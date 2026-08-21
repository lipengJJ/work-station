# 热点聚合模块重构任务书（交付给 DeepSeek 执行）

> 项目：`/Users/lipeng01/vscode/workbench`，模块 `backend/app/hotlist` + `frontend/apps/web-antd/src/views/hotlist`
> 技术栈：FastAPI + SQLAlchemy 2.0 + SQLite（**无 Alembic**）/ Vue3 + Ant Design Vue（Vben Admin）
> 本次范围：两项重构 + 一项功能补齐。**不改抓取内核**（adapters / crawl_service 的抓取与去重逻辑）。

---

## 一、现状（已核实，勿凭猜测）

### 1.1 已有的表与职责

| 表 | 文件 | 现状 |
|---|---|---|
| `hot_sources` | `models/hot_source.py` | 源字典 + 健康状态。有 `source_kind`（hotlist/tech）但**没有分组** |
| `hot_topics` | `models/hot_topic.py` | 主题：源绑定、Skill、digest 策略、发布、**报告推送配置** |
| `hot_topic_sources` | `models/hot_topic_source.py` | 主题↔源 多对多，`enabled` 记在关联上 |
| `hot_keyword_rules` | `models/hot_keyword_rule.py` | **全局规则**，有自己的 `source_ids` 和一整套 `notify_*`（实时命中推送） |
| `hot_rule_hits` | — | 规则命中记录 |
| `hot_topic_reports` | `models/hot_topic_report.py` | 报告 |

### 1.2 当前的两条链路是**断开的**（本次要解决的核心问题）

```
链路 A（命中推送）：crawl_service.match_rules_and_record_hits()
    → keyword_rules.load_rules(db, source_id)   ← 读全部启用规则，与主题无关
    → 写 HotRuleHit
    → push_service.notify_rule_hits(rule_id)     ← 按【规则】推送

链路 B（报告生成）：topic_report_service.fetch_candidates()
    → 只按 _topic_source_ids() 取数              ← ★ 完全没有用关键词规则
    → 全部条目进 L0
```

**后果**：用户在「规则」页配的关键词对周报毫无影响；主题只能按源筛，配了
`+trading, quant, backtest` 也不会让报告只分析量化相关的内容。

### 1.3 前端现状

- 路由 `router/routes/modules/hotlist.ts`：榜单 / 摘要 / **规则** / 源管理 / 主题订阅 / 主题详情 / 报告
- `views/hotlist/rules/index.vue`：全局过滤词 + 词组规则卡片列表（独立顶层菜单）
- `views/hotlist/sources/index.vue`：平铺表格，无分组
- `views/hotlist/topics/detail.vue`：主题详情

---

## 二、重构目标

### 目标 A：规则并入主题（一个主题 = 一次完整配置）

用户心智应当是：**建一个主题 → 勾数据源 → 配关键词 → 选 Skill → 开推送 → 完事**。
配完之后该主题自动扫描它的源、按它的关键词匹配、用它的 Skill 生成日报/周报、按它的渠道推送。

「规则」不再是顶层菜单，而是主题详情里的一个 Tab。

### 目标 B：源管理分组 + 批量导入

源按用户自定义分组（股票类 / 游戏类 / AI 类…）折叠展示、批量开关、批量导入。

---

## 三、后端改动

### 3.1 `models/hot_keyword_rule.py` — 规则归属主题

**新增字段**

```python
topic_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
"""所属主题。NULL 表示全局规则：
   - rule_type='global_filter' 时恒为 NULL（全局过滤词对所有主题生效）
   - rule_type='group' 且 topic_id 为 NULL 的是历史遗留数据，迁移脚本会收编（见 §5）
"""
```

**删除字段**（保留列不读，见 §5 迁移说明；代码里必须彻底不再引用）

- `source_ids` —— 源范围由主题的 `hot_topic_sources` 决定。规则再存一份是冗余，
  且两者不一致时行为不可预期。**删掉，不要试图"取交集"兼容**。
- `notify_enabled` / `notify_channel_ids` / `notify_time_start` / `notify_time_end` /
  `notify_frequency` / `notify_only_on_hit` / `notify_pending_hits` / `notify_pending_since`
  —— 全部迁到 `hot_topics`（见 3.2）。

### 3.2 `models/hot_topic.py` — 并存两组推送配置

⚠️ **这是最容易做错的地方**：现在系统里有**两种语义完全不同的推送**，合并会丢功能。

| | 触发时机 | 内容 | 原位置 |
|---|---|---|---|
| **实时命中推送** | 抓取时命中关键词，立即或按频率汇总 | 命中的条目列表 | `hot_keyword_rules.notify_*` |
| **报告定时推送** | 报告生成完成后 | 报告摘要 + 链接 | `hot_topics.notify_*` |

**改法**：把主题上现有的 `notify_*` 四个字段**改名**为 `report_notify_*`（消除歧义），
再新增一组 `hit_notify_*`：

```python
# ---- 报告推送（原 notify_*，改名）----
report_notify_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
report_notify_channel_ids: Mapped[str] = mapped_column(Text, default="[]")
report_notify_time_start: Mapped[str | None] = mapped_column(String(8), nullable=True)
report_notify_time_end: Mapped[str | None] = mapped_column(String(8), nullable=True)

# ---- 实时命中推送（原 hot_keyword_rules.notify_*，迁移过来）----
hit_notify_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
hit_notify_channel_ids: Mapped[str] = mapped_column(Text, default="[]")
hit_notify_time_start: Mapped[str | None] = mapped_column(String(8), nullable=True)
hit_notify_time_end: Mapped[str | None] = mapped_column(String(8), nullable=True)
hit_notify_frequency: Mapped[str] = mapped_column(String(16), default="realtime")
"""realtime / 1h / 6h / 12h / daily"""
hit_notify_only_on_hit: Mapped[bool] = mapped_column(Boolean, default=True)
hit_notify_pending_hits: Mapped[int] = mapped_column(Integer, default=0)
hit_notify_pending_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

### 3.3 `services/keyword_rules.py` — 按主题加载

```python
def load_rules(
    db: Session,
    topic_id: int | None = None,
    source_id: str | None = None,
) -> tuple[list[dict], list[Any], list[str]]:
    """返回 (word_groups, filter_words, global_filters)，签名与返回结构保持不变
    （下游 matches_word_groups / match_groups 一行不用改）。

    改动：
      - topic_id 给定  → 只加载该主题的 group 规则 + 全部 global_filter
      - topic_id 为 None → 加载全部启用的 group 规则（榜单页"只看命中"等全局场景）
      - source_id 参数**删除**：源范围已由主题决定，规则不再有 source_ids
    """
```

`parse_frequency_text` / `_parse_word` / `_word_matches` / `matches_word_groups` /
`match_groups` **保持不变**。

### 3.4 `services/crawl_service.py` — 命中按主题聚合

`match_rules_and_record_hits()` 改造：

```python
def match_rules_and_record_hits(db, source_id, touched) -> set[int]:
    """返回值从 set[rule_id] 改为 set[topic_id]。

    新逻辑：
      1. 查出「引用了 source_id 且 enabled 的主题」（走 hot_topic_sources）
      2. 对每个主题，load_rules(db, topic_id=topic.id) 取它自己的规则
      3. 主题没有 group 规则时 → 视为「不过滤，全部命中」（保持"只勾源不配词"可用）
      4. 命中写 HotRuleHit（结构不变，仍记 rule_id；rule_id 为空时记 0 表示"无规则命中"）
      5. 返回本批次有新命中的 topic_id 集合
    """
```

调用处（`crawl_service` 第 126~127 行附近）：

```python
# 旧：for rule_id in newly_hit_rule_ids: push_service.notify_rule_hits(db, rule_id)
for topic_id in newly_hit_topic_ids:
    push_service.notify_topic_hits(db, topic_id)
```

> **为什么按主题而不是按规则聚合**：一个主题配 3 条词组规则时，按规则推会连发 3 条消息。
> 按主题聚合成一条，内容里再按规则分节。

### 3.5 `services/push_service.py`

- `notify_rule_hits(db, rule_id)` → **改名** `notify_topic_hits(db, topic_id)`
- 读配置从 `HotKeywordRule.notify_*` 改为 `HotTopic.hit_notify_*`
- 暂存计数 `hit_notify_pending_hits` / `hit_notify_pending_since` 记在主题上
- 消息标题带主题名：`【量化平台】新增 5 条命中`

### 3.6 `services/topic_report_service.py` — ★ 打通规则与报告（核心功能补齐）

`fetch_candidates()` 当前只按 `source_ids` 过滤，必须加上关键词过滤：

```python
def fetch_candidates(db, topic, period_start, period_end) -> list[HotItem]:
    source_ids = _topic_source_ids(db, topic)
    if not source_ids:
        return []
    q = (db.query(HotItem)
           .filter(HotItem.source_id.in_(source_ids),
                   HotItem.last_crawl_time >= period_start,
                   HotItem.last_crawl_time < period_end))
    items = q.order_by(HotItem.weight.desc()).limit(topic.max_items * 3).all()

    # ★ 新增：按主题自己的关键词规则过滤
    word_groups, filter_words, global_filters = keyword_rules.load_rules(db, topic_id=topic.id)
    if word_groups:      # 没配规则 = 不过滤，保持"只勾源也能出报告"
        items = [
            it for it in items
            if keyword_rules.matches_word_groups(
                f"{it.title} {it.summary or ''}", word_groups, filter_words, global_filters)
        ]
    return items[: topic.max_items]
```

三点注意：

1. **先按 weight 多取 3 倍再过滤**，否则命中率低的主题会因为先截断而拿不满 `max_items`。
2. **匹配文本用 `title + summary`**，与 `crawl_service` 里的匹配口径保持一致，
   避免"榜单页显示命中、报告里却没有"这种不一致。
3. **`word_groups` 为空时不过滤**——用户可能只想按源订阅，不配任何关键词。

同时 `generate_report()` 里 `notify_report()` 的配置读取改为 `topic.report_notify_*`。

### 3.7 新增 `models/hot_source_group.py` — 源分组

```python
class HotSourceGroup(Base):
    """源分组：纯粹的组织方式，方便管理和批量操作。

    ⚠️ 与「主题」是两个正交维度，不要混淆：
      - 分组：一个源属于一个分组（1:N），回答「这个源是干什么的」
      - 主题：一个源可被多个主题引用（N:N，走 hot_topic_sources），回答「我要订阅什么」
    唯一的交互点：主题选源时可以「按分组批量勾选」。
    分组不参与抓取调度，不影响任何匹配逻辑。
    """
    __tablename__ = "hot_source_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)   # 「股票财经」
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(16), default="")   # 前端标签色，可空
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)  # 内置分组不允许删除
    created_at / updated_at
```

`HotSource` 新增：

```python
group_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
"""所属分组。NULL = 未分组，前端归入「未分组」区。"""
```

**内置分组 seed**（幂等，`source_service.seed_default_groups()`，在 `main.py` lifespan 里
现有的 `seed_default_sources()` **之前**调用）：

| name | 说明 | 迁移时归入 |
|---|---|---|
| 中文热榜 | NewsNow 平台 | 现有 `source_kind='hotlist'` 的源 |
| 技术社区 | HN / GitHub / arXiv / HF | 现有 `source_kind='tech'` 的源 |

> `source_kind` 字段**保留不动**（`ranking.py` 的衰减逻辑和前端 Tab 还在用），
> 分组是另加的一层，不要用 group_id 去替换 source_kind。

### 3.8 `services/source_service.py` 新增

```python
def seed_default_groups(db) -> None: ...
def list_groups(db) -> list[HotSourceGroup]: ...
def create_group(db, data) -> HotSourceGroup: ...
def update_group(db, group_id, data) -> HotSourceGroup: ...
def delete_group(db, group_id) -> None:
    """内置分组拒删（400）。删除时组内源的 group_id 置 NULL，不级联删源。"""
def batch_move_sources(db, source_ids: list[str], group_id: int | None) -> int: ...
def batch_set_enabled(db, source_ids: list[str], enabled: bool) -> int: ...
```

### 3.9 `services/opml_service.py` — 批量导入到分组

现有导入是「导入到主题」。改成两个可选归属，互不依赖：

```python
def import_opml(
    db,
    content: str,
    group_id: int | None = None,   # 新增：导入的源归入哪个分组
    topic_id: int | None = None,   # 原有：同时关联到哪个主题（可空）
    imported_from: str = "",
) -> ImportResult:
    """
    - 解析 OPML → normalize_url 去重 → 已存在则复用（不覆盖用户改过的 name/cron）
    - 新建的源写入 group_id
    - topic_id 给定时额外建 HotTopicSource(enabled=False)
    - 返回 {created, reused, skipped, source_ids}
    """
```

于是「源管理」页可以纯粹地批量导入一批源到某个分组，不必先建主题。

### 3.10 Controller 改动

**`controllers/rules.py`** — 路由收敛到主题下：

| 旧 | 新 |
|---|---|
| `GET /api/hotlist/rules` | `GET /api/hotlist/topics/{topic_id}/rules` |
| `POST /api/hotlist/rules` | `POST /api/hotlist/topics/{topic_id}/rules` |
| `PUT /api/hotlist/rules/{rule_id}` | 保持（rule_id 已唯一） |
| `DELETE /api/hotlist/rules/{rule_id}` | 保持 |
| `POST /api/hotlist/rules/import` | `POST /api/hotlist/topics/{topic_id}/rules/import` |
| `POST /api/hotlist/rules/preview` | `POST /api/hotlist/topics/{topic_id}/rules/preview`（预览时只用该主题的源 + 规则） |
| `POST /api/hotlist/rules/global-filters` | 保持全局：`/api/hotlist/global-filters`（GET/POST/DELETE） |

**`controllers/sources.py`** 新增：

```
GET    /api/hotlist/source-groups
POST   /api/hotlist/source-groups
PUT    /api/hotlist/source-groups/{group_id}
DELETE /api/hotlist/source-groups/{group_id}
POST   /api/hotlist/sources/batch          # {source_ids, group_id?, enabled?}
POST   /api/hotlist/sources/import-opml    # {content|url, group_id?}
GET    /api/hotlist/sources?group_id=      # 列表支持按分组筛
```

---

## 四、前端改动

### 4.1 删除「规则」顶层菜单

- 删 `views/hotlist/rules/index.vue`
- `router/routes/modules/hotlist.ts` 删掉 `HotlistRules` 路由项
- **全局过滤词**（广告 / 软广）从规则页移出，放到**「主题订阅」列表页顶部一个可折叠区块**
  ——它对所有主题生效，放主题详情里会让人误以为是主题级配置。

### 4.2 `views/hotlist/topics/components/TopicDetailPanel.vue` — Tab 配置面板，内嵌不跳路由

主题详情**不是独立路由页面**。`topics/index.vue`（主题订阅列表）点击卡片，用
Ant Design Vue 的 `Drawer` 在同一个页面里展开这个组件，传 `topic-id` 进去；
关掉抽屉就回到列表，浏览器地址栏全程停在 `/hotlist/topics`。

| Tab | 内容 |
|---|---|
| 数据源 | 现有源勾选列表，**新增按分组折叠 + 「全选本组」** |
| 关键词规则 | 原 `rules/index.vue` 的词组卡片，作用域为本主题；含导入、试跑预览 |
| 分析配置 | Skill 选择、template、extra_question、digest_strategy、周期与 cron、max_items / shortlist_size / fulltext_size |
| 推送设置 | **两块分开**：① 实时命中推送（`hit_notify_*`，含频率）② 报告推送（`report_notify_*`）|
| 报告历史 | 现有报告列表；点进具体某期报告仍是单独路由 `topics/:id/reports/:reportId`（内容长、需要完整页面阅读，不适合塞进抽屉） |

> 曾经把这个做成独立路由 `topics/:id` + `detail.vue`。后来发现列表页「点卡片进详情」
> 和详情页本身概念上就是一件事，没必要多一次路由跳转——改成 Drawer 内嵌后，
> `detail.vue` 整个删除，路由表里的 `HotlistTopicDetail` 项也删除。

### 4.3 新建主题

不做独立页面 / 分步向导。「主题订阅」列表页右上角「新建主题」按钮弹出一个
最小表单弹窗（名称 / slug / 描述），提交后直接创建主题，并立即用同一个 Drawer
展开 §4.2 的配置面板——数据源、关键词规则、Skill / 周期、推送设置都在这一个面板里配，
不重复实现一套，也不需要额外跳转。

> 之前设计过一个 5 步向导页（`topics/create.vue`），把数据源勾选 / 关键词 / Skill
> 周期 / 推送设置在向导里又实现了一遍，与详情面板完全重复，且分步提交是
> 4 个串行 API 调用，部分失败会留下"半配置"的主题——违背了目标 A"一个主题 = 一次
> 完整配置"。**不要重建这个向导页**，创建流程到此为止即可。

### 4.4 `views/hotlist/sources/index.vue` — 分组化

- 顶部：分组 Tab 或左侧分组树（含「全部」「未分组」）
- 表格支持多选 → 批量操作条：`移动到分组` / `批量启用` / `批量停用` / `批量删除`
- 右上角按钮组：`+ 新建 RSS 源` / `批量导入 OPML`（选文件或填 URL + 选目标分组） / `分组管理`
- 分组管理弹窗：增删改名、排序、颜色

### 4.5 `api/core/hotlist.ts`

按 §3.10 的路由调整同步；新增 `SourceGroup` 类型与分组相关方法。

---

## 五、数据迁移（**必须做，项目无 Alembic**）

在 `backend/app/core/database.py` 里**沿用已有写法**新增一个幂等函数
（参考同文件的 `_ensure_tracking_ai_schema()`），在 `init_db()` 末尾调用：

```python
def _ensure_hotlist_topic_rule_schema() -> None:
    """hotlist 规则归属主题 + 源分组 + 推送配置拆分（幂等，老库兼容）。"""
```

执行内容：

1. **加列**（`ALTER TABLE ADD COLUMN`，已存在则跳过）
   - `hot_keyword_rules.topic_id INTEGER`
   - `hot_sources.group_id INTEGER`
   - `hot_topics` 加 `report_notify_*` 4 列 + `hit_notify_*` 8 列

2. **搬数据**
   ```sql
   -- 报告推送：老 notify_* → report_notify_*
   UPDATE hot_topics SET
     report_notify_enabled     = notify_enabled,
     report_notify_channel_ids = notify_channel_ids,
     report_notify_time_start  = notify_time_start,
     report_notify_time_end    = notify_time_end
   WHERE report_notify_channel_ids IS NULL OR report_notify_channel_ids = '';
   ```

3. **收编无主规则**：把 `rule_type='group' AND topic_id IS NULL` 的规则收进一个
   自动创建的主题「默认主题」（`slug='default'`，`enabled=True`，
   源 = 当前所有启用源，`skill_key=''`）。
   - 若这些规则原先带 `notify_enabled=1`，把第一条的 `notify_*` 搬到该主题的 `hit_notify_*`
   - 迁移完 `logger.warning` 打印收编了几条，提示用户去调整

4. **给存量源归入内置分组**
   ```sql
   UPDATE hot_sources SET group_id = (SELECT id FROM hot_source_groups WHERE name='中文热榜')
   WHERE group_id IS NULL AND source_kind='hotlist';
   UPDATE hot_sources SET group_id = (SELECT id FROM hot_source_groups WHERE name='技术社区')
   WHERE group_id IS NULL AND source_kind='tech';
   ```

**关于删列**：默认策略是"保留在库里但代码彻底不再读写"——`hot_keyword_rules` 的
`source_ids` 和 8 个 `notify_*` 就是这样处理的，ORM 模型里直接删掉字段定义即可
（SQLAlchemy 不要求模型覆盖所有列），在模型 docstring 里注明这些是废弃列。

⚠️ **例外**：这个默认策略有一个前提——老列必须是 nullable 或者有 DB 端 DEFAULT，
否则模型删掉字段定义后，任何走 ORM 的 INSERT 都不会给这些列赋值，会被 SQLite 的
NOT NULL 约束拒绝（真实踩过：`hot_topics.notify_enabled` / `notify_channel_ids`
建表时是 `NOT NULL` 且没有 DB 端 DEFAULT——ORM 的 `default=False` 只在走 ORM insert
时生效，是 Python 侧默认值，不是 schema 里的约束——迁移把数据搬到 `report_notify_*`
后就成了死列，但 NOT NULL 约束还在，导致新建主题直接 500）。遇到这种列，SQLite
不支持 `ALTER COLUMN`，只能重建表：`CREATE TABLE xxx_new` 建完整目标 schema
（不含要删的列）→ `INSERT INTO xxx_new (...) SELECT (...) FROM xxx` → `DROP TABLE xxx`
→ `RENAME xxx_new TO xxx`。前提是这张表没有被别的表用 `ForeignKey` 引用
（`hot_topic_sources` / `hot_keyword_rules` / `hot_topic_reports` 的 `topic_id` 都是
普通 `Integer` 列，不是 FK，所以 `hot_topics` 重建是安全的）。写法参考
`core/database.py::_ensure_notification_config_schema` 里已经在用的同一套重建套路。

---

## 六、验收标准

- [ ] 侧边栏「热点聚合」下不再有「规则」；主题详情是内嵌 Drawer（5 个 Tab），不是独立路由页
- [ ] 新建一个主题「量化平台」：勾 GitHub 周榜 + 财联社，配 `+trading, quant, backtest, 量化`，
      选一个 Skill，周期 weekly，开启报告推送 → 保存后**不需要再去别的页面配任何东西**
- [ ] 该主题「立即生成」出的报告，**条目全部与关键词相关**（验证 `fetch_candidates` 的规则过滤生效）
- [ ] 另建一个主题只勾源、不配关键词 → 报告仍能正常生成（不过滤分支可用）
- [ ] 同一个源（如 GitHub 周榜）被两个主题引用时，`hot_sources` 里只有一行，抓取只发生一次
- [ ] 一个主题配 3 条词组规则并全部命中 → 实时推送**只收到 1 条消息**（按主题聚合），
      内容里按规则分节
- [ ] 实时命中推送与报告推送可以分别开关、互不影响
- [ ] 源管理页按分组折叠；可新建分组、批量移动源、批量启停
- [ ] 批量导入 OPML 到「股票财经」分组 → 源进入该分组，**不需要先建主题**
- [ ] 用老库（已有主题、规则、源、报告数据）启动 → 迁移自动完成，
      老规则被收进「默认主题」，老源归入内置分组，已有报告可正常打开
- [ ] 全局过滤词在「主题订阅」页顶部，对所有主题生效
- [ ] `pnpm --filter @vben/web-antd run typecheck` 零错误

---

## 七、禁止事项

1. **不要合并两种推送**。`hit_notify_*`（实时命中）和 `report_notify_*`（报告）
   是不同触发时机、不同内容的两件事，合并会丢功能。
2. **不要用 `group_id` 替代 `source_kind`**。后者被 `ranking.py` 的衰减逻辑和前端 Tab 使用。
3. **不要让分组参与抓取调度或匹配逻辑**。分组纯粹是 UI 组织方式。
4. **不要保留 `HotKeywordRule.source_ids`**。源范围唯一真相是 `hot_topic_sources`，
   两处都有会导致行为不可预期。
5. **不要改动 `services/adapters/`、`ranking.py`、`diff_service.py`**，本次不涉及。
6. **不要静默降级用户输入的正则**。规则保存时 `re.compile` 校验失败必须返回 400。
7. **不要写 Alembic 迁移**。项目用的是 `database.py` 里的幂等 DDL 补丁，沿用同一套写法。

---

## 八、建议的提交拆分

```
refactor(hotlist): 源分组模型与批量操作（表 + service + controller + 源管理页）
refactor(hotlist): 关键词规则归属主题，推送配置拆分为命中/报告两组
feat(hotlist): 报告生成接入主题关键词过滤，打通规则与周报链路
refactor(hotlist): 主题详情改 Tab 布局，下线独立规则页
chore(hotlist): 老库幂等迁移（规则收编默认主题 + 存量源归入内置分组）
```
