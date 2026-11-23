# TODO / 后续优化

> 记录暂不动手、留待后续处理的优化项。每条注明背景和建议方案，方便以后直接捡起来做。

## 小红书笔记数据全局去重缓存（2026-08-02 记录）

**背景**：小红书笔记的文本/互动数据目前已经存库了，但是按采集任务存的（`XhsTaskExtra.result_json`，每个任务一份 JSON blob），不是按笔记去重的全局库。同一篇笔记如果被不同的采集任务或追踪任务命中，会重新调用一次 `spider_note()` 抓详情、存一份重复数据，没有跨任务复用，浪费接口调用次数（且增加触发小红书风控的概率）。

**建议方案**：

1. 新增一张全局笔记表（`note_id` 唯一键），存标题/正文/互动数据/标签/发布时间等结构化字段 + `last_fetched_at`。采集任务、追踪扫描命中某个 `note_id` 时先查这张表，命中且未过期就直接复用，不再调用 `spider_note()`。
   - 搜索列表接口（`search_some_note`）还是要调，用来发现新笔记候选；省的是"逐条抓详情"这部分调用，通常是接口调用量的大头。
2. 元数据进库、素材留本地：图片/视频等大文件不进 SQLite，继续放 `backend/storage/xhs_tasks/{id}/media/`，或者只存 CDN 原始 URL，靠现有的 media proxy 接口（`buildXhsMediaProxyUrl` / `/api/xhs/proxy/media`）实时代理拉取，不强制下载落盘。
   - **待验证**：小红书图片/视频 CDN URL 是否带时效性签名。如果是短时效签名链接，长期存 URL 复用会失效，需要抓包实测确认，不能假设它长期有效——这个结论会直接影响"要不要强制下载素材到本地"的取舍。
3. AI 分析读取路径（`analysis_project.list_project_notes` → 回源 `XhsTaskExtra.result_json`）如果改成全局表，要同步换成按 `note_id` 查全局表，不再依赖 `task_id` 反查，逻辑更干净。
4. 需要一个 TTL 或手动刷新机制：复用旧数据意味着点赞/评论数会过期，不能永久冻结数据。建议加 `last_fetched_at` 超过 N 天允许过期重抓，或者在 UI 上提供"刷新这篇笔记"的入口。

**状态**：已实施（2026-08-03）。

- 新增 `app/xhs/models/xhs_note.py`（`XhsNote`，`note_id` 主键）+ `app/xhs/services/note_cache.py`（`get_or_fetch_note`/`upsert_note`/`get_cached_note(s_map)`，默认 TTL 3 天）。
- `tasks.py::_run_task` 和 `tracking.py::run_scan` 里原来直接调 `spider_note()` 的地方都换成了 `note_cache.get_or_fetch_note()`；抓取失败但缓存里有旧数据时会退回旧数据而不是整条笔记直接失败。
- `analysis_project.list_project_notes` 改成优先查全局缓存（按 `note_id`，不再依赖 `task_id` 反查），缓存没有的才退回旧的 `task_id → get_preview` 路径，并顺手回填进全局表——不需要一次性迁移脚本，项目笔记会在被访问到时逐步"迁"进新表。已经在真实数据上验证过（普吉岛项目 288 篇笔记，一次性全部正确回填）。
- 新增手动刷新入口：`POST /api/xhs/notes/{note_id}/refresh`（强制重抓、覆盖缓存），笔记管理页详情弹窗里加了"刷新最新数据"按钮。
- 第 2 点（CDN URL 是否长期有效）**仍未验证**，本次没有改动素材下载/展示逻辑，media proxy 仍然是直接实时转发笔记里的原始 CDN URL，风险和之前一样，不因为这次改动变化。

## 素材下载速度优化 —— 剩余项（2026-08-02 记录）

**背景**：`downloading_media` 阶段（`app/xhs/services/utils/data_util.py::download_note`/`download_media`）之前完全串行、每次请求都新建连接，已经优化了三项：① 共享 `requests.Session()` + 连接池；② 单篇笔记内图集多图/视频封面+正文并发下载（`ThreadPoolExecutor`，并发度 `_MEDIA_DOWNLOAD_WORKERS=5`）；③ 下载前检查文件是否已存在且非空，存在则跳过。已验证：7 篇笔记、477 个媒体文件（92MB）从原来的纯串行降到 15 秒内完成；对已下载笔记重跑 `download_note` 耗时 0.001 秒（确认真的跳过而不是重新请求）。

**还没做、留到后续的三项**：

1. **笔记与笔记之间也做有限并发**，而不是等一篇笔记的素材全部下载完才开始下一篇。当前 `tasks.py::_run_task` 里 `for i, note_info in enumerate(parsed_notes): download_note(...)` 仍然是逐篇笔记来。注意这里指的仍然是媒体下载这一步（打 CDN 域名），不涉及需要签名 header 的搜索/详情接口调用，和"整个采集任务串行跑防风控"的设计不冲突。
2. **把 `@retry(tries=3, delay=1)` 的重试粒度从整个 `download_note()` 下沉到单个文件**。现在图集内并发下载后，任何一张图片失败仍然会让异常冒泡，触发对整篇笔记（包括已经下载成功的图片，虽然现在有跳过逻辑，重试时会因为"已存在"而跳过重复下载，实际重复下载的浪费已经被第③项间接缓解了不少，但重试本身仍然是笔记级别，白白多等 delay、多发起一次已经用不上的整轮调度）。
3. **`REQUEST_TIMEOUT = 15` 秒是否需要调低**，配合更细粒度的单文件重试来减少个别慢请求拖累整体感知速度的情况；需要谨慎实测（调太低可能在网络本来就一般的环境下增加误判失败率），不能直接改。

**状态**：1/2/5 已完成并验证；3/4/6（对应本条的 1/2/3）仅记录，未实施。

## 主题报告 L2 全文并发抓取失败——疑似 SQLite 并发写冲突（2026-08-29 记录）

**背景**：主题报告生成 L2 阶段并发抓全文（`topic_report_service._fetch_fulltexts_concurrent`，`FULLTEXT_WORKERS=5`）时，实测出现一批 15 条**全部**抓取失败（日志：`funnel L2 成稿开始：32 条入选 + 0 篇全文`），且全部命中同一条通用异常日志，没有一条走"抓取失败/正文过短/付费墙"这些各自有专门 info 日志的正常降级分支——不像 15 个网站碰巧都抓不到，更像某个系统性问题。

**诊断（未 100% 确认——异常信息被日志吞了，见方案第 1 条）**：
1. `_fetch_fulltexts_concurrent`（`topic_report_service.py:288`）catch 到异常只打印 `f"全文获取异常（item {item.id}）"`，**没带 `str(exc)` 或 `exc_info=True`**，目前完全看不出真实异常类型。
2. `fetch_fulltext()`（`fulltext_service.py`）每次调用独立开一个新 `SessionLocal()`，5 个线程并发对**同一个 SQLite 文件**各自 `db.add()` + `db.commit()`（写 `HotItemContent` 缓存行）。
3. `backend/app/core/database.py` 的 SQLite 引擎只开了 `PRAGMA foreign_keys=ON`，**没开 WAL 模式，也没设 `busy_timeout`**——默认 rollback journal 同一时刻只允许一个写者，其他连接的 commit 在竞争下容易超时报 `database is locked`。
4. 15 条全部在约 1.5 秒内失败，比真实网络请求失败/超时（`FULLTEXT_TIMEOUT=8`s）的时间分布快得多，更像并发 commit 互相打架。

**建议方案**：
1. 先修日志：把异常内容打出来（`logger.exception(...)` 或加 `exc_info=True`）——不管是不是猜的这个原因，这个都该修，下次复现能立刻确认根因。
2. 给 SQLite 引擎开 WAL 模式（`PRAGMA journal_mode=WAL`），加在 `database.py` 现有 `@event.listens_for(engine, "connect")` 回调里，跟 `PRAGMA foreign_keys=ON` 放一起；这是"多线程各自开连接并发写同一个 SQLite 文件"场景的标准解法。可以顺带加个 `busy_timeout`（比如 5000ms）兜底，减少偶发竞争时的失败率。

**状态**：已实施（2026-08-29）。`database.py` 的 `_enable_sqlite_foreign_keys` 回调里加了 `PRAGMA journal_mode=WAL` + `PRAGMA busy_timeout=5000`；`_fetch_fulltexts_concurrent` 的异常日志加上了 `{exc}`。重启后端验证 `PRAGMA journal_mode` 返回 `wal`，符合预期。

## 榜单条目行内加「查看摘要」按钮（2026-08-29 记录）

**背景**：`HotlistApi.Item.summary` 后端接口本来就有返回，且已经在用——列表页搜索框（`q` 参数）就是拿它去匹配标题/摘要/来源；但整个榜单页面目前**没有任何地方把 summary 渲染出来给用户看**。现有「详情」按钮打开的弹窗（`board/index.vue::openDetail`）展示的是当前榜位/历史最佳/权重/命中规则 + 榜位曲线图，唯独没有摘要正文。想知道一条新闻具体讲了什么，现在只能点标题链接跳去原文。

**建议方案**：
1. 每行最右侧（现有「详情」按钮同一列）加一个「摘要」按钮/图标，点击展示该条目的 `summary`。
2. 交互形式两个可选方向，待实现时定：
   - a. 轻量气泡卡片（Popover，hover 或 click 展开）——`summary` 字段本来就随列表接口一起返回了，不需要额外请求，纯前端展示。
   - b. 直接并进现有「详情」弹窗，加一个「摘要」分区，跟榜位曲线等信息放一起，不新增交互入口。
3. `summary` 是 HTML（RSS 摘要原文），渲染前需要跟其他地方一样处理一下（`strip_html` 或按需保留基本格式），别直接把标签糊到页面上。
4. 纯前端改动——`summary` 数据已经在 `listHotlistItemsApi` 返回的 `Item` 里，不需要动后端接口。

**状态**：已实施（2026-08-29）。按方案 a（轻量 Popover）实现：`board/index.vue` 每行「详情」按钮左侧加了一个文档图标按钮，点击弹出 Popover 展示该条目摘要；新增 `stripHtml()` 用 `DOMParser` 解析取 `textContent`（不用 `v-html`，避免不可信 RSS 内容里的恶意标签被当成真实 DOM 渲染）。浏览器实测点击生效。

## 主题源定时抓取任务莫名停止触发 + 生成报告前的新鲜度兜底（2026-08-29 记录）

**背景**：排查"主题勾选了好几个源，但只有部分源的数据进了报告"时发现，源 `rss-localhost-1b4625c5`（`http://localhost:1200/ai-bot/daily-ai-news`）的 `enabled=1`、`cron_expr="0 */4 * * *"`、`consecutive_failures=0`，看起来一切正常，但 `last_fetched_at` 卡在创建时那一次抓取，之后 13+ 小时里配置的每 4 小时一次**再没触发过**，导致这个源当天的候选池永远是空的（不是内容不相关，是压根没有"当天"的数据）。现场手动调用该源的"立即抓取"接口**一次就成功**（`total_fetched` 500→1500），证明源本身、网络、RSSHub 路由都没问题，纯粹是**定时任务不知道为什么没有按 cron 继续触发**。日志显示进程重启时 `register_all_enabled_jobs` 确实打了"6/6 个源"注册成功，但具体是哪个环节之后把这个 job 弄丢/没重新触发，还没查到根因（今天期间后端重启过多次，怀疑跟这个有关，但没实锤）。

**建议方案（分两块）**：

1. **根因排查**（优先级更高，这个不修，同类问题会在其他源上重演）：
   - 查 APScheduler 的 job store 在多次 `register_all_enabled_jobs()` 重复调用后是否存在 job 被覆盖/丢失的情况（`replace_existing=True` 理论上没问题，但要确认没有别的路径绕过了 `register_job`）。
   - 确认是否跟频繁重启后端有关——本次是在同一进程存活期间内没有重启的情况下也没触发，先排除"重启导致 job 没重新注册"，重点看**进程存活期间** cron 为什么没有按预期 fire。
   - 补充监控/日志：至少要能在"job 应该触发但没触发"时留下痕迹，现在完全没有任何相关日志行（连失败日志都没有，是彻底沉默）。

2. **生成报告前的新鲜度兜底**（用户提出的思路，能直接堵住这次的表现，但不是根因修复，两者都要做）：
   - 在 `generate_report()` 里，`compute_period()` 算完 `period_start/period_end`、`fetch_candidate_pool()` 之前，加一步检查：对主题绑定的每个源（`_topic_source_ids()`），若 `HotSource.last_fetched_at < period_start`（说明这个源在本期窗口内还没更新过），调用现成的 `crawl_service.run_crawl(db, source_ids=[stale_ids], trigger="manual")` 强制刷新一次，成功了再继续走候选池。
   - 判断"过没过期"要按主题的 `period_start`（daily/weekly 各自的窗口起点），不能写死"今天"——weekly 主题的源本来就可能几天更新一次，按天判定会误伤。
   - 强制刷新本身失败（源真的挂了，不是"没触发"而是"触发了也抓不到"）不能阻塞报告生成——记日志、这个源这期就是没数据，继续往下走，跟现有 RSS 抓取失败的容错哲学保持一致。
   - 只检查主题实际绑定的源，不要全局扫一遍所有源。

**状态**：第 2 项（新鲜度兜底）已实施（2026-08-29）：新增 `_ensure_sources_fresh(db, topic, period_start)`，在 `generate_report()` 里 `ensure_topic_embedding` 之后、`fetch_candidate_pool` 之前调用，按 `HotTopicSource` 绑定关系找出本期未更新的源并调 `run_crawl` 强制刷新，失败只记警告不阻塞。

上线后立刻炸了一次：`HotSource.last_fetched_at`（SQLite 读出来是不带时区的 naive datetime）直接跟 `period_start`（带 UTC 时区）在 Python 层 `<` 比较，报 `TypeError: can't compare offset-naive and offset-aware datetimes`，导致手动生成报告直接失败。修法：把比较交给 SQL 层做（`db.query(HotSource.id).filter(..., or_(last_fetched_at.is_(None), last_fetched_at < period_start))`），跟 `fetch_candidate_pool()` 里 `HotItem.last_crawl_time` 的比较方式保持一致——SQLite 存的是字符串，SQL 层比较不区分 tzinfo，不会有这个问题。修完重新触发验证：`source_count` 从 2 涨到 4（4 个绑定源全部贡献了数据），生成成功，没有再报错。

第 1 项（根因排查）**仍未处理**——需要长时间观察 APScheduler 实际行为才能定位，不是能一次性改代码解决的事，继续留在这里跟踪。

## Skill 系统只扫描仓库内置根，不再扫外部目录（2026-08-29 记录）

**背景**：`storage_service.py` 目前是"双根"扫描——`REPO_SKILLS_ROOT`（`workbench/skills/`，仓库内）+ `EXTERNAL_SKILLS_ROOT`（`~/.workbench/skills/`，主目录下，本意是给"用户自行导入的 Skill"留位置）。实际排查发现 `~/.workbench/skills/` 里躺着 58 个跟本项目完全无关的公开 UI/设计类 Skill 包（`swiss-design`/`oklch-skill`/`rams`/`apple-design`/`12-principles-of-animation` 等），扫描逻辑（`_all_skill_roots()`）不区分来源，只要目录下有 `SKILL.md` 就全部注册进 `skills` 表，跟用户自己真正需要的 `gemini-travel-planner` 混在一起，Skill 管理页面看着很乱。仓库内置根目前只有 `gemini-travel-planner` 一个，是干净的。

**建议方案**：
1. `_all_skill_roots()`（`storage_service.py:39`）改成只返回 `[REPO_SKILLS_ROOT]`，去掉外部根这一路扫描；`resolve_skill_root()` / `list_builtin_skill_dirs()` 里对应的多根遍历逻辑一起简化。
2. `EXTERNAL_SKILLS_ROOT` 常量、`WORKBENCH_SKILLS_DIR` 环境变量可以一并去掉，除非以后真要做"外部导入"这个功能——目前看一直没人真正拿这个位置导入过项目相关的 Skill，反而先被一堆无关内容污染了。
3. 数据库里已经注册进去的那 57+ 条外部 Skill 记录光改扫描逻辑不会自动消失，需要一次性清理（按 skill_key 核对是否还能在新的单根扫描结果里找到，找不到的删掉对应 `skills`/`skill_versions` 行）。
4. 磁盘上 `~/.workbench/skills/` 那 58 个目录本身删不删是你自己的事，不属于代码改动范围——代码不再扫它们之后，留着也不影响。

**状态**：已实施（2026-08-29）。`_all_skill_roots()` 改成只返回 `[REPO_SKILLS_ROOT]`，`EXTERNAL_SKILLS_ROOT`/`WORKBENCH_SKILLS_DIR` 相关代码已删除；`topic-weekly-digest`（项目实际需要用到的 Skill）先从 `~/.workbench/skills/` 迁回 `workbench/skills/` 仓库根，再改扫描逻辑，避免连带丢失；数据库里清理掉了 57 条外部残留记录（`skills`/`skill_versions`/`skill_templates`），只剩 `gemini-travel-planner` 和 `topic-weekly-digest` 两个。重启后端验证：启动扫描正确识别两个 Skill，API 返回列表干净。磁盘上 `~/.workbench/skills/` 里剩下的 57 个无关目录未删除，留给你自己处理。

## 刷新页面时短暂显示 `%VITE_APP_TITLE%` 占位符未替换（2026-08-29 记录）

**背景**：前端 `apps/web-antd/index.html` 的 `<title>` 和加载动画模板（`internal/vite-config/src/plugins/inject-app-loading/default-loading-antd.html`）都用了 Vite 原生的 `%VITE_APP_TITLE%` 环境变量占位符（Vite 内置能力：自动把 `index.html` 里的 `%ENV_NAME%` 替换成对应环境变量值，不是这个项目自己写的替换逻辑）。但 `apps/web-antd/.env.development` 和 `.env.production` 里**从来没有定义过 `VITE_APP_TITLE`**，Vite 找不到值可替换，就把占位符原样留在了 HTML 里。平时加载动画只在 Vue 应用挂载前一闪而过，不容易注意到；这次是刷新页面时加载动画停留时间变长（当天改动多，HMR/依赖重新优化耗时变长），正好让占位符露出来了。

项目里另有一个自定义工具函数 `internal/vite-config/src/utils/env.ts::loadAndConvertEnv()`，其中 `appTitle` 对未定义的 `VITE_APP_TITLE` 有兜底默认值 `'Vben Admin'`（左上角 logo 文字显示正常就是这个兜底在起作用）——但这个兜底只作用于代码里读取的 `appTitle` 变量本身，**管不到** Vite 对 `index.html`/加载动画 HTML 里那个原生占位符字符串的替换，两边各管各的，所以出现"一处有兜底、一处没有"的不一致。

**建议方案**：在 `apps/web-antd/.env.development` 和 `.env.production` 里补上 `VITE_APP_TITLE=<应用名>`（可以对齐后端 `core/config.py` 里 `app_title` 的默认值"统一工作台"，或者继续用"Vben Admin"，看想不想统一品牌名）。加上之后 Vite 原生替换和自定义兜底就会一致，不会再出现占位符裸露的情况。

**状态**：已实施（2026-08-29）。两个 `.env` 文件都补了 `VITE_APP_TITLE=统一工作台`（对齐后端 `app_title` 默认值）。重启前端 dev server 验证：浏览器左上角 logo 与标签页标题都正确显示"统一工作台"。注意：已经访问过旧版本的浏览器会把 `app.name` 缓存进 `localStorage`（`xxx-preferences` 键），不会自动读取新值，需要清一次浏览器本地存储（或换个浏览器/隐私模式）才能看到效果——这是预期行为，不是修复没生效。
