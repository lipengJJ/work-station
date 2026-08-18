# 热点聚合模块（app/hotlist）· 统一重构技术设计

> **范围**：新建 `app/hotlist` 作为唯一的热点聚合域，同时**下线 `app/ai_trending`**——
> 原有 6 个技术源（HN / GitHub / arXiv / HF / InfoQ / 36氪）按新架构重写为 adapter 接入，
> 旧的 `TrendingSource` / `RawItem` / 时间衰减热度 / topic 订阅这套逻辑不保留。
> 唯一保留的是**定时推送**（配置模型 + 发送编排），改接新表。
>
> 借鉴来源：[TrendRadar](https://github.com/sansan0/TrendRadar) 的
> 热榜抓取、频率词 DSL、排名权重、新增检测。

---

## 一、统一的前提：所有源本质上都是「有序榜单」

这是这次能合并成一个模块的关键观察：

| 源 | 顺序含义 |
|---|---|
| 微博 / 知乎 / 抖音 / 头条…（NewsNow） | 平台自己的热榜排名 |
| Hacker News frontpage | 按 points 排的榜位 |
| GitHub Trending | 按 stars_today 排的榜位 |
| HF Models / Papers Trending | 按 trendingScore 排的榜位 |
| arXiv / InfoQ / 36氪（RSS/Atom） | 按发布时间倒序的位置 |

既然全部都是「一次抓取返回一个有序列表」，就可以共用同一套：
**条目表 + 排名时间线 + 权重公式 + 频率词过滤 + 新增检测 + 推送**。

原 `ai_trending` 之所以是另一套，是因为它把每个源的原始指标（points / stars / trendingScore）
各自归一化再做时间衰减——这套 `MAX_REF` 参考上限是拍脑袋定的（HN 10000、GitHub 5000、
HF 1000000），跨源可比性其实不强。**改用「榜位」做统一尺度反而更诚实**：
第 3 名就是第 3 名，不需要猜参考上限。原始指标降级为展示字段。

时间衰减这个好东西不丢，改成**每源可配的一个乘数**（见 §4.1），一个公式覆盖两类源。

---

## 二、废弃与新增对照

### 2.1 删除（后端 3664 行 + 前端 1310 行）

| 路径 | 行数 | 处置 |
|---|---|---|
| `backend/app/ai_trending/` 整个目录 | 3664 | 删除 |
| `frontend/.../views/ai-trending/` | 1310 | 删除 |
| `frontend/.../router/routes/modules/ai-trending.ts` | — | 删除 |
| `frontend/.../api/core/ai-trending.ts` | — | 删除 |
| `main.py` 里 3 个 ai_trending router + lifespan 里的 `register_all_enabled_jobs()` | — | 换成 hotlist |
| `core/database.py::init_db` 里 `from app.ai_trending import models` + `ensure_push_log_topic_id()` | — | 删除 |

旧表（`ai_trending_items` / `ai_trending_source_status` / `ai_trending_topics` /
`ai_trending_topic_hits` / `ai_trending_push_configs` / `ai_trending_push_logs`）
**弃用不迁数据**——热点数据本来就是 7 天滚动，新表建好跑一次全量抓取即满。
给一个 `backend/scripts/drop_legacy_ai_trending.py`（显式执行、不自动跑）清理老库。

### 2.2 逻辑去向（旧 → 新）

| 旧实现 | 新去向 |
|---|---|
| `services/base.py::TrendingSource` ABC | → `services/adapters/base.py::HotSourceAdapter`（签名改为返回带 rank 的有序列表） |
| `services/base.py::RawItem` | → `adapters/base.py::RawEntry`（加 `rank`，去 `heat_score`） |
| `services/base.py` 热度函数（`hn_heat` / `github_heat` / `paper_heat` / `hf_models_heat`） | **删除**，统一走 `ranking.py` 的榜位权重 |
| `services/base.py::normalize_url` / `url_hash` | → 提到 `app/common/utils/url.py`，补微博 `band_rank` 规则 |
| `services/base.py::parse_datetime` / `parse_struct_time` / `strip_html` | → `app/common/utils/text.py`（通用工具，别的域也能用） |
| `services/base.py::filter_ai_keywords` + `AI_KEYWORDS` 常量 | **删除**，由频率词规则表取代（能力严格更强） |
| `services/sources/hn.py` / `github.py` / `hf.py` / `arxiv.py` | → `services/adapters/` 下同名 adapter，只保留「请求 + 解析 + 排位」 |
| `services/sources/infoq.py` + `kr36.py` | → **合并**成一个配置化的 `adapters/rss.py`，源列表进 DB（照 TrendRadar 的 `rss.feeds` 思路） |
| `services/collector.py` | → `services/crawl_service.py`（重试/状态更新的骨架保留，去重键和入库逻辑重写） |
| `services/topic_service.py`（423 行主题订阅） | → **由频率词规则取代**。原「主题 = 一组关键词 + 命中记录 + 推送」正好是新的 `HotKeywordRule` + `HotRuleHit` + 推送配置，且新规则多出必须词/排除词/正则/限量 |
| `models/topic.py` + `topic_hit.py` | → `models/hot_keyword_rule.py` + `hot_rule_hit.py` |
| `services/push_service.py` + `push_webhook.py`（**保留**） | → `services/push_service.py`，编排与配置模型基本照搬，数据源换成新表 |
| `services/scheduler_jobs.py`（**写法保留**） | → `services/scheduler_jobs.py`，job id 前缀改 `hotlist_`，cron 配置从常量改为 DB 里每源一列 |
| `models/source_status.py` | → 合并进 `models/hot_source.py`（源字典与健康状态本来就是 1:1） |

### 2.3 净新增（移植自 TrendRadar，约 700 行）

`crawler/fetcher.py`（NewsNow 客户端 + 域名安全校验）、`core/frequency.py`（频率词 DSL）、
`core/analyzer.py::calculate_news_weight`（榜位权重）、`core/data.py`（新增检测）、
`storage/sqlite_mixin.py` 的脱榜检测段。

**不抄**：`report/html.py`(3221) / `notification/*`(4000+) / `ai/*` / `storage/remote.py` / `mcp_server/`
——这些工作台都已有更好的（Vue 前端、`notify_service`、`ai_gateway`）。

---

## 三、目录结构

```
backend/app/hotlist/
├── models/
│   ├── __init__.py
│   ├── hot_source.py          源字典 + 健康状态（原 platforms + source_status 合并）
│   ├── hot_item.py            条目主记录
│   ├── hot_rank_history.py    榜位时间线（含脱榜 rank=0）
│   ├── hot_crawl_record.py    批次记录 + 各源成败
│   ├── hot_keyword_rule.py    频率词规则（吸收原 topic 订阅）
│   ├── hot_rule_hit.py        规则命中记录（吸收原 topic_hit，推送去重用）
│   ├── hot_push_config.py     推送配置（保留）
│   └── hot_push_log.py        推送记录（保留）
├── schemas/
│   ├── __init__.py
│   ├── source.py              SourceIn / SourceOut
│   ├── rule.py                RuleIn / RuleOut / RulePreviewIn / RulePreviewOut
│   ├── item.py                ItemQuery / ItemOut / RankPointOut
│   ├── digest.py              DigestQuery / DigestOut / DigestGroupOut
│   └── push.py                PushConfigIn / PushConfigOut / PushLogOut
├── services/
│   ├── __init__.py
│   ├── adapters/
│   │   ├── __init__.py        registry（注册表，写法沿用旧 sources/__init__.py）
│   │   ├── base.py            HotSourceAdapter ABC + RawEntry
│   │   ├── newsnow.py         ← TrendRadar fetcher.py，一个类驱动全部中文热榜平台
│   │   ├── hackernews.py      ← 重写自 sources/hn.py
│   │   ├── github.py          ← 重写自 sources/github.py
│   │   ├── huggingface.py     ← 重写自 sources/hf.py（models + papers）
│   │   ├── arxiv.py           ← 重写自 sources/arxiv.py
│   │   └── rss.py             ← infoq.py + kr36.py 合并，feed 配置进 DB
│   ├── keyword_rules.py       ← TrendRadar core/frequency.py，输入换 DB
│   ├── ranking.py             ← TrendRadar analyzer.py 权重公式
│   ├── crawl_service.py       抓取编排：重试 → upsert → 榜位历史 → 脱榜 → 状态
│   ├── diff_service.py        ← TrendRadar core/data.py，改 SQL
│   ├── digest_service.py      三模式摘要组装（daily / incremental / current）
│   ├── push_service.py        ← 保留原 push_service + push_webhook，改接新表
│   └── scheduler_jobs.py      ← 保留原写法，前缀改 hotlist_
└── controllers/
    ├── __init__.py
    ├── sources.py             源管理（开关 / 改名 / 抓取频率 / 健康状态）
    ├── hotlist.py             榜单查询 / 条目详情 / 手动抓取
    ├── rules.py               规则 CRUD + 导入 + 试跑预览
    ├── digest.py              摘要（三模式）
    └── push.py                推送配置 + 发送记录（保留）
```

前端：

```
frontend/apps/web-antd/src/
├── router/routes/modules/hotlist.ts     侧边栏「热点聚合」（替换原「AI 开发热点」）
├── api/core/hotlist.ts
└── views/hotlist/
    ├── board/       榜单（源分组 Tab：中文热榜 / 技术源；榜位 + 趋势迷你图 + 命中高亮）
    ├── digest/      热点摘要（三模式切换 + 按词组分区）
    ├── rules/       频率词规则可视化编辑 + 试跑
    └── sources/     源管理（开关 / 频率 / 健康状态角标）
```

> 原 `views/ai-trending/index.vue` 是 1156 行的单文件页。新页面按上面四块拆开，
> 每块的表格/筛选区复用 `views/xhs/_shared` 那套（和小红书模块视觉保持一致）。

---

## 四、数据模型

### 4.1 HotSource — 源字典 + 健康状态

```python
class HotSource(Base):
    __tablename__ = "hot_sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)   # "weibo" / "hackernews"
    name: Mapped[str] = mapped_column(String(64), default="")       # 显示名，可改
    source_kind: Mapped[str] = mapped_column(String(16), default="hotlist", index=True)
                                    # hotlist = 中文热榜 / tech = 技术源
    adapter: Mapped[str] = mapped_column(String(32), default="")    # 注册表里的 adapter key
    adapter_params: Mapped[str] = mapped_column(Text, default="{}") # JSON：NewsNow 平台 id / RSS url
    expected_domain: Mapped[str] = mapped_column(String(128), default="")  # 域名安全校验
    decay_half_life_hours: Mapped[float] = mapped_column(Float, default=0.0)
                                    # 0 = 不衰减（热榜）；24 = 论文/RSS；48 = HN/GitHub
    cron_expr: Mapped[str] = mapped_column(String(64), default="*/30 * * * *")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    # ---- 健康状态（原 AiTrendingSourceStatus 的字段，原样并进来）----
    last_fetched_at / last_status / last_error / consecutive_failures
    fail_count / last_success_at / total_fetched
```

**一个 adapter 可以对应多行源**：`newsnow` adapter 对应 11 行（微博/知乎/抖音…），
`adapter_params = {"platform": "weibo"}`；`rss` adapter 对应 InfoQ / 36氪 / 任意自定义 feed，
`adapter_params = {"url": "..."}`。**加一个 RSS 源不用写代码，前端点一下就行**——
这是相对旧模块（infoq.py / kr36.py 各一个类）的实质改进。

`cron_expr` 入库意味着抓取频率可以在前端改，不用像旧的 `JOB_CRON` 常量那样改代码重启。

### 4.2 HotItem — 条目

```python
class HotItem(Base):
    __tablename__ = "hot_items"
    __table_args__ = (
        Index("ux_hot_items_source_url", "source_id", "url",
              unique=True, sqlite_where=text("url != ''")),
        Index("ix_hot_items_source_last", "source_id", "last_crawl_time"),
        Index("ix_hot_items_date_weight", "stat_date", "weight"),
    )
    id / source_id / title / url / mobile_url / summary
    stat_date: Mapped[str]      # YYYY-MM-DD，按天分域（替代 TrendRadar 的一天一文件）
    rank: Mapped[int]           # 最新榜位
    best_rank: Mapped[int]      # 历史最佳
    first_crawl_time / last_crawl_time / crawl_count
    published_at: Mapped[datetime | None]   # 有的源给（RSS/arXiv），没有则 None
    metrics: Mapped[str]        # JSON：points / stars_today / trendingScore，仅展示
    weight: Mapped[float]       # 写入时算好，列表页直接 ORDER BY
```

去重键说明：`(source_id, url)` 部分唯一索引（url 非空时）。URL 为空的条目（少数热榜没链接）
不参与唯一约束，靠 `(source_id, stat_date, title)` 在应用层查一次。
跨源同 URL **不再合并**——旧模块「跨源同 URL 只保留热度最高的一条」会丢掉
「HN 和 GitHub 同时上榜」这个本身有价值的信号。改为各源独立存，前端展示时可选按 URL 折叠。

### 4.3 统一权重（`ranking.py`）

```python
def calculate_weight(ranks, count, rank_threshold, weight_config, decay) -> float:
    rank_weight      = (Σ(11 - min(r, 10)) / len(ranks)) * 10       # 归一到 0~100
    frequency_weight = min(count, 10) * 10
    hotness_weight   = (排名 <= rank_threshold 的次数 / len(ranks)) * 100
    base = rank_weight*W1 + frequency_weight*W2 + hotness_weight*W3   # 默认 .6/.3/.1
    return round(base * decay, 2)
```

`decay` 由源的 `decay_half_life_hours` 决定：

```python
decay = 1.0 if half_life <= 0 else 0.5 ** (hours_since(published_at) / half_life)
```

这样：中文热榜 `half_life=0` → 纯榜位权重（TrendRadar 行为）；
arXiv / RSS `half_life=24` → 保留旧 ai_trending 的时间衰减手感。**一个公式，两类源。**

三个系数进系统设置（`ApiConfig`：`hotlist_rank_weight` / `hotlist_frequency_weight` /
`hotlist_hotness_weight`），默认沿用 TrendRadar 的 0.6 / 0.3 / 0.1。

### 4.4 HotRankHistory / HotCrawlRecord

```python
class HotRankHistory(Base):
    __tablename__ = "hot_rank_history"
    __table_args__ = (Index("ix_hot_rank_item_time", "item_id", "crawl_time"),)
    id / item_id / rank / crawl_time        # rank = 0 表示脱榜
```

脱榜检测（移植自 `sqlite_mixin.py`）：上一批次在榜、本批次不在的条目，插一条 `rank=0`。
排名曲线掉到底就是脱榜，不用单独建表。

> 原实现是每源一次全表扫 + Python 集合差。工作台改成一条 SQL：
> `SELECT id FROM hot_items WHERE source_id=? AND last_crawl_time=:prev AND url NOT IN (:current)`，
> 当前 URL 多时先写临时表再 `LEFT JOIN`。

```python
class HotCrawlRecord(Base):
    __tablename__ = "hot_crawl_records"
    id / crawl_time(unique) / total_items / created_at

class HotCrawlSourceStatus(Base):     # 批次内每源成败
    crawl_record_id / source_id / status  # PK(crawl_record_id, source_id)
```

### 4.5 HotKeywordRule — 频率词规则（吸收原 topic 订阅）

```python
class HotKeywordRule(Base):
    __tablename__ = "hot_keyword_rules"

    id
    rule_type: Mapped[str]        # group = 词组 / global_filter = 全局过滤
    display_name: Mapped[str]     # 组别名（原 topic 的名字）
    normal_words: Mapped[str]     # JSON: 普通词（OR）
    required_words: Mapped[str]   # JSON: 必须词（AND）
    exclude_words: Mapped[str]    # JSON: 排除词
    source_ids: Mapped[str]       # JSON: 限定源；[] = 全部源
    max_count: Mapped[int]        # 每组最多显示条数，0 = 不限
    enabled / sort_order

    # ---- 推送配置（原 topic 的订阅语义，字段设计对齐 XhsTrackingTask）----
    notify_enabled: Mapped[bool]
    notify_channel_ids: Mapped[str]      # JSON 数组，指向 NotificationConfig.id
    notify_time_start / notify_time_end  # HH:MM 静默时段
    notify_frequency: Mapped[str]        # realtime / hourly / daily
    notify_only_on_hit: Mapped[bool]
    notify_pending_hits / notify_pending_since
```

每个词存成 `{"word": "京东", "is_regex": false, "display_name": null}`——
正是 `frequency.py::_parse_word` 的输出结构，**解析器的产物结构照搬，只换输入源**。

```python
class HotRuleHit(Base):          # 原 AiTrendingTopicHit
    __tablename__ = "hot_rule_hits"
    __table_args__ = (UniqueConstraint("rule_id", "item_id"),)
    id / rule_id / item_id / matched_at / notified: bool
```

`(rule_id, item_id)` 唯一约束保证同一条目对同一规则只推一次。

`keyword_rules.py` 的移植原则——**保持与原函数同签名，下游零改动**：

```python
def load_rules(db: Session) -> tuple[list[dict], list[dict], list[str]]:
    """返回 (word_groups, filter_words, global_filters)，
    与 TrendRadar load_frequency_words() 同签名，
    于是 matches_word_groups() 等匹配逻辑可以一行不改地用上。"""

def parse_frequency_text(text: str) -> ...:
    """保留原文本 DSL 解析，用于 POST /rules/import 一次性导入。"""
```

`_parse_word` / `_word_matches` / `matches_word_groups` 三个纯函数**逐行照搬**，
它们是这次移植里最该写单测的部分。

### 4.6 推送（保留）

`HotPushConfig` / `HotPushLog` 字段沿用原 `ai_trending` 的两张表，
`push_service.py` 的编排（读配置 → 取时间窗内条目 → 渲染 → 发送 → 记录）保留，
两处改动：

1. 数据源从 `AiTrendingItem` 换成 `HotItem` + `HotRuleHit`；
2. 发送统一走 `notify_service.send_task_hits_to_channels(db, channel_ids, title, content)`，
   删掉 `push_webhook.py`（283 行自建 webhook 发送）——你已有企微 / Server酱多通道 + 发送记录。

定时推送 job（`register_push_job` 那套 `enabled + 非空校验 → add_job / unregister` 的幂等写法）
原样保留，只改 job id 前缀。

---

## 五、抓取编排（`crawl_service.py`）

```
for source in enabled_sources:                    # 串行，源间随机间隔 100±20ms
    entries = fetch_with_retry(adapter, source)   # 初始 + 2 次重试（5s / 15s 退避）
    if source.expected_domain:                    # 域名安全校验，不过则整源丢弃
        check_domain_safety(entries, source.expected_domain)
    upsert_items(entries)                         # 去重 + 更新 rank / crawl_count
    write_rank_history(entries)
    detect_off_list(source, prev_crawl_time)      # 脱榜 → rank=0
    recompute_weights(source)                     # 写入时算好 weight
    match_rules_and_record_hits(source)           # 命中规则 → HotRuleHit
    update_source_status(source, ok/err)
write_crawl_record()
```

重试骨架、`update_source_status` 的成功清零/失败累加语义，都直接沿用原 `collector.py`——
那部分写得没问题，只是入库逻辑要换。

域名安全校验（移植 `fetcher.py::_check_domain_safety`）值得点名：
用 `urlparse().hostname` 而非字符串包含，挡住 `https://baidu.com@evil.com` 这类 userinfo 绕过，
同时校验 `url` 和 `mobileUrl`，要求 HTTPS。用公共 NewsNow 实例时必须开。

---

## 六、三种摘要模式（`digest_service.py`）

| 模式 | 语义 | 数据范围 |
|---|---|---|
| `daily` | 当日汇总 | `stat_date = 今天` 全部 |
| `incremental` | 只看新增 | 最新批次 − 历史批次（当天首次抓取时全算新增） |
| `current` | 当前榜单 | `last_crawl_time == 最新批次时间`，但统计信息取全历史 |

新增检测的核心判据（源自 `data.py`）：

> 一个标题只要其 `first_crawl_time < 最新批次时间` 就算历史标题。
> 即使同标题有多条记录（URL 不同），只要任一条是历史的，整个标题就不算新增。

原实现把全天数据拉进内存做集合差，改成一条 SQL 即可。

`count_word_frequency`（400 行、17 个参数）**不要整段照抄**。它把模式判断、词组匹配、
统计、排序、限量全揉在一起，是 CLI 里为了避免全局状态一路传参的产物。拆成四个纯函数：

```python
select_scope(db, mode, stat_date, source_ids) -> list[HotItem]
match_groups(items, rules)                    -> dict[rule_id, list[HotItem]]
rank_within_group(items, weight_config)       -> list[HotItem]     # 排序 + max_count
build_digest(grouped)                         -> DigestOut
```

---

## 七、分阶段实施

### Phase 0 · 拆除（约 0.5 天）

- [ ] 删 `backend/app/ai_trending/`、前端 `views/ai-trending/` + 路由 + api 文件
- [ ] `main.py` 去掉 3 个 router 与 lifespan 里的 ai_trending 注册
- [ ] `core/database.py::init_db` 去掉 ai_trending models import 与 `ensure_push_log_topic_id()`
- [ ] `app/common/utils/url.py` + `text.py`：把 `normalize_url` / `url_hash` /
      `parse_datetime` / `parse_struct_time` / `strip_html` 提出来（**先提再删**，别丢了）
- [ ] `backend/scripts/drop_legacy_ai_trending.py`（手动执行）

> 顺序很重要：先把要复用的纯函数提到 common 并跑通 import，再删目录。

### Phase 1 · 骨架 + 中文热榜（约 1 天）

- [ ] 8 张表 + `init_db()` 注册
- [ ] `adapters/base.py`（`HotSourceAdapter` + `RawEntry`）+ registry
- [ ] `adapters/newsnow.py`：移植 `fetch_data` / `crawl_websites` / `_check_domain_safety`，
      print → loguru，api_url 从 `ApiConfig` 读（`hotlist_newsnow_api_url`，留空用公共实例）
- [ ] `crawl_service.py` 全流程 + `controllers/sources.py` + `controllers/hotlist.py`
- [ ] seed：11 个中文热榜源（含 `expected_domain`）
- [ ] 前端「榜单」+「源管理」两页

**验收**：手动触发一次，11 个平台入库；断网/脏数据时源状态标红且不影响其他源。

### Phase 2 · 技术源迁回（约 1 天）

- [ ] `adapters/hackernews.py` / `github.py` / `huggingface.py` / `arxiv.py`：
      从旧 `sources/*.py` 改写，**只保留请求 + 解析**，输出改为带 `rank` 的 `RawEntry`
- [ ] `adapters/rss.py`：合并 infoq + kr36，feed 地址走 `adapter_params`
- [ ] seed：6 个技术源（`source_kind="tech"`，`decay_half_life_hours` 分别配好）
- [ ] 前端榜单页按 `source_kind` 分组 Tab

**验收**：技术源条目与旧模块抓到的一致（对比一次结果）；榜位排序合理。

### Phase 3 · 频率词规则（核心价值，约 1 天）

- [ ] `keyword_rules.py`：`_parse_word` / `_word_matches` / `matches_word_groups` 照搬（**先写单测**）
- [ ] `load_rules()` + `parse_frequency_text()`
- [ ] `controllers/rules.py`：CRUD + `/import`（粘贴 TrendRadar 文本）+ `/preview`（试跑）
- [ ] 命中记录 `HotRuleHit` 写入接进 `crawl_service`
- [ ] 前端「规则」页：词组卡片（普通/必须/排除 三色标签）+ 正则开关 + 试跑抽屉

**验收**：正则、必须词、排除词、全局过滤、限量五种语法都生效；保存前能试跑看到命中样例。

### Phase 4 · 权重 + 摘要 + 推送（约 1 天）

- [ ] `ranking.py` 权重公式 + 系数进系统设置；写入时落 `weight` 列
- [ ] `diff_service.py` 新增检测（SQL 版）
- [ ] `digest_service.py` 四步拆分 + `controllers/digest.py`
- [ ] `push_service.py` 改接新表，删 `push_webhook.py`，走 `notify_service`
- [ ] `scheduler_jobs.py`：每源按 `cron_expr` 注册 + 推送 job + 每日清理
- [ ] 前端「摘要」页 + 条目详情榜位曲线（含脱榜段）

**验收**：三模式条数关系合理（incremental ≤ current ≤ daily）；规则命中能按配置时段推送且不重复推。

---

## 八、移植时的坑

1. **别照抄 `print`**。TrendRadar 是 CLI，全程 print，工作台要 loguru。
2. **别照抄「一天一个 SQLite 文件」**（`_get_connection(data.date)`），用 `stat_date` 列。
3. **正则来自用户输入**。保存规则时 `re.compile` 校验并返回 400（原代码是打 warning 后降级成
   子串匹配，Web 端不该静默降级），另加模式长度上限防灾难性回溯。
4. **`ranks` 列表的存储**。权重公式要历史全部榜位，别每次去 `hot_rank_history` 聚合；
   在 `HotItem` 上加个 `ranks_json` 缓存列（最多留最近 N 次），写入时顺带更新。
5. **旧模块的 `MAX_REF` 别带过来**。那些参考上限（HN 10000 / GitHub 5000 / HF 1000000）
   是拍脑袋的，新模型不需要。原始指标存进 `metrics` 只做展示。
6. **公共 NewsNow 实例不保证可用**，`expected_domain` 必开，源状态表要如实记录失败，
   前端源 Tab 挂警示角标（这个交互旧模块已经有，照做）。
7. **先提公共函数再删旧目录**（Phase 0 那条），否则 `normalize_url` 这种写得不错的实现容易被一起删掉。

---

## 九、许可与合规

移植文件头部注明来源，例如：

```python
"""频率词 DSL 解析与匹配。

移植自 TrendRadar (https://github.com/sansan0/TrendRadar) core/frequency.py，
改动：配置输入从文本文件换成数据库行；解析产物结构与匹配逻辑保持一致。
"""
```

NewsNow 公共实例是第三方服务，生产建议自建（`api_url` 已可配置）。
本模块与工作台其余部分一样仅供个人学习研究，见 `DISCLAIMER.md`。
