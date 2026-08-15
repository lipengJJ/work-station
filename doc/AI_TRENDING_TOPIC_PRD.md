# AI 开发热点聚合 — 增量 PRD：全局热榜 → 主题跟踪模式（重构）

> 本文为「AI 开发热点聚合」的**重构增量 PRD**，描述从「全局热榜模式」迁移到「主题跟踪模式」的完整差异。
> 既有全局热榜能力（6 来源 7 通道抓取、`ai_trending_items` 数据底座、来源健康状态）以 `doc/AI_TRENDING_PRD.md`、`doc/AI_TRENDING_ARCHITECTURE.md` 为准保留复用；既有推送底层（`push_webhook.py` Sender 协议 + Mock 实现、`push_service.py` 管线）保留复用，但**入口从全局卡片改为主题级**。
> 本次重构的主要参照：XHS 关键词追踪（`backend/app/xhs/models/xhs_tracking_task.py` / `xhs_tracking_hit.py` / `services/tracking.py` / `controllers/tracking.py` / 前端 `views/xhs/tracking/`）。

| 项目信息 | 内容 |
|---|---|
| Language | 中文 |
| Programming Language | 与既有 ai_trending 模块一致：FastAPI + SQLAlchemy 2.0 + APScheduler（后端）；Vue3 + Vben Admin / web-antd + ant-design-vue（前端）；SQLite |
| Project Name | `ai_trending` 模块内重构增量（新增表 `ai_trending_topic` / `ai_trending_topic_hit`，路由 `/api/ai-trending/topics/*`） |
| 原始需求 | ① 移除 AI 热点页顶部的全局定时推送配置卡片（mock 推送底层保留复用，入口改为主题级）；② AI 热点改为**分主题显示**，类似 XHS 追踪：用户创建「跟踪主题」（含关键词），系统按主题关键词去各来源检索相关新闻（不是全局抓取后过滤），点击主题查看该主题下的热点列表；③ 主题级定时推送：点击主题弹窗/抽屉 → 选择推送方式（下拉：企业微信/钉钉/飞书/邮件，实际发送由其他分支开发，本次只保存选择）+ 推送频率 + 推送时间；④ 推送方式选项为占位，本次保存配置即可（可复用现有 mock Sender 协议）。 |

---

## 1. 产品定义（重构增量）

### 1.1 Product Goals

**一句话**：把「打开就是一张大而全的热榜」重构为「用户按自己的关注领域创建跟踪主题、系统按关键词定向追踪、并按主题订阅推送」，让每个开发者只关心自己关心的 AI 子领域。

**三个衡量指标（重构后）**：
1. **主题时效性**：新创建主题在 30 分钟内完成首次抓取并展示命中结果的比例 ≥ 95%（run-now 即时触发 + 定时兜底）。
2. **主题内容有效性**：主题详情页条目点击可达率（原文 URL 有效）≥ 95%；关键词设置合理时每主题日均新增命中 ≥ 5 条。
3. **推送配置可用性**：主题推送配置（方式/频率/时间/开关）保存后即可回读生效；通道切换占位不阻塞保存（实际发送由其他分支接入）。

### 1.2 User Stories（新增 5 条）

1. 作为**开发者**，我希望创建「跟踪主题」（如「AI Agent」）并配置关键词，以便系统按关键词自动检索各来源、汇聚与该主题相关的热点，而不是在全局大热榜里自己翻找。
2. 作为**开发者**，我希望在主题列表页一眼看到每个主题的运行状态、最近抓取时间、命中总数和推送开启徽标，以便知道哪些主题在正常运转、哪些出了问题。
3. 作为**开发者**，我希望点击某个主题进入详情，看到该主题下的热点新闻列表（可查看摘要、跳转原文），以便聚焦自己关注的 AI 子领域。
4. 作为**开发者**，我希望对某个主题单独配置定时推送（企业微信/钉钉/飞书/邮件 + 频率 + 时间），以便每个团队关注的主题都能按需收到日报，而不是全局只有一份。
5. 作为**开发者**，我希望对任意主题随时手动触发一次抓取（run-now），以便新建主题后立刻看到结果，不用干等定时任务。

---

## 2. 现状 vs 目标对比表

| 维度 | 现状（全局热榜模式） | 目标（主题跟踪模式） | 差异说明 |
|---|---|---|---|
| **数据模型** | `ai_trending_items` 全局单表 + `ai_trending_source_status` 来源状态；无「主题」概念 | **新增** `ai_trending_topic`（主题：name/keywords/interval/enabled/状态/内嵌推送配置）+ `ai_trending_topic_hit`（主题命中关联，仿 XHS hit）；`ai_trending_items` 保留作数据底座 | 从「单表全量」升级为「主题 + 命中关联」两级结构；条目数据不重复存储，主题通过 hit 表引用 items |
| **抓取方式** | 6 来源 7 通道每小时**全局抓取**，入库后按来源/类型筛选，无关键词维度 | **每主题按关键词定向检索**：HN/GitHub/arXiv/HF 走检索接口（`search()`），InfoQ/36氪 仅全量 feed → 关键词过滤；检索结果 upsert 进 items（同 url_hash 去重）+ 记 topic_hit | 从「全局抓取后过滤」变为「按主题关键词主动检索」；全局每小时抓取保留作数据底座（`/sources` 健康状态与「全部热点」视图仍可用） |
| **页面结构** | 单页热榜：来源 Tab + 类型/排序筛选 + 列表卡片 + **顶部全局推送配置卡片** | **主题列表页**（卡片 + 新建/编辑/删除 + 每主题状态/最近抓取/推送徽标）→ 点击进入**主题详情页**（返回 + 该主题热点列表 + 立即抓取 + 推送配置）；**移除全局推送卡片**；「全部热点」作为二级入口保留 | 从「单页热榜」变为「列表-详情两态」（仿 XHS tracking `index.vue` 单页两态结构） |
| **推送配置** | 全局单行配置 `ai_trending_push_config`（id=1），页面顶部卡片，企业微信 webhook + push_time + top_n | **每主题内嵌推送配置**：`push_enabled / push_channel / push_frequency / push_time`，入口在主题详情页弹窗；channel 下拉占位（企业微信/钉钉/飞书/邮件），本次仅保存配置，实际发送由其他分支接入（复用 mock Sender 协议） | 从「全局一份、企微 webhook 可发」变为「每主题一份、多通道占位仅保存」；全局推送卡片 UI 移除 |

---

## 3. 技术规范（重构增量）

### 3.1 需求池

**P0（必做）**
- [ ] 数据模型：`ai_trending_topic`（name / keywords JSON / interval_minutes / enabled / status / last_run_at / last_run_message / last_item_count + 内嵌推送配置字段 push_enabled / push_channel / push_frequency / push_time）与 `ai_trending_topic_hit`（topic_id / item_id / matched / first_seen_at，Unique(topic_id, item_id)），`init_db()` 自动建表
- [ ] 主题 CRUD：`/api/ai-trending/topics` GET/POST/PUT/DELETE + GET /{id}（对齐 `xhs/controllers/tracking.py` 风格）；创建/更新/删除时同步注册/注销定时任务
- [ ] 主题抓取：`TrendingSource` 基类新增可选 `search(keywords)` 方法（默认降级 = `fetch()` + 关键词过滤）；HN / GitHub(Search API) / arXiv / HF 实现检索，InfoQ / 36氪 走默认过滤；`topic_service.run_topic_scan(topic_id)`：检索 → upsert items → 记 hits（去重）→ 更新主题状态
- [ ] 主题定时任务：per-topic interval job（`ai_trending_topic_{id}`，`interval_minutes`，enabled 才注册），`register_all_enabled_jobs()` 启动兜底（对齐 xhs `register_all_enabled_jobs`）
- [ ] 主题列表页：卡片/表格 + 新建/编辑/删除 + 每主题状态徽标、最近抓取时间、命中总数、推送开启徽标
- [ ] 主题详情页：返回按钮 + 该主题热点列表（`/{id}/items` 分页，热度/时间排序，点击弹详情/跳原文）+ 立即抓取按钮 + 推送配置按钮
- [ ] 主题级推送配置：`PUT/GET /{id}/push-config`（channel 下拉占位 wecom/dingtalk/feishu/email + frequency + time + 开关），**仅落库**，实际发送由其他分支开发（可复用现有 mock Sender 协议）
- [ ] **移除全局推送卡片**：前端 `views/ai-trending/index.vue` 删除顶部「定时推送」配置卡片区块；`push_webhook.py` / `push_service.py` 底层保留复用

**P1（重要）**
- [ ] 主题立即抓取按钮 run-now：`POST /topics/{id}/run-now`（复用 run_topic_scan，异步 + 限频，对齐 xhs run-now）
- [ ] 抓取记录/最后状态：主题状态机（idle/running/failed）+ last_run_at / last_run_message / last_item_count 完整展示；可选记入统一 `Task` 表（module='ai_trending'，仿 xhs `_record_task`）
- [ ] 关键词多词支持：P0 按 JSON 数组落库，P1 完善前端多关键词输入交互 + OR 命中语义确认
- [ ] 主题级定时推送执行（P1）：按主题推送配置注册 cron job，复用 `build_sender()`（Mock）与 `push_service` 管线，`ai_trending_push_log` 加 `topic_id` 可空列记录主题推送；真实通道由其他分支接入
- [ ] 主题最近推送状态展示（主题详情页显示最近一次推送成功/失败/降级）

**P2（可选）**
- [ ] 主题分组/标签（topic group，列表页按组折叠）
- [ ] 主题热度趋势（该主题命中条目的 heat_score 时间曲线）
- [ ] 单主题多推送配置（多通道同时推 / 多时间点），届时把内嵌配置抽成独立表
- [ ] 主题命中过滤增强（must_include / must_exclude，对齐 XHS 过滤语义）

### 3.2 数据模型草案

**表 `ai_trending_topic`（主题，仿 `xhs_tracking_tasks`）**

| 字段 | 类型 | 约束/默认 | 说明 |
|---|---|---|---|
| id | int | PK | 主键 |
| name | str(128) | | 主题名称（如「AI Agent」「大模型开源」） |
| keywords | Text | 默认 "[]" | JSON 数组 `["agent", "multi-agent", "智能体"]`，P0 即支持多关键词；任一命中即算该主题命中（OR，P1 再考虑 AND） |
| interval_minutes | int | 默认 60 | 主题抓取频率（对齐 xhs interval_minutes：15/30/60/180/360/720/1440） |
| enabled | bool | 默认 True | 主题开关；false 时不注册定时任务、不抓取 |
| status | str(16) | 默认 "idle" | idle / running / failed（对齐 xhs status） |
| last_run_at | DateTime | 可空 | 最近一次抓取时间 |
| last_run_message | Text | 可空 | 最近一次抓取结果/失败原因 |
| last_item_count | int | 默认 0 | 最近一次抓取新增命中数 |
| push_enabled | bool | 默认 False | 主题推送总开关（内嵌推送配置，见 3.2.3 建议） |
| push_channel | str(16) | 默认 "wecom" | 推送方式：`wecom` / `dingtalk` / `feishu` / `email`（本次占位枚举，仅保存） |
| push_frequency | str(16) | 默认 "daily" | 推送频率：`daily`（每天）/ 预留 `hourly`、`every_12h` 等（P0 仅 daily 生效，见待确认 Q2） |
| push_time | str(5) | 默认 "09:00" | 推送时间（HH:MM，服务器本地时区，对齐既有 push_time 口径） |
| created_at / updated_at | DateTime | 默认 now | 时间戳 |

**表 `ai_trending_topic_hit`（主题命中，仿 `xhs_tracking_hits`）**

| 字段 | 类型 | 约束/默认 | 说明 |
|---|---|---|---|
| id | int | PK | 主键 |
| topic_id | int | FK → ai_trending_topic.id，index | 所属主题 |
| item_id | int | FK → ai_trending_items.id，index | 命中的热点条目（**引用**，不复制条目数据） |
| matched | bool | 默认 True | 是否命中（预留过滤语义，本次恒 True） |
| first_seen_at | DateTime | 默认 now | 该主题第一次看到该条目的时间（主题详情「最新」排序键） |
| created_at | DateTime | 默认 now | 记录创建时间 |

**表 `ai_trending_items`（保留，加可空 topic 关联？——见 3.2.2 决策）**

#### 3.2.1 主题命中表设计：复用 items 加 topic_id vs 新建 topic_hit？

**结论：新建 `ai_trending_topic_hit`（XHS 风格），`ai_trending_items` 不加 topic_id。理由：**

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A：`ai_trending_items` 加 `topic_id` 可空列 | 改动最小 | ① 一条热点可被多个主题命中（多关键词主题重叠），单列无法表达多对多；② 全局抓取入库的条目 topic_id 为空，语义混杂；③ 主题命中「首次见到时间」等主题维度的元数据无处安放 | ✗ 不采用 |
| B：新建 `ai_trending_topic_hit`（引用 item_id） | ① 完全对齐 XHS hit 模式（本次主要参照），工程师可复用既有心智；② 天然支持多主题多对多；③ 主题维度元数据（first_seen_at/matched）独立存放；④ items 表保持纯净，全局数据底座不受污染 | 多一张关联表 | ✓ **采用** |
| C：新建独立表并复制条目全量字段（XHS 存 note_json 的做法） | 与 XHS 完全一致 | 复制数据造成冗余，且 items 已有 url_hash 去重 + 完整字段，无必要 | ✗ 不采用（XHS 复制是因为小红书无统一条目表；我们已有统一 items 表） |

> 说明：XHS hit 存 `note_json` 是因为小红书笔记没有统一条目表；而 `ai_trending_items` 已经是统一条目表（url_hash 去重、热度归一化、保留策略齐全），因此 hit 表**引用 item_id** 即可，避免重复存储，同时保留 XHS 的「(topic_id, item_id) 唯一去重 + matched 占位」结构。

#### 3.2.2 旧功能处置：`ai_trending_items` 全局数据是否保留？

**结论：保留，作为数据底座。**
- 全局每小时抓取继续运行：① 维持 `ai_trending_source_status` 来源健康状态（`/sources` 端点与 UI 警示仍可用）；② 支撑「全部热点」二级视图（见 3.5）；③ 主题关键词命中的条目与全局池共享 `url_hash` 去重，主题命中即从池中引用，两边数据一致不打架。
- 主题抓取是**独立的定向检索**（不是从全局池过滤），检索结果 upsert 进 items（全局池也随之变厚），再通过 topic_hit 关联——两层数据天然同源，无冲突。
- 保留策略（7 天 / 2000 条）沿用：清理 items 时**级联删除**对应 topic_hit（`ondelete="CASCADE"` 或清理 job 中一并删除），避免孤儿 hit。

#### 3.2.3 推送配置：放 topic 表内嵌字段 vs 独立表？

**结论：P0 内嵌在 `ai_trending_topic` 表（push_enabled / push_channel / push_frequency / push_time 四字段）。理由：**
1. **1:1 关系**：一个主题一份推送配置，独立表只增加一次 join，无收益。
2. **列表页展示**：主题列表需要显示「推送开启徽标 + 通道名」，内嵌字段让 `TopicOut` 序列化零成本。
3. **迁移安全**：既有 `ai_trending_push_config`（id=1）保留不动（标记废弃、无 UI 入口），不破坏已上线数据。
4. **演进空间**：P2 需要单主题多推送配置时，再抽 `ai_trending_topic_push_config` 独立表（topic_id FK + 多行），当前设计不阻塞。

### 3.3 主题抓取设计（按关键词检索，非全局过滤）

**核心改动**：`TrendingSource` 基类新增可选方法 `search(keywords: list[str]) -> list[RawItem]`，默认实现 = `self.fetch()` 全量抓取后按关键词过滤（标题+摘要子串匹配，复用 `filter_ai_keywords` 逻辑）。

| 来源 | P0 检索实现 | 说明 |
|---|---|---|
| hn | Algolia API `search?query={kw}` | 官方支持检索，按 query 参数 |
| github | GitHub Search API `search/repositories?q={kw}&sort=stars` | Trending HTML 无检索能力，走 Search API（匿名限额 10 次/分，可配 token） |
| arxiv | API `search_query=all:"{kw}"` | 官方支持检索 |
| hf | models 接口 `search={kw}` / daily_papers 检索 | 支持部分检索；不可用则降级默认过滤 |
| infoq / kr36 | **默认过滤**（fetch() + 关键词过滤） | 仅全量 RSS，无检索接口，接受降级（见待确认 Q5） |

**执行流程（`topic_service.run_topic_scan`，对齐 xhs `run_scan` 风格）**：
1. 读 topic，未启用直接返回；置 `status=running`，commit。
2. 遍历注册表所有源：支持 `search()` 的调 `search(topic.keywords)`，否则调默认实现 → 收集 RawItem 列表。
3. 逐条 upsert 进 `ai_trending_items`（复用 `collector._upsert_items` 的 url_hash 去重 + 热度覆盖语义），拿到每条 item 的 id。
4. 对每条（已存在的或新入库的）item，查 `ai_trending_topic_hit` 是否已有 `(topic_id, item_id)`：无则插入（新增命中 +1），有则跳过（重复 +1）——主题维度去重，多次抓取不重复展示。
5. 更新 topic：`status=idle`、`last_run_at`、`last_run_message="本次新增命中 N 条"`、`last_item_count=N`；异常置 `failed` + 错误信息（对齐 xhs run_scan 的三态更新）。
6. SessionLocal() 自开自关（调度器线程），与 `_run_source_job` 一致。

**定时任务**：`scheduler_jobs.py` 新增 per-topic interval job——`register_topic_job(topic)`（`trigger="interval", minutes=interval_minutes, id=ai_trending_topic_{id}, replace_existing=True`）、`unregister_topic_job(topic_id)`；创建/更新（enabled 变化）/删除时调用；`register_all_enabled_jobs()` 启动时遍历 enabled 主题全部注册（对齐 xhs）。

### 3.4 API 草案（对齐 xhs tracking 风格，全部 `Depends(get_current_user)`）

```
GET    /api/ai-trending/topics                              → TopicOut[]
       # [{id, name, keywords[], interval_minutes, enabled, status, last_run_at,
       #   last_run_message, last_item_count, total_item_count, next_run_at,
       #   push:{enabled, channel, frequency, time}, created_at}]
       # next_run_at 读 APScheduler 真实 job.next_run_time（对齐 xhs _next_run_at）

POST   /api/ai-trending/topics                              → TopicOut
       # body: {name, keywords[], interval_minutes?, enabled?, push?}
       # 校验：name 非空、keywords 非空数组、interval_minutes 在允许集合、push.time HH:MM

GET    /api/ai-trending/topics/{topic_id}                   → TopicOut | 404

PUT    /api/ai-trending/topics/{topic_id}                   → TopicOut
       # 同 POST 校验；enabled 关→开或 interval 变化时重注册定时任务；开→关注销

DELETE /api/ai-trending/topics/{topic_id}                   → {success: true}
       # 注销定时任务 + 级联删除 topic_hit + 删除 topic（对齐 xhs delete_tracking_task）

POST   /api/ai-trending/topics/{topic_id}/run-now           → {success: true}
       # 立即抓取：异步线程 run_topic_scan(topic_id)，限频（如 60s 一次）或直接入队

GET    /api/ai-trending/topics/{topic_id}/items?sort=heat|time&page=1&page_size=20
       → { items: [TrendingItemOut 同现有字段], total, page, page_size }
       # 该主题命中列表：join ai_trending_topic_hit + ai_trending_items
       # sort=heat（默认, heat_score DESC）/ time（first_seen_at DESC）

GET    /api/ai-trending/topics/{topic_id}/push-config       → {enabled, channel, frequency, time}
PUT    /api/ai-trending/topics/{topic_id}/push-config       → 同上
       # body: {enabled, channel: wecom|dingtalk|feishu|email, frequency: daily|..., time: HH:MM}
       # 仅落库 topic 表内嵌字段；本次不触发任何真实发送（发送由其他分支接入）
       # P1 可选：GET /topics/{id}/push-logs 最近推送记录（push_log.topic_id）

# 既有端点保留：
GET    /api/ai-trending/items                               # 数据底座/「全部热点」视图
GET    /api/ai-trending/sources                             # 来源健康状态（保留）
POST   /api/ai-trending/refresh                             # 全局手动刷新（保留，数据底座）
GET    /api/ai-trending/push/config | /latest | POST /test  # 全局推送端点标记 deprecated，不删除（避免破坏既有调用）
```

### 3.5 UI 设计稿（文字描述，风格对齐现有模块 + XHS tracking）

**总结构**：`views/ai-trending/index.vue` 重构为「列表-详情」两态单页（仿 `views/xhs/tracking/index.vue`：列表态 ↔ 详情态，顶部返回箭头切换），**移除顶部全局推送配置卡片**。页面提供顶部入口切换到「全部热点」（保留原热榜 Tab/筛选/列表视图，暗色卡片复用）。

**① 主题列表态（默认）**

```
┌──────────────────────────────────────────────────────────────┐
│ 🔥 AI 主题跟踪         [全部热点]  [＋ 新建主题]                │
├──────────────────────────────────────────────────────────────┤
│ ┌─────────────────────┐  ┌─────────────────────┐             │
│ │ 📌 AI Agent          │  │ 📌 大模型开源         │             │
│ │   [agent][智能体]     │  │   [llm][open-source] │             │
│ │   ● 运行中 · 每 1 小时 │  │   ● 运行中 · 每 3 小时 │             │
│ │   最近抓取 12 分钟前   │  │   最近抓取 2 小时前    │             │
│ │   命中 128 条 · 本次+5 │  │   命中 46 条 · 本次+1 │             │
│ │   🔔 每日 09:00 企微   │  │   🔔 未开启推送        │             │
│ │   [立即抓取][推送配置][⋯]│  │   [立即抓取][推送配置][⋯]│             │
│ └─────────────────────┘  └─────────────────────┘             │
└──────────────────────────────────────────────────────────────┘
```

- 顶部：标题「AI 主题跟踪」+「全部热点」入口 + **新建主题按钮**。
- 主题卡片：名称、关键词 chips、状态点（运行中=绿 / 已暂停=灰 / 扫描中=琥珀脉冲 / 失败=红，对齐 xhs `statusInfo`）、抓取频率、最近抓取相对时间、命中总数 + 本次新增、**推送徽标**（开启则显示 `🔔 每日 09:00 企微`，未开则灰字「未开启推送」）。
- 操作：立即抓取（run-now）、推送配置、更多（编辑/删除，删除二次确认提示将清空该主题命中）。
- 空态：插画 + 「还没有跟踪主题，点击右上角新建」。
- 新建/编辑主题弹窗：名称 Input、关键词多输入（tags 输入，P0 支持多词）、抓取频率下拉（15 分钟/30 分钟/1 小时/3 小时/6 小时/12 小时/每天，对齐 xhs FREQUENCY_OPTIONS）、启用开关、保存。

**② 主题详情态（点击主题卡片进入）**

```
┌──────────────────────────────────────────────────────────────┐
│ ← 返回      📌 AI Agent        ● 运行中 · 最近抓取 12 分钟前    │
│             [agent][智能体]     命中 128 条                     │
│             [立即抓取] [推送配置] [编辑]                         │
├──────────────────────────────────────────────────────────────┤
│ 热度 [全部|新闻|项目|论文|模型]  排序 [热度|最新]   共 128 条     │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ [HN] 新多智能体框架发布…        ★ 热度 78 · 2 小时前       │ │
│ │ [GitHub] xyz/agent-kit ★ 120   ★ 热度 65 · 5 小时前       │ │
│ │ ...（列表卡片复用现有样式：来源徽标/标题/摘要/热度/时间）    │ │
│ └──────────────────────────────────────────────────────────┘ │
│                            [分页]                             │
└──────────────────────────────────────────────────────────────┘
```

- 顶部：返回箭头 + 主题名 + 状态点 + 关键词 chips + 最近抓取/命中统计；操作按钮：立即抓取（loading 态）、推送配置、编辑。
- 热点列表：复用现有热榜列表卡片（来源徽标、标题、摘要 2 行截断、热度、相对时间），点击弹详情弹窗（完整摘要 + 跳转原文按钮新窗口）。
- 筛选/排序：类型胶囊 + 热度/最新 Segmented（对齐现有热榜页交互）。
- 空态：该主题暂无命中，提示「点击立即抓取开始追踪」。

**③ 推送配置弹窗（主题详情 → 推送配置）**

```
┌──────────────────────────────────────────────────────────────┐
│ ⚙ 推送配置 — AI Agent                                [开关]   │
│  推送方式   [企业微信 ▾]  （下拉：企业微信 / 钉钉 / 飞书 / 邮件） │
│  推送频率   [每天 ▾]      （P0：每天；P1 扩展每 N 小时）         │
│  推送时间   [🕘 09:00]                                          │
│  ⓘ 实际发送通道开发中，本次仅保存配置；对接后按此处配置推送       │
│                    [保存] [取消]                                │
└──────────────────────────────────────────────────────────────┘
```

- 推送方式：Select 占位选项 `wecom 企业微信 / dingtalk 钉钉 / feishu 飞书 / email 邮件`，仅保存枚举值。
- 推送频率：Select（P0 仅 `daily 每天` 生效，其余选项置灰标注「即将支持」）。
- 推送时间：TimePicker HH:MM（校验，复用现有 onPushTimeChange 逻辑）。
- 开关：Switch 总开关；保存调 `PUT /topics/{id}/push-config`，成功 message 提示「推送配置已保存」。
- 提示文案：注明「实际发送通道开发中，本次仅保存配置」。
- P1：下方追加最近推送状态区（复用现有 latestPush 的 Tag/Alert 展示，按 topic_id 过滤）。

### 3.6 文件结构（增量）

```
backend/app/ai_trending/
├── models/
│   ├── __init__.py                  [修改] 导出 AiTrendingTopic / AiTrendingTopicHit
│   ├── topic.py                     [新建] AiTrendingTopic ORM（含内嵌推送配置字段）
│   ├── topic_hit.py                 [新建] AiTrendingTopicHit ORM（Unique(topic_id, item_id)）
│   └── push_log.py                  [修改] 加 topic_id 可空列（P1 记录主题推送）
├── schemas/
│   ├── __init__.py                  [修改] 导出 TopicIn/Out、TopicPushConfigIn/Out、TopicHitPage
│   └── topic.py                     [新建] Pydantic 出入参（keywords 校验、channel/time 校验）
├── services/
│   ├── base.py                      [修改] TrendingSource 增加 search(keywords) 默认实现（fetch+过滤）
│   ├── sources/{hn,github,arxiv,hf}.py [修改] 实现 search()；infoq/kr36 用默认
│   ├── topic_service.py             [新建] topic CRUD + run_topic_scan + 命中去重 + 状态更新
│   └── scheduler_jobs.py            [修改] register/unregister_topic_job + register_all_enabled_jobs 增补
└── controllers/
    ├── __init__.py                  [修改]
    └── topic.py                     [新建] /api/ai-trending/topics/* 路由（CRUD + run-now + items + push-config）

frontend/apps/web-antd/src/
├── api/core/ai-trending.ts          [修改] 新增 Topic/TopicHitPage 类型 + topics CRUD/run-now/items/push-config 请求函数
└── views/ai-trending/index.vue      [重构] 列表-详情两态 + 新建/编辑主题弹窗 + 推送配置弹窗；移除全局推送卡片；保留「全部热点」视图
```

### 3.7 与既有约定的对齐

- 错误语义：400 参数错误 / 404 不存在 / 429 限频（run-now）/ 502 上游抓取失败（对齐 resource/trending）。
- 时间：库内 `datetime.now(timezone.utc)`；`push_time` / 定时任务按服务器本地时区解释（对齐既有 push 口径）。
- SQLite 并发：调度器线程内 `SessionLocal()` 自开自关（同 `_run_source_job` / xhs `run_scan`）。
- 日志：loguru；主题抓取成功/失败必须留痕（`last_run_message` + logger）。
- 依赖最小化：**零新增后端依赖**（检索复用 requests / 现有 API 调用模式）。

---

## 4. 验收口径（重构增量）

- 新建主题（含 2+ 关键词）保存后：列表页出现该主题卡片，`next_run_at` 有值；点击「立即抓取」后 30 秒内 `last_run_at` 更新、命中数增长；主题详情页出现该主题热点列表。
- 主题抓取与全局抓取并行：同一 URL 在 items 表只一行（url_hash 去重）；同一主题重复抓取同一条目不再新增 hit（详情列表不重复）。
- 删除主题：topic_hit 级联清理，items 全局数据不受影响；定时任务注销。
- 保存主题推送配置（如 企业微信 + 每天 + 09:00 + 开）：回读一致，页面显示 `🔔 每日 09:00 企微` 徽标；**不触发任何真实发送**（mock Sender 仅 P1 接入执行）。
- 前端「AI 开发热点」页不再出现全局推送配置卡片；「全部热点」视图与来源健康状态正常。

---

## 5. 待确认问题（Open Questions，附建议）

1. **旧热榜页去留**：重构后「全部热点」（全局热榜 + 来源 Tab/筛选）是保留为二级入口，还是彻底移除只留主题？**建议保留**：`ai_trending_items` 既作数据底座又有来源健康状态，保留「全部热点」视图成本低、可让用户先看到全局再建主题，且不破坏已上线能力。
2. **推送频率语义**：需求为「推送频率 + 推送时间」，P0 是否只支持「每天固定时刻（push_time）推送」、频率字段先落库 `daily` 占位，interval 类型（每 N 小时）P1 再做？**建议 P0 只做 daily**：与既有 push cron 完全同构（`hour/min from push_time`），避免为未落地的多频率调度引入复杂度。
3. **主题抓取与全局抓取的关系**：主题抓取是独立关键词检索（已确认），全局每小时抓取是否继续保留？**建议保留**作数据底座（见 3.2.2）；若希望「主题内容 100% 来自定向检索、全局抓取仅作池子」，需要确认保留全局抓取不会让用户误解「主题数据来自全局过滤」——实现上主题命中只来自 `search()` 结果，不会混入全局池条目（除关键词检索本身命中的外）。
4. **多关键词匹配逻辑**：主题多个关键词之间是 OR 还是 AND？XHS 用单 keyword + must_include/must_exclude 表达 AND。**建议 P0 用 OR**（任一关键词命中即算该主题命中，交互最简单、命中量最大）；AND 语义留给 P1 的 must_include（对齐 XHS）。
5. **来源检索能力差异**：InfoQ/36氪 仅全量 RSS、无检索接口，主题抓取时只能「抓全量 feed → 关键词过滤」，与 HN/GitHub/arXiv/HF 的「真检索」并存。**建议接受该降级**：对 RSS 源过滤出的条目同样 upsert + 记 hit，仅说明「部分来源为全量扫描过滤」；若后续噪声大可再按主题限制来源（P2）。
6. **推送配置的通道参数**：本次只保存「方式/频率/时间/开关」，不填 webhook/收件人；未来接入真实通道（企微 webhook / 钉钉 / 飞书 / 邮件收件人）时参数放哪？**建议**：本轮 `ai_trending_topic` 只存 channel 枚举，具体通道参数（webhook_url、secret、收件人邮箱等）在真实通道分支开发时新增字段（或抽独立配置表），避免本轮过度设计；P1 调度执行复用的 mock Sender 协议已预留 `build_sender(config)` 工厂，切换通道不改 `push_service`。
