# AI 开发热点聚合 — 简单 PRD

| 项目信息 | 内容 |
|---|---|
| Language | 中文 |
| Programming Language | FastAPI（后端）+ Vue Vben Admin / web-antd（前端），SQLite + SQLAlchemy + APScheduler，与既有模块一致 |
| Project Name | `ai_trending`（后端模块 `backend/app/ai_trending/`，前端路由 `frontend/apps/web-antd/src/router/routes/modules/ai-trending.ts`） |
| 原始需求 | 用户希望获取 AI 开发相关热点信息（技术 / 模型 / 工具等），从权威网站采集，做成工作台的一个新模块页面：热榜列表展示，点开可看详情/跳转原文，后端定时自动刷新 + 前端手动刷新双通道。 |

---

## 1. 热点来源调研结论（可抓取性验证）

> 原则：**可抓取性是第一优先 —— 宁可少而稳，不要多而挂。** 以下均经过实际验证（2026-08-15）。

### 1.1 验证矩阵

| # | 来源 | 抓取方式 | 验证状态 | 国内可达性 | 更新频率 | 推荐级别 |
|---|---|---|---|---|---|---|
| 1 | **Hacker News** | 官方 API（Algolia）`https://hn.algolia.com/api/v1/search?tags=front_page`，返回 title / url / points / num_comments / created_at | ✅ 已验证 | 一般可达 | 实时（每小时抓即可） | **P0** |
| 2 | **GitHub Trending** | 静态 HTML 抓取 `https://github.com/trending?since=daily`（SSR 渲染，仓库名/描述/今日 star 直接内嵌）；兜底 GitHub Search API（`search/repositories?q=created:>日期&sort=stars`） | ✅ 已验证（SSR HTML 可直接解析） | 偶有波动，需超时+重试 | 每日更新（每日抓 1-2 次即可） | **P0** |
| 3 | **arXiv** | 官方 API `https://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.LG&sortBy=submittedDate&sortOrder=descending&max_results=50`（Atom feed） | ✅ 已验证 | 可达但偶慢 | 每日美东 17:00 批量更新 | **P0** |
| 4 | **Hugging Face** | 官方 API 双通道：① 模型榜 `https://huggingface.co/api/models?sort=trendingScore&direction=-1&limit=50`（含 id/likes/downloads/trendingScore）；② 每日论文 `https://huggingface.co/api/daily_papers`（含 paper.id 可拼 arXiv 链接） | ✅ 已验证 | 可达 | 每日 | **P0** |
| 5 | **InfoQ 中国** | 官方 RSS `https://www.infoq.cn/feed`（RSS 2.0，title/link/pubDate/description 完整，AI 内容浓度高） | ✅ 已验证 | 国内可达 | 实时（每日数十条） | **P0** |
| 6 | **36氪** | 官方 RSS `https://36kr.com/feed`（已验证为有效 RSS 2.0，但为全站 feed，含大量非 AI 商业/创业新闻）→ **需 AI 关键词过滤** | ✅ 已验证（噪声大） | 国内可达 | 实时 | **P1** |
| 7 | **机器之心** | ⚠️ 无公开免费 RSS：`/rss` 实为「数据服务」页，提供**申请制免费 RSS**（个人订阅 ¥198/年 有更高频次 + MCP/Skills）；备选为抓 SSR 首页（存在 WAF/反爬风险） | ⚠️ 部分验证（需申请） | 国内可达 | 每日 | **P1/P2** |
| 8 | Papers with Code | API 维护不稳（Meta 收购后维护减少），且 HF daily_papers 已覆盖论文榜 | 知识判断 | — | — | 不推荐 |
| 9 | Awesome-AI | 为 GitHub 仓库、人工维护、更新不频繁，与「热点」定位不符 | 知识判断 | — | — | P2 可选 |

### 1.2 推荐来源组合（6 个，5-7 个目标区间内）

- **P0 必做（5 个）**：Hacker News、GitHub Trending、arXiv、Hugging Face（模型榜+每日论文）、InfoQ 中国 —— 全部为官方 API/RSS 或可稳定解析的静态页，零鉴权、零反爬，风险最低。
- **P1 重要（1 个）**：36氪（官方 RSS + AI 关键词过滤，覆盖中文泛科技快讯；噪声可控性需上线后观察）。
- **P1/P2 可选（1 个）**：机器之心（申请其免费 RSS 数据服务，需用户确认是否值得走申请流程）。

---

## 2. 产品定义

### 2.1 Product Goals

**一句话**：为开发者提供一个「打开就能看到今天 AI 圈在发生什么」的聚合热榜页，把分散在 HN / GitHub / arXiv / Hugging Face / 中文媒体的 AI 热点收敛到工作台一个页面，无需逐站访问。

**三个衡量指标**：
1. **来源可用率**：过去 7 天定时抓取成功率 ≥ 95%（核心稳定性，宁少而稳）。
2. **内容新鲜度**：热榜列表中 48 小时内发布的条目占比 ≥ 80%。
3. **内容供给量**：日均去重后新增热点条目 ≥ 50 条（确保页面长期有内容可看）。

### 2.2 User Stories

1. 作为**开发者**，我希望打开「AI 开发热点」页就能看到聚合后的热榜列表（按热度排序），以便不用逐个访问 HN / GitHub / arXiv 等网站即可掌握今日 AI 动态。
2. 作为**开发者**，我希望按来源筛选（全部 / HN / GitHub / arXiv / HF / InfoQ / 36氪）和按类型筛选（新闻 / 项目 / 论文 / 模型），以便快速定位我关心的那类热点。
3. 作为**开发者**，我希望点击列表项能查看摘要详情并跳转原文，以便深入了解感兴趣的条目。
4. 作为**开发者**，我希望看到「上次更新时间」并支持手动点击刷新，以便在定时任务之外按需获取最新热点。
5. 作为**开发者**，我希望热点数据自动每小时刷新且不产生重复条目，以便长期使用列表始终干净、可信。

---

## 3. 技术规范

### 3.1 需求池

**P0（必做）**
- [ ] 后端 `ai_trending` 模块四层结构（`controllers/ models/ schemas/ services/`），与 resource 模块风格一致，并在 `main.py` 注册路由
- [ ] 5 个 P0 来源抓取器：HN（Algolia API）、GitHub Trending（HTML + Search API 兜底）、arXiv（API）、HF（models + daily_papers 双接口）、InfoQ（RSS 解析）
- [ ] 热点条目数据模型（见 3.2），含 URL 去重键与索引
- [ ] 去重策略：同源同 URL 不重复入库；跨源同 URL（如 HN 引用 arxiv 链接）仅保留热度最高来源
- [ ] 每小时定时任务自动刷新（APScheduler，注册方式参考 `xhs_tracking.register_all_enabled_jobs`）
- [ ] 热榜列表 API：分页、来源筛选、类型筛选、热度/时间排序
- [ ] 手动刷新 API（带频率限制，如 10 分钟 1 次）
- [ ] 前端页面：来源 Tab / 筛选 + 列表卡片 + 手动刷新按钮 + 空态/加载态/错误态
- [ ] 前端路由注册（`router/routes/modules/ai-trending.ts`，参考 resource.ts）

**P1（重要）**
- [ ] 详情弹窗/抽屉：摘要展开、标签、来源徽标、跳转原文按钮
- [ ] 类型分类（news / project / paper / model）标签与筛选
- [ ] 关键词搜索过滤
- [ ] 来源健康状态：每个来源最近抓取时间 / 成功失败数，失败在 UI 上警示
- [ ] 36氪 AI 关键词过滤调优（上线后根据噪声反馈迭代）
- [ ] 跨源热度归一化排序（对数缩放 + 24h 时间衰减）
- [ ] 机器之心免费 RSS 数据服务申请接入（若用户确认）

**P2（可选）**
- [ ] 收藏 / 稍后读
- [ ] 热点关键词 Top N / 趋势曲线
- [ ] 每日热点摘要推送
- [ ] 热门仓库 / 工具榜单补充（如 Awesome-AI）
- [ ] 热点详情页缓存 / 命中缓存降级

### 3.2 数据模型草案

表 `ai_trending_items`：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | int PK | 主键 |
| source | str(32) index | 来源标识：hn / github / arxiv / hf_models / hf_papers / infoq / kr36 |
| title | str(512) | 标题 |
| url | str(1024) | 原文链接 |
| url_hash | str(64) unique index | 归一化 URL 的 MD5，去重键 |
| summary | Text | 摘要（RSS description / arXiv abstract / HF 摘要） |
| heat_score | float index | 热度分，跨源归一化到 0-100 |
| category | str(16) index | news / project / paper / model |
| tags | str(255) | JSON 数组（语言、框架、arXiv 分类等） |
| published_at | DateTime index | 原文发布时间（缺失则用抓取时间） |
| fetched_at | DateTime | 抓取时间 |
| created_at | DateTime | 入库时间 |

**热度分归一化规则**（P0 简化版）：
- HN：`log2(points + 1)` 归一化
- GitHub：`log2(stars_today + 1)` 归一化
- arXiv / HF papers：无热度 → 时间衰减默认分 `max(0, 10 - 距发布时间小时数/6)`
- HF models：`log10(trendingScore + 1)` 归一化
- InfoQ / 36氪（RSS）：时间衰减分（24h 内权重高）
- 统一再乘 `0.5^(距发布小时数/24)` 时间衰减，输出 0-100

### 3.3 API 草案（参考 resource 模块风格，统一 `Depends(get_current_user)`）

```
GET  /api/ai-trending/items?source=&category=&sort=heat|time&page=1&page_size=20
     → { items: [{id, source, title, url, summary, heat_score, category, tags, published_at, fetched_at}], total, page, page_size }

GET  /api/ai-trending/sources
     → [{ source_id, source_name, category_type, last_fetched_at, last_status, fail_count }]

POST /api/ai-trending/refresh        # 手动刷新，10 分钟限频 1 次
     → { triggered: true, message }
```

### 3.4 UI 设计稿（文字描述，风格对齐现有模块）

**热榜页（`/ai-trending`）**

1. **顶部操作栏**：页面标题「AI 开发热点」；右侧显示「上次更新：x 分钟前」+ **手动刷新按钮**（点击后 loading 态，完成后提示更新时间）。
2. **来源 Tab 行**（antd Tabs / 胶囊）：`全部 | 开发者社区(HN) | 开源项目(GitHub) | 论文(arXiv) | 模型与论文(HF) | 中文媒体(InfoQ·36氪)`。每个 Tab 带来源徽标色；某来源最近抓取失败时 Tab 右上角显示红色警示角标（P1）。
3. **类型筛选 + 排序行**：类型胶囊（全部/新闻/项目/论文/模型，P1）；排序切换（热度 默认 / 最新）。
4. **列表区**（antd List + Card）：每条目卡片包含——
   - 左：来源徽标（彩色圆点/标签，标识 HN/GitHub/arXiv/HF/InfoQ/36氪）
   - 中：标题（主链接，点击进入详情弹窗）；摘要 2 行截断（text-overflow）；标签 chips（P1）
   - 右/底部：热度信息（HN points / GitHub ★today / HF trendingScore）、发布时间（相对时间如「2 小时前」）
   - 点击卡片 → **详情弹窗**：完整摘要 + 标签 + 来源 + 发布时间 + 跳转原文按钮（新窗口）
5. **状态**：
   - 加载态：首屏骨架屏（Skeleton）；手动刷新按钮 loading
   - 空态：插画 + 「暂无热点数据，点击右上角刷新获取」
   - 错误态：接口失败 Alert 提示 + 重试按钮；单来源失败不影响整体列表
6. **分页**：与 resource 模块一致使用 antd 分页（每页 20）。

### 3.5 定时任务设计

- **注册方式**：在 `main.py` lifespan 中调用 `ai_trending.scheduler.register_all_enabled_jobs()`（参考 `xhs_tracking.register_all_enabled_jobs`），基于 `app/core/scheduler.py` 的进程内单例 BackgroundScheduler。
- **频率**：每来源一个 job，默认 cron 每小时（`minute=0`）；GitHub Trending 可配置每日 2 次（`hour=2,14`）。配置项集中在 settings 或模块 config。
- **并发与隔离**：各来源 job 相互独立，任一来源失败不阻塞其他来源。
- **去重**：`url_hash`（归一化 URL 的 MD5）unique 约束 + `INSERT OR IGNORE`；标题归一化（去首尾空白、大小写折叠）作为同源兜底；跨源同 URL 合并时保留热度分最高的记录。
- **失败重试**：单来源单次抓取失败重试 2 次（指数退避 5s / 15s）；连续失败 ≥ 3 次将该来源标记 `failed`，记录 `fail_count`，后续 job 照常执行；恢复成功自动清零。
- **保留策略**：超过 7 天的条目每日清理一次（或保留最近 2000 条），避免表无限膨胀。
- **手动刷新**：复用同一 collector runner，接口层做 10 分钟限频（Redis 或内存锁）。

### 3.6 文件结构（对齐 resource 模块）

```
backend/app/ai_trending/
├── __init__.py
├── models/ai_trending_item.py        # ORM 模型
├── schemas/trending.py               # Pydantic 出入参
├── services/
│   ├── base.py                       # 抓取器基类 + 热度归一化工具
│   ├── sources/hn.py / github.py / arxiv.py / hf.py / infoq.py / kr36.py
│   ├── collector.py                  # 统一执行抓取→去重→入库
│   └── scheduler_jobs.py             # APScheduler job 注册
└── controllers/trending.py           # /api/ai-trending/* 路由

frontend/apps/web-antd/src/
├── views/ai-trending/index.vue       # 热榜页
└── router/routes/modules/ai-trending.ts  # 路由注册（参考 resource.ts）
```

---

## 4. 待确认问题（Open Questions）

1. **默认排序**：热榜默认按「热度」还是「最新」？建议默认热度（跨源归一化 + 24h 时间衰减），可切换最新 —— 是否接受？
2. **点击行为**：列表项点击后是「直接新窗口跳转原文」还是「先弹详情弹窗、弹窗内再跳转原文」？建议后者（详情弹窗 + 跳转原文按钮）。
3. **机器之心**：其公开 RSS 为「数据服务」申请制（免费需申请，个人订阅 ¥198/年 更高频次）。是否值得为这一个来源走申请流程？还是 P1 阶段暂缓、直接用 36氪关键词过滤覆盖中文媒体？
4. **36氪取舍**：36氪全站 RSS 含大量非 AI 商业新闻，需关键词过滤（噪声可控但非零）。接受该方案，还是干脆去掉 36氪（保留 InfoQ + 机器之心作为中文来源）？
5. **数据保留**：保留 7 天 / 最多 2000 条是否合适？是否需要更长历史（如 30 天）以支撑后续趋势分析？
