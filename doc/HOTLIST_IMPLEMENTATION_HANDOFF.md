# 热点聚合模块（app/hotlist）· 实施交接文档

> 配套设计文档：[HOTLIST_INTEGRATION_DESIGN.md](./HOTLIST_INTEGRATION_DESIGN.md)（**先读那份**，
> 讲清楚了为什么这么设计、哪些逻辑从哪来、哪些刻意不抄）。
> 本文档只讲**怎么落地**：当前进度、剩余待办、每个文件的实现规格。
>
> 面向 CLI（Claude Code）执行。当前分支 `feature/hotlist`（从 `main` 拉出）。

---

## 〇、先跑这一条（环境遗留清理）

之前的会话在云端沙箱里操作，**沙箱不允许删除挂载目录里的文件**，导致两件事需要手动收尾：

```bash
cd /Users/lipeng01/vscode/workbench

# 1. 清掉残留的 git 索引锁（空文件，沙箱删不掉；不清 git 无法 add/commit）
rm -f .git/index.lock .git/index.lock.stale

# 2. 真正删除「已移出但没删掉」的旧代码
rm -rf _to_delete/

# 3. 确认 git 恢复正常
git status
```

`_to_delete/` 里是被移出去的旧代码（等价于已删除，因为已不在 import 路径/构建范围内）：

| `_to_delete/` 下的路径 | 原路径 |
|---|---|
| `backend/ai_trending/` | `backend/app/ai_trending/`（3664 行） |
| `frontend/views_ai-trending/` | `frontend/apps/web-antd/src/views/ai-trending/`（1310 行） |
| `frontend/routes_ai-trending.ts` | `.../router/routes/modules/ai-trending.ts` |
| `frontend/api_ai-trending.ts` | `.../api/core/ai-trending.ts` |
| `_probe_mount` | 环境探测用的空文件，无意义 |

> 删之前如果想回看旧实现（比如 `push_service.py` 的推送编排要照搬），
> 现在还在 `_to_delete/backend/ai_trending/` 下，或者 `git show main:backend/app/ai_trending/services/push_service.py`。

---

## 一、已完成（Phase 0，无需重做）

### 1.1 公共工具已提取 ✅

旧 `ai_trending/services/base.py` 里几个写得不错的纯函数已经提到公共位置——**这一步必须先于删除**，
否则会连着一起丢：

**`backend/app/common/utils/url.py`**
- `normalize_url(url)` — 归一化：小写 scheme/host、HTTPS_ONLY_HOSTS 抬升、丢 utm_*/跟踪参数、
  去尾斜杠、arXiv 去版本号、HF 收敛到 `{model_id}`
- `url_hash(url)` — 归一化后的 MD5
- **新增** `PLATFORM_DROP_PARAMS` — 平台专属动态参数。微博热搜链接带 `band_rank`（榜位）和 `Refer`，
  抓 10 次就是 10 条不同 URL，不去掉根本没法按 URL 去重。已配微博/知乎/头条/澎湃。

**`backend/app/common/utils/text.py`**
- `parse_datetime` / `parse_struct_time` / `strip_html`（从旧 base.py 搬）
- **新增** `truncate(text, limit)` — 落库前控 summary 长度
- **新增** `hours_since(dt, now)` — 时间衰减要用（旧 base.py 里也有，一并搬过来）

### 1.2 旧模块已下线 ✅

- `backend/app/ai_trending/` → 移到 `_to_delete/`
- 前端 `views/ai-trending/` + 路由 + `api/core/ai-trending.ts` → 移到 `_to_delete/`
- `frontend/.../api/core/index.ts`：去掉 `export * from './ai-trending'`，加上 `export * from './hotlist'`
- `backend/app/core/database.py::init_db`：去掉 ai_trending models import 与 `ensure_push_log_topic_id()`，
  换成 `from app.hotlist import models as hotlist_models`
- `backend/app/main.py`：3 个 ai_trending router → `hotlist_api` + `hotlist_sources_api`；
  lifespan 里 `ai_trending_scheduler_jobs.register_all_enabled_jobs()` →
  `hotlist_source_service.seed_default_sources()` + `hotlist_scheduler_jobs.register_all_enabled_jobs()`

> ⚠️ **main.py 目前引用的模块还没写**（`app.hotlist.controllers.hotlist` / `.sources`、
> `app.hotlist.services.source_service` / `.scheduler_jobs`），所以**后端现在起不来**。
> 这是预期状态，Phase 1 写完就好。想先跑起来的话，把 main.py 里这几行临时注释掉。

### 1.3 已写好的 model ✅

`backend/app/hotlist/models/` 下四个文件已完成，注释里写了设计取舍，直接用：

- `hot_source.py` — `HotSource`（源字典 + 健康状态合并成一张表）
- `hot_item.py` — `HotItem`（条目，含 `stat_date` / `ranks_json` / `metrics` / `weight`）
- `hot_rank_history.py` — `HotRankHistory`（榜位时间线，`rank=0` 表示脱榜）
- `hot_crawl_record.py` — `HotCrawlRecord` + `HotCrawlSourceStatus`

---

## 二、Phase 1 · 骨架 + 中文热榜（待办）

### 2.1 `models/__init__.py`

```python
from app.hotlist.models.hot_crawl_record import HotCrawlRecord, HotCrawlSourceStatus
from app.hotlist.models.hot_item import HotItem
from app.hotlist.models.hot_rank_history import HotRankHistory
from app.hotlist.models.hot_source import HotSource

__all__ = ["HotCrawlRecord", "HotCrawlSourceStatus", "HotItem", "HotRankHistory", "HotSource"]
```

（对齐 `app/xhs/models/__init__.py` 的写法。）

### 2.2 `services/adapters/base.py`

```python
class RawEntry(BaseModel):
    """adapter 产出的标准化条目。不落库，crawl_service 负责入库。

    与旧 ai_trending 的 RawItem 的关键差别：有 rank（榜位），没有 heat_score。
    打分统一由 ranking.py 按榜位算，adapter 不参与打分——这样新增一个源
    只需要「请求 + 解析 + 按返回顺序排位」，不用再拍一个 MAX_REF 参考上限。
    """
    rank: int = 0                 # 1 起；adapter 按返回顺序 enumerate 填
    title: str = ""
    url: str = ""
    mobile_url: str = ""
    summary: str = ""
    published_at: datetime | None = None
    metrics: dict = Field(default_factory=dict)   # points / stars_today… 仅展示


class HotSourceAdapterError(Exception):
    """抓取/解析失败，message 可直接展示给用户。"""


class HotSourceAdapter(ABC):
    """抓取器抽象。一个 adapter 可服务多行 HotSource（靠 params 区分）。

    新增一个源的三种情况：
      1. 已有 adapter 能覆盖（如再加一个 RSS 源）→ 前端加一行，零代码
      2. 新协议 → 写一个 adapter 子类 + 注册一行 + seed 一行源
      3. NewsNow 已支持的平台 → seed 一行源即可
    """
    adapter_key: str = ""

    @abstractmethod
    def fetch(self, params: dict) -> list[RawEntry]:
        """返回有序列表（rank 已填）。失败抛 HotSourceAdapterError。"""

    def _request(self, url, timeout=20, headers=None) -> requests.Response:
        """统一 GET：超时 + 异常语义收敛为 HotSourceAdapterError。"""
        # 照搬旧 base.py::TrendingSource._request，改异常类型


registry: dict[str, HotSourceAdapter] = {}
def register(adapter): ...
def get(key) -> HotSourceAdapter: ...
```

### 2.3 `services/adapters/newsnow.py` ← 移植 TrendRadar `crawler/fetcher.py`

移植要点（原文件 238 行，改完约 180 行）：

| 原实现 | 改法 |
|---|---|
| `DEFAULT_API_URL = "https://newsnow.busiyi.world/api/s"` | 保留为默认值，实际地址从 `ApiConfig` 读 key `hotlist_newsnow_api_url`，留空用默认 |
| `print(...)` | → `loguru.logger` |
| `fetch_data()` 内的重试循环（2 次、3~5s 随机退避 + 递增） | 原样保留 |
| `crawl_websites()` 批量循环 | **不要移植**——批量编排归 `crawl_service.py`，adapter 只管单个源 |
| `_check_domain_safety(items, expected_domain)` | **原样移植**到本文件（或 `services/security.py`），见下 |
| 请求间隔 `request_interval + random.randint(-10, 20)` | 移到 `crawl_service.py` 的源间循环里 |

`_check_domain_safety` 值得单独强调，这段照抄不要改：

```python
# 用 urlparse().hostname 而不是字符串包含，否则 https://baidu.com@evil.com 能绕过校验
parsed = urlparse(url)
if parsed.scheme != "https": return f"{url} (非 HTTPS 或格式异常)"
hostname = (parsed.hostname or "").lower()
if hostname != expected and not hostname.endswith("." + expected): return ...
# url 和 mobileUrl 两个字段都要校验；任一不过 → 整个源本次数据丢弃 + 记 failed
```

`fetch(params)` 的实现：

```python
def fetch(self, params: dict) -> list[RawEntry]:
    platform = params["platform"]                    # "weibo" / "zhihu" ...
    url = f"{self._api_url()}?id={platform}&latest"
    data = self._get_json_with_retry(url)
    if data.get("status") not in ("success", "cache"):
        raise HotSourceAdapterError(f"响应状态异常: {data.get('status')}")
    entries = []
    for idx, item in enumerate(data.get("items", []), 1):
        title = item.get("title")
        # 跳过无效标题（None / float / 空串）——原实现踩过这个坑，保留
        if title is None or isinstance(title, float) or not str(title).strip():
            continue
        entries.append(RawEntry(rank=idx, title=str(title).strip(),
                                url=item.get("url", ""), mobile_url=item.get("mobileUrl", "")))
    return entries
```

> 注意：原实现里同一标题出现多次会把 index 追加进 `ranks`。新模型不需要——
> 同批次内重复出现是数据源自己的问题，按 URL 去重后取最小 rank 即可（在 crawl_service 处理）。

### 2.4 `services/source_service.py`

```python
DEFAULT_SOURCES = [
    # id, name, expected_domain —— 取自 TrendRadar config/config.yaml 的 platforms.sources
    ("toutiao", "今日头条", "toutiao.com"),
    ("baidu", "百度热搜", "baidu.com"),
    ("wallstreetcn-hot", "华尔街见闻", "wallstreetcn.com"),
    ("thepaper", "澎湃新闻", "thepaper.cn"),
    ("bilibili-hot-search", "bilibili 热搜", "bilibili.com"),
    ("cls-hot", "财联社热门", "cls.cn"),
    ("ifeng", "凤凰网", "ifeng.com"),
    ("tieba", "贴吧", "baidu.com"),
    ("weibo", "微博", "weibo.com"),
    ("douyin", "抖音", "douyin.com"),
    ("zhihu", "知乎", "zhihu.com"),
]

def seed_default_sources() -> None:
    """幂等 seed（已存在的 id 跳过，不覆盖用户改过的 name/cron/enabled）。
    在 main.py lifespan 里调用，参照 skills_registry.scan_on_startup() 的位置。"""
```

`decay_half_life_hours` 全部为 `0`（热榜不衰减），`cron_expr` 默认 `*/30 * * * *`，
`source_kind="hotlist"`，`adapter="newsnow"`，`adapter_params={"platform": <id>}`。

再加 CRUD：`list_sources` / `update_source`（改名/开关/cron/expected_domain）/
`create_source`（自定义源）/ `delete_source`。

### 2.5 `services/crawl_service.py`（核心编排，新写）

```
run_crawl(db, source_ids=None, trigger="cron") -> CrawlResult:
    crawl_time = now()                       # 本批次统一时间戳，别用各条目写入时间
    stat_date  = crawl_time.date()
    for source in enabled_sources:           # 串行
        try:
            entries = adapter.fetch(source.adapter_params)   # 内含重试
            if source.expected_domain:
                bad = check_domain_safety(entries, source.expected_domain)
                if bad: raise HotSourceAdapterError(...)      # 整源丢弃
            upsert_items(db, source, entries, crawl_time, stat_date)
            write_rank_history(db, ...)
            detect_off_list(db, source, prev_crawl_time, current_urls)
            recompute_weights(db, source, stat_date)
            update_source_status(db, source, ok=True, fetched=len(entries))
        except Exception as exc:
            update_source_status(db, source, ok=False, error=str(exc))
            # 不 re-raise：任一源失败不阻塞其他源（沿用旧 collector.py 的语义）
        sleep(random.uniform(0.08, 0.12))     # 源间随机间隔，防限流
    write_crawl_record(db, ...)
```

几个实现细节：

- **`upsert_items`**：按 `(source_id, normalize_url(url))` 查已有行。
  命中 → 更新 `title/rank/mobile_url/last_crawl_time`，`crawl_count += 1`，
  `best_rank = min(best_rank, rank)`，`ranks_json` 追加（保留最近 50 个）。
  未命中 → 插入，`first_crawl_time = last_crawl_time = crawl_time`。
  URL 为空 → 按 `(source_id, stat_date, title)` 查。
- **`detect_off_list`**：上批在榜、这批不在的条目，插一条 `rank=0` 的 `HotRankHistory`。
  **别照抄 TrendRadar 的实现**（每源全表扫 + Python 集合差），用一条 SQL：
  ```sql
  SELECT id FROM hot_items
  WHERE source_id = :sid AND last_crawl_time = :prev AND url != ''
    AND url NOT IN (:current_urls)
  ```
  当前 URL 超过 ~500 条时先写临时表再 LEFT JOIN（SQLite 参数上限 999）。
- **`update_source_status`**：成功 → 清零 `consecutive_failures`、刷新 `last_success_at`、
  `total_fetched += n`；失败 → `consecutive_failures += 1`，连续 ≥3 时 `fail_count += 1`。
  这套语义直接沿用旧 `collector.py::_update_status`。

### 2.6 `services/ranking.py`（Phase 1 先用简化版）

Phase 1 只需要能排序，先实现 `calculate_weight`，`decay` 传 1.0：

```python
def calculate_weight(ranks: list[int], count: int, rank_threshold: int,
                     weight_config: dict, decay: float = 1.0) -> float:
    if not ranks: return 0.0
    rank_score_sum = sum(11 - min(r, 10) for r in ranks if r > 0)
    high_rank_count = sum(1 for r in ranks if 0 < r <= rank_threshold)
    n = len([r for r in ranks if r > 0]) or 1
    rank_weight      = (rank_score_sum / n) * 10        # 归一到 0~100
    frequency_weight = min(count, 10) * 10
    hotness_weight   = (high_rank_count / n) * 100
    base = (rank_weight * weight_config["RANK_WEIGHT"]
            + frequency_weight * weight_config["FREQUENCY_WEIGHT"]
            + hotness_weight * weight_config["HOTNESS_WEIGHT"])
    return round(base * decay, 2)
```

三项都先归一到 0~100 再加权，所以系数可以当"占比"读。默认 0.6 / 0.3 / 0.1，
Phase 4 时接进系统设置（`ApiConfig` 的 `hotlist_rank_weight` 等）。

`decay` 的完整形式（Phase 2 技术源接入时才需要）：

```python
decay = 1.0 if source.decay_half_life_hours <= 0 else \
        0.5 ** (hours_since(item.published_at) / source.decay_half_life_hours)
```

### 2.7 `schemas/` + `controllers/`

**`schemas/source.py`**：`SourceOut`（含健康状态）/ `SourceIn`（name / enabled / cron_expr /
expected_domain / decay_half_life_hours / sort_order）
**`schemas/item.py`**：`ItemOut`（含 `metrics` / `ranks` 的 JSON 字符串 → 对象的
`field_validator(mode="before")`，写法照抄旧 `schemas/trending.py::_parse_heat_meta`）、`ItemPage`

**`controllers/sources.py`** — `prefix="/api/hotlist/sources"`：
- `GET /` 源列表 + 健康状态
- `PUT /{source_id}` 更新
- `POST /` 新建自定义源（主要给 RSS 用）
- `DELETE /{source_id}`

**`controllers/hotlist.py`** — `prefix="/api/hotlist"`：
- `GET /items` 分页列表（`source_id` / `source_kind` / `stat_date` / `sort`(weight|rank|time) 筛选）
- `GET /items/{id}` 详情 + 榜位时间线（`HotRankHistory` 按 `crawl_time` 升序）
- `POST /crawl` 手动触发（**限频 + daemon 线程异步**，逻辑照搬旧
  `controllers/trending.py::manual_refresh`，那段写得没问题：进程内 `threading.Lock` +
  时间戳，冷却期内返回 429）

所有接口 `Depends(get_current_user)`，与其他模块一致。

### 2.8 `services/scheduler_jobs.py`

照搬旧 `ai_trending/services/scheduler_jobs.py` 的写法，三处改动：

1. job id 前缀 `ai_trending_` → `hotlist_`
2. cron 配置从 `JOB_CRON` 常量 → 读 `HotSource.cron_expr`（用 `CronTrigger.from_crontab()`）
3. `register_all_enabled_jobs()` 里对 `enabled=False` 的源要 **`remove_job` 兜底**，
   否则前端关掉一个源、重启前 job 还在跑

保留的好习惯（别改）：`replace_existing=True` 保证重启幂等；job 内 `SessionLocal()` 自开自关
（调度器线程不能跨线程共享 Session）；`except Exception: logger.exception(...)` 兜底，
不让异常打到调度器线程。

### 2.9 前端（Phase 1）

- `router/routes/modules/hotlist.ts` — 侧边栏「热点聚合」，`icon: 'lucide:flame'`，
  `order` 沿用原 ai-trending 的 `1.7`，下挂 `board` / `sources` 两个子路由
- `api/core/hotlist.ts` — namespace `HotlistApi`，写法照原 `ai-trending.ts`
- `views/hotlist/board/index.vue` — 源分组 Tab（中文热榜 / 技术源）+ 榜单表格
  （榜位、标题、`crawl_count`、`weight`、首次/最后出现时间）+ 手动刷新按钮 + 源状态角标
- `views/hotlist/sources/index.vue` — 源管理（开关、改名、cron、expected_domain、健康状态）

表格/筛选区复用 `views/xhs/_shared` 那套组件，和小红书模块视觉保持一致。
**别再写成 1156 行的单文件页**（原 `views/ai-trending/index.vue` 的问题），按子路由拆开。

### 2.10 Phase 1 验收

```bash
cd backend && .venv/bin/python seed.py && .venv/bin/uvicorn app.main:app --port 8010
# 另开一个终端
curl -X POST localhost:8010/api/hotlist/crawl -H "Authorization: Bearer <token>"
```

- [ ] 11 个源全部入库，`hot_items` 有数据，`hot_rank_history` 每条一行
- [ ] 故意把某个源的 `expected_domain` 改成 `evil.com` → 该源整批丢弃 + `last_status=failed`，
      其他源不受影响
- [ ] 连抓两次 → `crawl_count` 增长、`ranks_json` 累积、掉出榜的条目有 `rank=0` 记录
- [ ] 前端榜单页按源分组显示，手动刷新按钮 10 分钟内二次点击返回 429
- [ ] `pnpm --filter @vben/web-antd run typecheck` 零错误

---

## 三、Phase 2 · 技术源迁回

从 `_to_delete/backend/ai_trending/services/sources/` 里取旧实现改写（或 `git show main:...`）：

| 新文件 | 来源 | 改写要点 |
|---|---|---|
| `adapters/hackernews.py` | `sources/hn.py` (88行) | 删 `hn_heat` 调用；按 frontpage 顺序填 `rank`；`points` 进 `metrics` |
| `adapters/github.py` | `sources/github.py` (148行) | 同上；`stars_today` 进 `metrics` |
| `adapters/huggingface.py` | `sources/hf.py` (148行) | models + papers 两个 params 分支；`trendingScore` 进 `metrics` |
| `adapters/arxiv.py` | `sources/arxiv.py` (101行) | 按发布时间倒序填 `rank`；`published_at` 必填 |
| `adapters/rss.py` | `sources/infoq.py` + `kr36.py` **合并** | feed 地址走 `adapter_params["url"]`，不再一个源一个类 |

**删掉不要带过来的**：`hn_heat` / `github_heat` / `paper_heat` / `hf_models_heat` 四个热度函数、
`MAX_REF` 常量、`filter_ai_keywords` 和 `AI_KEYWORDS`（由 Phase 3 的频率词规则取代，能力严格更强）。

seed 6 行技术源，`source_kind="tech"`，`decay_half_life_hours`：
arXiv/RSS = 24，HN/GitHub/HF = 48。

**验收**：技术源抓到的条目数和标题，与切回 `main` 分支跑旧模块的结果对得上。

---

## 四、Phase 3 · 频率词规则（核心价值）

### 4.1 新增 model

`models/hot_keyword_rule.py` — `HotKeywordRule`：

```python
rule_type       # group / global_filter
display_name    # 组别名（对应原 topic 的名字）
normal_words    # JSON: 普通词（组内 OR）
required_words  # JSON: 必须词（AND）
exclude_words   # JSON: 排除词
source_ids      # JSON: 限定源；[] = 全部
max_count       # 每组最多显示条数，0 = 不限
enabled / sort_order
# 推送配置（字段设计直接对齐 XhsTrackingTask，语义完全对得上）：
notify_enabled / notify_channel_ids / notify_time_start / notify_time_end
notify_frequency / notify_only_on_hit / notify_pending_hits / notify_pending_since
```

每个词存成 `{"word": "京东", "is_regex": false, "display_name": null}`
——正是 `frequency.py::_parse_word` 的产物结构。

`models/hot_rule_hit.py` — `HotRuleHit`：`rule_id` / `item_id` / `matched_at` / `notified`，
`UniqueConstraint("rule_id", "item_id")` 保证同一条目对同一规则只推一次。

### 4.2 `services/keyword_rules.py` ← 移植 TrendRadar `core/frequency.py`

**逐行照搬三个纯函数**（它们是这次移植最该写单测的部分）：
`_parse_word` / `_word_matches` / `matches_word_groups`。

改写两个入口：

```python
def load_rules(db) -> tuple[list[dict], list[dict], list[str]]:
    """返回 (word_groups, filter_words, global_filters)。
    **保持与原 load_frequency_words() 同签名** —— 这样下游匹配/统计逻辑一行不用改。"""

def parse_frequency_text(text: str) -> tuple[list[dict], list[dict], list[str]]:
    """保留原文本 DSL 解析（空行分组、[GLOBAL_FILTER] 区段、+/!/@ 前缀、/正则/、=> 别名），
    供 POST /rules/import 一次性导入 TrendRadar 格式的配置。"""
```

### 4.3 controllers/rules.py

- `GET/POST/PUT/DELETE /api/hotlist/rules` — CRUD
- `POST /api/hotlist/rules/import` — 粘贴 TrendRadar 文本批量导入
- `POST /api/hotlist/rules/preview` — **试跑**：拿当天已抓数据跑一遍匹配，
  返回命中条数 + 前 N 条样例。这是 Web 后台相对配置文件最大的优势，别省。

### 4.4 坑

**正则来自用户输入**，保存时必须 `re.compile` 校验并返回 400。
原实现是 `except re.error → print warning → 降级成子串匹配`，
CLI 里可以，Web 端**不该静默降级**（用户以为正则生效了，其实在做子串匹配）。
另外加模式长度上限（建议 200 字符）防灾难性回溯。

### 4.5 接进抓取流程

`crawl_service` 在 `upsert_items` 之后加一步 `match_rules_and_record_hits`，
新命中写 `HotRuleHit`。前端榜单页加「只看命中」筛选 + 标题上高亮命中词组。

**验收**：普通词 OR、`+`必须词 AND、`!`排除词、`@N`限量、`/正则/`、`=>`别名、
`[GLOBAL_FILTER]` 全局过滤，七种语法逐个验证；保存前试跑能看到命中样例。

---

## 五、Phase 4 · 摘要 + 推送

### 5.1 `services/diff_service.py` ← TrendRadar `core/data.py`

新增检测的判据（原文档强调过，这里再写一遍因为容易写错）：

> 一个标题只要其 `first_crawl_time < 最新批次时间`，就算历史标题。
> 即使同标题有多条记录（URL 不同），只要任一条是历史的，整个标题就不算新增。

原实现拉全天数据进内存做集合差，改成一条 SQL：

```sql
SELECT * FROM hot_items
WHERE stat_date = :today AND last_crawl_time = :latest
  AND title NOT IN (SELECT title FROM hot_items
                    WHERE stat_date = :today AND first_crawl_time < :latest)
```

边界：当天第一次抓取（没有任何历史批次）时，最新批次全部算新增。

### 5.2 `services/digest_service.py`

三种模式：`daily`（当日全部）/ `incremental`（只看新增）/ `current`（当前榜单，
即 `last_crawl_time == 最新批次时间`，但统计信息取全历史）。

**不要照抄 `analyzer.py::count_word_frequency`**（400 行、17 个参数，
是 CLI 里为避免全局状态一路传参的产物）。拆四个纯函数：

```python
select_scope(db, mode, stat_date, source_ids) -> list[HotItem]
match_groups(items, rules)                    -> dict[rule_id, list[HotItem]]
rank_within_group(items, weight_config)       -> list[HotItem]     # 排序 + max_count
build_digest(grouped)                         -> DigestOut
```

### 5.3 推送（**保留旧逻辑**）

- `models/hot_push_config.py` / `hot_push_log.py` — 字段沿用旧
  `ai_trending/models/push_config.py` + `push_log.py`
- `services/push_service.py` — 编排（读配置 → 取时间窗内条目 → 渲染 → 发送 → 记录）
  照搬旧 `push_service.py`，两处改：
  1. 数据源 `AiTrendingItem` → `HotItem` + `HotRuleHit`
  2. 发送改走 `notify_service.send_task_hits_to_channels(db, channel_ids, title, content)`
- **删掉 `push_webhook.py`**（283 行自建 webhook 发送）——工作台已有企微 / Server酱多通道 + 发送记录
- 定时推送 job 的幂等注册写法（`enabled + 非空校验 → add_job / unregister`）原样保留

### 5.4 权重系数进系统设置

`ApiConfig` 三个 key：`hotlist_rank_weight` / `hotlist_frequency_weight` /
`hotlist_hotness_weight`，默认 0.6 / 0.3 / 0.1，在「系统设置」页可调。

---

## 六、贯穿全程的注意事项

1. **loguru 不要 print**。TrendRadar 是 CLI，全程 print，移植时全换掉。
2. **移植文件头注明来源**：
   ```python
   """频率词 DSL 解析与匹配。

   移植自 TrendRadar (https://github.com/sansan0/TrendRadar) core/frequency.py，
   改动：配置输入从文本文件换成数据库行；解析产物结构与匹配逻辑保持一致。
   """
   ```
3. **纯函数先写单测**。`backend/tests/` 目前只有通知模块的测试，这次至少补：
   `test_hotlist_keyword_rules.py`（DSL 解析 + 匹配）、`test_hotlist_ranking.py`（权重公式）、
   `test_hotlist_url.py`（归一化，尤其是微博 `band_rank` 那条）。这三块都是无 IO 纯函数，
   成本低、回归价值高。
4. **`ranks_json` 别无限增长**，保留最近 50 个。权重公式只看最近的榜位分布就够。
5. **SQLite 参数上限 999**，`url NOT IN (...)` 的写法在源返回条目多时会炸，注意分批或临时表。
6. **公共 NewsNow 实例不保证可用**，`expected_domain` 必开，失败要如实记进源状态，
   前端 Tab 挂警示角标（这个交互旧模块已经有，照做）。

---

## 七、提交建议

一个 Phase 一个 commit，信息沿用仓库现有风格（`feat:` / `refactor:` / `fix:` + 中文说明）：

```
refactor: 下线 ai_trending，公共 URL/文本工具提取到 app/common/utils
feat: 热点聚合模块骨架 + NewsNow 中文热榜接入（app/hotlist）
feat: 技术源（HN/GitHub/arXiv/HF/RSS）按 adapter 架构迁回 hotlist
feat: 频率词规则引擎（词组/必须词/排除词/正则/限量/全局过滤）+ 可视化编辑
feat: 热点摘要三模式 + 规则命中定时推送
```

---

## 附：许可与合规

移植代码来自 [TrendRadar](https://github.com/sansan0/TrendRadar)，仓库自带 LICENSE，
每个移植文件头部注明来源即可。NewsNow 公共实例是第三方服务，生产建议自建
（`api_url` 已做成可配置）。本模块与工作台其余部分一样仅供个人学习研究，见 `DISCLAIMER.md`。

---

## 附录 A · GitHub 源怎么配（含「最近一周热门」）

### A.1 先分清三种「最近一周」

这三个问题**答案完全不同**，配源之前先想清楚要哪个：

| 想要的 | 数据通道 | 语义 |
|---|---|---|
| **本周涨星最多的项目**（多数人说的「一周热点」） | `https://github.com/trending?since=weekly` | 老项目也会上榜，看的是**这一周新增的 star** |
| **本周新建且最火的项目** | Search API `q=created:>YYYY-MM-DD&sort=stars` | 只有**新仓库**，`awesome-xxx` 类新库容易霸榜 |
| **本周有活跃更新的热门项目** | Search API `q=pushed:>YYYY-MM-DD&sort=stars` | 老牌大项目会占满，参考价值低 |

一般要的是第一个。第二个作为 trending HTML 抓失败时的兜底（旧实现就是这么降级的），
但要清楚**它不是同一件事**——降级后榜单内容会明显变样，前端最好给个提示。

### A.2 源配置（seed / 前端新增一行）

GitHub adapter 用 `since` 参数区分日榜/周榜/月榜，一个 adapter 喂多行源：

| 字段 | 日榜 | 周榜 | 周榜（限 Python） |
|---|---|---|---|
| `id` | `github-daily` | `github-weekly` | `github-weekly-python` |
| `name` | GitHub 日榜 | GitHub 周榜 | GitHub 周榜 · Python |
| `source_kind` | `tech` | `tech` | `tech` |
| `adapter` | `github` | `github` | `github` |
| `adapter_params` | `{"since":"daily"}` | `{"since":"weekly"}` | `{"since":"weekly","language":"python"}` |
| `expected_domain` | `github.com` | `github.com` | `github.com` |
| `decay_half_life_hours` | `48` | `0` | `0` |
| `cron_expr` | `0 2,14 * * *` | `0 6 * * *` | `0 6 * * *` |

两个参数说明：

- **`decay_half_life_hours` 周榜设 0**。周榜本身就是「过去 7 天」的聚合结果，
  再叠一层时间衰减等于把同一个时间因素算两遍，排序会被抓取时刻带偏。日榜设 48 是因为
  日榜条目会连续几天在榜，需要让老条目自然退位。
- **`cron_expr` 周榜每天一次就够**。周榜数据变化慢，抓太勤只是重复写 `rank_history`，
  白白增加被 GitHub 限流的概率。

### A.3 `adapters/github.py` 实现规格

在 Phase 2 改写旧 `sources/github.py`（`_to_delete/backend/ai_trending/services/sources/github.py`
或 `git show main:backend/app/ai_trending/services/sources/github.py`）。旧实现的骨架是对的
（HTML 主通道 + Search API 兜底 + lxml 解析），改四处：

```python
class GitHubAdapter(HotSourceAdapter):
    adapter_key = "github"
    TRENDING_URL = "https://github.com/trending"
    SEARCH_API = "https://api.github.com/search/repositories"

    def fetch(self, params: dict) -> list[RawEntry]:
        since = params.get("since", "daily")          # daily / weekly / monthly
        language = params.get("language", "")
        try:
            return self._fetch_html(since, language)
        except HotSourceAdapterError:
            logger.warning(f"github trending({since}) HTML 抓取失败，降级 Search API")
            return self._fetch_search_api(since, language)
```

改动点：

1. **`since` / `language` 进 URL**：`f"{TRENDING_URL}?since={since}"`，
   有 language 再拼 `&language={quote(language)}`（注意 `c++` 要 URL 编码）。
2. **star 文案的正则要跟着 `since` 变**。旧代码写死 `stars today`，周榜页面上是
   `stars this week`、月榜是 `stars this month`，写死了周榜的 star 数会全部解析成 0：
   ```python
   _STARS_RE = re.compile(r"([\d,]+)\s*stars?\s*(?:today|this week|this month)", re.I)
   ```
3. **填 `rank`**：`for idx, article in enumerate(articles, 1)`，
   页面顺序就是榜位。删掉 `github_heat(...)` 调用，打分交给 `ranking.py`。
4. **`metrics`**：`{"stars_today": n, "since": since}`（周榜时这个 n 其实是本周新增，
   key 建议改成中性的 `stars_delta`，另存 `since` 说明口径，免得前端展示时说错）。

兜底通道按 `since` 换天数：

```python
days = {"daily": 1, "weekly": 7, "monthly": 30}.get(since, 7)
since_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
url = f"{SEARCH_API}?q=created:>{since_date}&sort=stars&order=desc&per_page=30"
```

### A.4 两个运维坑（实测确认）

1. **GitHub trending 页会对机房 IP 返回 403**。从云端容器直接请求 `github.com/trending`
   实测拿到 403（浏览器 UA 也一样）；家用/办公网络正常。这意味着：
   - 本地开发能抓通，**部署到云服务器后可能整源失败**
   - `_fetch_html` 里要把 403 单独识别出来，`last_error` 写明「疑似 IP 被限」，
     而不是笼统的「请求失败」，否则排查时会一直怀疑解析逻辑
   - 兜底的 Search API 走 `api.github.com`，机房 IP 可用，所以降级链路是有意义的

2. **Search API 匿名限额 10 次/分**（认证后 30 次/分）。周榜每天抓一次远够用，
   但如果 Phase 3 的规则试跑也走 Search API 要注意。想提额就在
   `ApiConfig` 加一个 `hotlist_github_token`，请求带 `Authorization: Bearer <token>`
   （只读 public repo，用细粒度 token 且不给任何 scope 即可）。

### A.5 前端怎么看「最近一周热门」

配好 `github-weekly` 源后，榜单页：**技术源 Tab → 选 GitHub 周榜 → 按 `weight` 排序**。

想直接查接口：

```bash
# 周榜当前排名前 20
curl -H "Authorization: Bearer <token>" \
  "localhost:8010/api/hotlist/items?source_id=github-weekly&sort=rank&page_size=20"

# 看某个项目这一周的榜位变化（含掉榜）
curl -H "Authorization: Bearer <token>" "localhost:8010/api/hotlist/items/123"
```

连抓几天之后，`crawl_count`（在榜天数）和 `ranks_json`（榜位序列）就有内容了，
`weight` 会自然把「连续多天高位」的项目顶上去——这正好是周榜单看一眼看不出来的信息。

配合 Phase 3 的频率词规则还能做定向订阅，例如新建一条规则：

```
[Agent 框架]
+/agent|框架/
LLM
RAG
!course
!tutorial
@5
```

含义：必须命中 `agent` 或 `框架`（正则），且命中 `LLM` / `RAG` 任一，
排除教程类，每次最多推 5 条。绑定 `source_ids=["github-weekly"]` + 企微通道，
就是一个「本周 Agent 相关新项目」的周报。

---

## 附录 B · `stat_date` 语义修正（**Phase 1 实现前必读**）

设计文档里 `stat_date` 是照 TrendRadar 的「按天分域」搬来的，但 TrendRadar 是
**一天一个 SQLite 文件**、每天重新插入；本项目的唯一键是全局的 `(source_id, url)`，
一条记录**跨天只有一行**。于是：

> `stat_date` 的真实语义是「**首次发现日期**」，不是「所属日期」。

直接影响：GitHub 周榜里一个上周就上榜的项目，`stat_date` 停在上周，
用 `WHERE stat_date = today` 查「今日榜单」会**查不到它**——而它明明还在榜上。
中文热榜因为话题生命周期短，这个坑不容易暴露；周榜/月榜类源必然踩到。

**修正**（Phase 1 写 `crawl_service` / `digest_service` 时就按这个来）：

1. `stat_date` 字段保留，改注释为「首次发现日期」，只用于数据清理和「新增了多少」统计；
2. **所有「当日/当前」的范围查询一律用 `last_crawl_time`**，不要用 `stat_date`：
   ```sql
   -- 今日在榜（对）
   WHERE last_crawl_time >= :today_start
   -- 今日在榜（错，会漏掉跨天仍在榜的条目）
   WHERE stat_date = :today
   ```
3. 第五节 `diff_service` 的新增检测 SQL 同步改：把两处 `stat_date = :today`
   换成 `last_crawl_time >= :today_start` / `first_crawl_time >= :today_start`；
4. 清理任务按 `last_crawl_time` 判断过期（多久没再上榜），而不是按 `stat_date`——
   否则一个持续在榜三周的项目会被当成「三周前的旧数据」删掉。
