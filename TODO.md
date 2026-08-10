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
