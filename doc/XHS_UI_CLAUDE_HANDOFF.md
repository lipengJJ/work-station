# 小红书分析 UI 重构交接文档（Claude 实施版）

> 文档版本：v1.1  
> 编写日期：2026-08-02  
> 项目目录：`/Users/lipeng01/vscode/workbench`  
> 目标：指导 Claude 在现有 Vue + Ant Design Vue + FastAPI 项目中实现已经确认的交互原型。  
> 本文档是开发交接材料，不代表代码已经完成。

## 1. 给 Claude 的执行指令

将以下内容与本文件一起交给 Claude：

```text
请先完整阅读 `doc/XHS_UI_CLAUDE_HANDOFF.md`，并把它作为本次小红书模块重构的产品和 UI 依据。

执行要求：
1. 先阅读文档列出的现有页面、API 和后端接口，不要重新发明数据层。
2. 修改前先列出计划改动的文件、复用的组件、接口差异和实施顺序，等待我确认后再编码。
3. 只保留文档约定的五个导航功能，不要删除后端能力和历史数据。
4. 优先复用 Ant Design Vue、当前主题 Token、现有 API 封装和 groupNotesByRecency。
5. 禁止把 Mock 数据写进生产页面；原型数据只用于理解布局。
6. 每完成一个阶段就运行类型检查、相关测试和页面验证，并对照验收清单汇报。
7. 不要修改股票分析及其他无关模块。
8. 如果现有接口不足，先明确说明缺少的字段和兼容方案，不要静默改变接口语义。
```

## 2. 已确认的产品范围

小红书分析左侧导航只保留：

1. 笔记管理
2. AI 分析
3. 分析报告
4. 采集任务
5. 追踪任务

已确认从产品中删除的独立功能：

- 评论管理
- 关键词统计
- 情绪分析
- 酒店/品牌提及排名

实施状态：对应前端路由和占位页面、后端占位接口已经删除；AI 分析中的“情感倾向”预置模板也已删除。采集任务的评论抓取与评论文件下载属于采集流程能力，不属于“评论管理”独立页面，继续保留。

当前路由文件：

- `frontend/apps/web-antd/src/router/routes/modules/xhs.ts`

## 3. 视觉规范

沿用工作台现有深色主题和 Ant Design Vue 组件，不另建第二套设计系统。

核心视觉参考：

| Token | 建议值 | 用途 |
|---|---:|---|
| 页面背景 | `#080b10` | 主背景 |
| 面板背景 | `#0d1118` | 表格、卡片、弹窗 |
| 次级面板 | `#111620` | Hover、选中状态 |
| 边框 | `#242c39` | 表格及分组边界 |
| 主文字 | `#edf1f7` | 标题和重要数字 |
| 次文字 | `#8290a5` | 描述、时间、辅助信息 |
| 品牌色 | `#665cff` | 主按钮、选中、关键操作 |
| 成功色 | `#38c976` | 运行中、成功 |
| 警告色 | `#eab653` | 风险、待关注 |
| 错误色 | `#ef6673` | 失败、危险操作 |

通用规则：

- 主操作使用品牌色实心按钮，次操作使用描边按钮。
- 状态必须同时有文字和图标/状态点，不能只靠颜色。
- 列表数字、状态和时间按列对齐。
- 长内容进入独立页面，不用大型弹窗承载。
- Hover 只提高边框和背景亮度，不引起布局跳动。
- 桌面优先，同时保证小于 `760px` 时不横向溢出。

## 4. 现有代码与接口地图

### 4.1 前端页面

| 功能 | 当前文件 |
|---|---|
| 笔记管理 | `frontend/apps/web-antd/src/views/xhs/notes/index.vue` |
| AI 分析 | `frontend/apps/web-antd/src/views/xhs/ai-analysis/index.vue` |
| 采集任务 | `frontend/apps/web-antd/src/views/xhs/collect-tasks/index.vue` |
| 追踪任务 | `frontend/apps/web-antd/src/views/xhs/tracking/index.vue` |
| API 与类型 | `frontend/apps/web-antd/src/api/core/xhs.ts` |
| 时间分组工具 | `frontend/apps/web-antd/src/utils/note-grouping.ts` |

### 4.2 后端接口

| 需求 | 现有接口 |
|---|---|
| 笔记管理任务列表 | `GET /api/xhs/notes` |
| 某采集任务的笔记 | `GET /api/xhs/notes/{task_id}` |
| 采集任务列表 | `GET /api/xhs/collect-tasks` |
| 创建采集任务 | `POST /api/xhs/collect-tasks` |
| 采集任务预览 | `GET /api/xhs/collect-tasks/{task_id}/preview` |
| 追踪任务列表/创建 | `GET/POST /api/xhs/tracking-tasks` |
| 更新追踪任务 | `PUT /api/xhs/tracking-tasks/{id}` |
| 立即执行追踪 | `POST /api/xhs/tracking-tasks/{id}/run-now` |
| 追踪命中笔记 | `GET /api/xhs/tracking-tasks/{id}/hits` |

后端相关文件：

- `backend/app/xhs/controllers/notes.py`
- `backend/app/xhs/controllers/collect_tasks.py`
- `backend/app/xhs/controllers/tracking.py`
- `backend/app/xhs/schemas/xhs.py`
- `backend/app/xhs/services/tasks.py`
- `backend/app/xhs/services/tracking.py`

现有 `/api/xhs/notes` 已经按“有笔记的采集任务”返回数据，适合直接作为笔记管理首页的数据源；不要在前端把所有笔记拉回后再自行拼主题。

## 5. 笔记管理：最终交互方案

### 5.1 一级视图：采集任务列表

默认进入“采集主题”，不直接显示 1,248 篇混合笔记。

顶部切换：

- `采集主题`：默认选中。
- `全部笔记`：用户主动查看跨任务的全部内容；如果后端暂时没有跨任务分页接口，第一阶段可以隐藏或禁用并标注接口待补，不能在浏览器端无限量合并全部任务。

任务列表必须采用 Table，不使用卡片网格。字段顺序：

| 字段 | 数据来源/说明 |
|---|---|
| 采集主题与关键词 | `task.keyword`；第一行主题，第二行关键词摘要 |
| 状态 | `task.status`，映射排队中/运行中/已完成/失败 |
| 主题笔记 | `task.note_count` |
| 本次新增 | 若现有接口无字段，第一阶段显示 `—`，不要伪造；后端补 `new_note_count` 后再接入 |
| 已选证据 | 若现有接口无字段，第一阶段显示 `—`；可后续从分析项目关联统计 |
| 最近更新 | 优先使用后端任务更新时间；目前只有 `created_at` 时先使用它并在代码中注明 |
| 操作 | 查看笔记/右箭头 |

列表行为：

- 默认按最近更新时间倒序。
- 支持按主题名称和关键词模糊搜索。
- 支持按全部、运行中、已完成、失败筛选。
- 点击整行或“查看笔记”进入任务详情。
- 键盘 Enter 也可进入，行必须有可见焦点样式。
- 空状态：没有任务时引导用户去“采集任务”创建任务。
- 搜索无结果：显示“没有匹配的采集任务”，保留清除筛选入口。

### 5.2 二级视图：任务笔记 Table

点击例如“新加坡二手家具”后，只展示这个 `task_id` 对应的笔记。

顶部上下文：

- 面包屑：`采集主题 / 新加坡二手家具`。
- 主题名称与关键词。
- 该任务总笔记数。
- “查看采集任务”入口。
- 返回任务列表。

笔记采用 Table，不使用当前卡片瀑布流。建议字段：

| 字段 | 对应 `XhsApi.Note` |
|---|---|
| 多选 | `note_id` |
| 笔记信息 | 封面 + `title` + `nickname` |
| 内容类型 | `note_type` |
| 发布时间 | `upload_time` |
| 点赞 | `liked_count` |
| 评论 | `comment_count` |
| 收藏 | `collected_count` |
| 标签 | `tags` |

排序与时间分组：

- 所有笔记先按发布时间倒序。
- 然后使用时间段分组：`最近一周`、`最近一个月`、`最近半年`。
- 最近一周：0–7 天。
- 最近一个月：大于 7 天且不超过 30 天。
- 最近半年：大于 30 天且不超过 180 天。
- 超过半年可增加“更早”分组，不能丢数据。
- 没有数据的分组不渲染。
- 复用并按上述边界校正 `frontend/apps/web-antd/src/utils/note-grouping.ts`。

Table 上方工具栏：

- 搜索标题、内容或作者。
- 内容类型筛选。
- 时间范围筛选。
- 互动量筛选。
- 更多筛选。
- 已选择数量。
- 批量加入 AI 分析。
- 添加标签（后端未支持时禁用并标注待实现）。
- 导出。

右侧分析篮：桌面端保留；窄屏改为抽屉或底部浮层。分析篮里的笔记必须来自当前主题，切换主题前提示是否清空当前选择。

### 5.3 笔记详情

现有详情 Modal 可保留，继续展示轮播图/视频、描述、标签、作者、时间、地区和原文链接。Table 行或标题点击打开详情；复用：

- `coverOf`
- `proxied`
- `openDetail`
- `openInXhs`

## 6. 新建采集任务弹窗

目标文件：`frontend/apps/web-antd/src/views/xhs/collect-tasks/index.vue`。

桌面宽度约 `720px`，分成：

1. 标题说明和关闭按钮。
2. 基础信息：任务名称、关键词、常用关键词快捷标签。
3. 采集范围：采集数量、发布时间、内容类型、结果排序。
4. 互动量过滤：点赞最低/最高、收藏最低/最高。
5. 是否同时采集评论。
6. 底部：重置、过滤摘要、取消、创建任务。

### 6.1 与现有接口的字段映射

| UI 字段 | 当前 `CollectTaskIn` | 处理方式 |
|---|---|---|
| 任务名称 | 无 | 如产品确实需要独立名称，后端新增 `name`；否则第一阶段以关键词作为主题名 |
| 关键词 | `keyword` | 直接使用；后端目前是字符串 |
| 采集数量 | `require_num` | 1–1000 |
| 排序 | `sort_type_choice` | 复用当前枚举 |
| 内容类型 | `note_type` | 复用当前枚举 |
| 发布时间 | `note_time` | 复用当前枚举 |
| 采集评论 | `fetch_comments` | 直接使用 |
| 点赞范围 | 无 | 需要后端/爬虫支持后再开放；第一阶段禁用或不展示 |
| 收藏范围 | 无 | 需要后端/爬虫支持后再开放；第一阶段禁用或不展示 |

不得把尚未被后端支持的筛选条件伪装成可用条件。

表单校验：

- 关键词必填。
- 最低值不得大于最高值。
- 提交时按钮 loading，阻止重复提交。
- 成功后关闭弹窗、刷新任务列表并显示成功反馈。
- 已填写内容时关闭弹窗应询问是否放弃。

## 7. 追踪任务列表

目标文件：`frontend/apps/web-antd/src/views/xhs/tracking/index.vue`。

使用单列紧凑 Table/List，不使用三列大卡片。字段：

1. 追踪主题、关键词、运行状态。
2. 本次新增（`last_hit_count`）。
3. 累计笔记（当前接口缺少累计字段时显示 `—`，建议后端新增 `total_hit_count`）。
4. 下次检查时间及执行频率。
5. 启动/暂停开关。
6. 更多操作：编辑、立即运行、删除。

状态规则：

- 运行中：绿色状态点，开关打开。
- 扫描中：使用 processing 状态并禁用重复“立即运行”。
- 已暂停：灰色状态点，计划显示“当前已暂停”。
- 失败：红色状态与错误摘要，提供重试。

### 7.1 后端差异

当前 `TrackingTask` 有 `last_run_at`、`last_hit_count`、`interval_minutes`、`enabled`，但没有明确的 `next_run_at`、累计命中数。推荐后端序列化补充：

```ts
next_run_at: string | null;
total_hit_count: number;
```

如果暂不补接口，前端只能根据 `last_run_at + interval_minutes` 推导下次时间，并在代码中标注这是推导值。

## 8. AI 分析与分析报告

### 8.1 AI 分析

保留现有分析项目和证据关联逻辑。分析输出至少包含：

- 核心结论
- 主要证据
- 风险与反例
- 下一步建议

证据编号必须能追溯原始笔记。分析完成后才允许保存报告。

### 8.2 分析报告

新增独立导航“分析报告”。当前路由中没有该项，需要新增路由和页面，不要复用永久左右分栏。

交互结构：

```text
全宽报告列表 → 独立报告详情页 → 点击证据编号 → 右侧来源证据抽屉
```

报告列表字段：报告名称及摘要、模板、关联项目、来源数量、生成时间、状态、操作。支持搜索、模板/项目筛选和排序。

详情页使用约 `920px` 的居中阅读栏，包含标题、元信息、核心结论、证据、风险、建议和数据说明。

注意：需要 Claude 先检查当前后端是否已经持久化可复用的分析记录。若现有 `NoteAnalysis` 足够，扩展列表/详情接口；若不足，再设计迁移，不得只存浏览器状态。

## 9. 推荐实施顺序

### 阶段 1：导航收敛（已完成）

- 已修改 `xhs.ts`，删除评论管理、关键词统计、情绪分析、酒店/品牌提及排名四个入口。
- 已删除四个占位页面、后端占位路由和“情感倾向”分析模板。
- 为“分析报告”建立路由占位。

### 阶段 2：笔记管理

- 把任务卡片改为可搜索、可筛选的 Table。
- 默认最近更新倒序。
- 把任务详情中的笔记卡片网格改为 Table。
- 接入时间分组和批量选择。
- 保留现有笔记详情 Modal。

### 阶段 3：采集任务

- 重构弹窗布局。
- 只开放后端已支持的筛选项。
- 对缺失的名称、互动范围字段先确认后端方案。

### 阶段 4：追踪任务

- 列表化布局。
- 接入启停、立即运行、编辑和删除。
- 明确推导字段与真实后端字段。

### 阶段 5：分析报告

- 设计持久化模型/接口。
- 实现全宽列表、详情页和证据抽屉。
- 接入 AI 分析保存流程。

## 10. 数据排序与分页要求

- 任务列表排序应优先由后端完成：`updated_at DESC, id DESC`。
- 笔记排序应优先由后端完成：`upload_time DESC, note_id DESC`。
- 数据量可能达到数千条，生产实现必须支持服务端分页，禁止一次加载全部数据再前端分页。
- 搜索建议使用 `query` 参数，状态使用 `status`，分页使用 `page/page_size`。
- 当前 `/api/xhs/notes` 和 `/api/xhs/notes/{task_id}` 未暴露分页/搜索参数；建议新增且保持旧调用兼容。

推荐接口形式：

```http
GET /api/xhs/notes?query=二手家具&status=success&page=1&page_size=20&sort=updated_desc
GET /api/xhs/notes/{task_id}?query=沙发&note_type=normal&date_range=30d&page=1&page_size=50&sort=published_desc
```

推荐分页响应：

```json
{
  "items": [],
  "total": 200,
  "page": 1,
  "page_size": 50
}
```

如改变响应结构，需要同步修改 `XhsApi` 类型与所有调用方，或提供兼容接口版本。

## 11. 响应式与可访问性

- 小于 `1100px`：隐藏次要列，保留主题、状态、数量和操作。
- 小于 `760px`：表格可切换为紧凑列表；弹窗单列；分析篮改抽屉。
- 可点击行支持 Enter。
- 所有图标按钮必须有 `aria-label` 或 Tooltip。
- 开关必须展示文字状态，不只展示颜色。
- 键盘焦点必须清晰可见。
- 空状态、加载态、失败态和无搜索结果状态必须分别实现。

## 12. 验收清单

### 导航

- [ ] 小红书导航只显示五个目标入口。
- [ ] 旧页面代码和后端能力未被误删。

### 笔记管理

- [ ] 默认展示采集任务列表而非全部笔记。
- [ ] 任务列表为 Table，默认最近更新优先。
- [ ] 主题名和关键词搜索有效。
- [ ] 状态筛选有效。
- [ ] 点击任务只加载该 `task_id` 的笔记。
- [ ] 笔记 Table 按时间倒序。
- [ ] 最近一周、最近一个月、最近半年分组边界正确。
- [ ] 超过半年的笔记没有丢失。
- [ ] 批量选择和加入 AI 分析可用。
- [ ] 笔记详情仍可查看图片、视频和原文。

### 采集任务

- [ ] 弹窗层级和字段分组符合文档。
- [ ] 不展示假筛选项。
- [ ] 校验、loading、成功和失败反馈完整。

### 追踪任务

- [ ] 使用单列紧凑列表。
- [ ] 状态、执行计划、启停和立即运行正确。
- [ ] 缺失字段没有用假数据代替。

### 分析报告

- [ ] 报告列表、详情、证据抽屉均为独立可访问状态。
- [ ] 报告数据持久化，不只保存在前端。

### 工程质量

- [ ] TypeScript 类型检查通过。
- [ ] 前端 lint/测试通过。
- [ ] 后端测试通过。
- [ ] 浏览器控制台无错误。
- [ ] 相关页面完成桌面与窄屏验证。

## 13. 已确认的原型资料

临时可交互原型：

- `/private/tmp/workbench-xhs-static-demo/index.html`
- 本地预览：`http://127.0.0.1:8765/`

关键截图：

- `/private/tmp/workbench-xhs-static-demo/note-task-list-final.png`
- `/private/tmp/workbench-xhs-static-demo/note-task-table-grouped.png`
- `/private/tmp/workbench-xhs-static-demo/collection-filters-final.png`
- `/private/tmp/workbench-xhs-static-demo/tracking-list-final.png`
- `/private/tmp/workbench-xhs-static-demo/report-list-final.png`
- `/private/tmp/workbench-xhs-static-demo/report-detail-evidence.png`

注意：`/private/tmp` 内容可能被系统清理，Claude 应把本交接文档作为功能与交互依据；需要长期保存截图时，再将确认后的图片复制到仓库 `docs/assets/`。

## 14. 变更记录维护规则

Claude 每次完成一批实现后，在本文件末尾追加：

```text
### YYYY-MM-DD / 版本号
- 已实现：
- 变更文件：
- 接口变化：
- 验证结果：
- 未完成/风险：
```

禁止删除旧记录。

## 15. 交接记录

### 2026-08-02 / v1.0

- 已整理确认过的小红书五模块 UI 方向。
- 已将笔记管理的任务列表、关键词搜索、最近排序、笔记 Table 和时间分组写入实施要求。
- 已对照当前 Vue 页面、API 类型和 FastAPI 接口标出可复用能力与接口缺口。
- 当前仅新增本文档，未执行正式 UI 重构。

### 2026-08-02 / v1.1

- 已删除评论管理、关键词统计、情绪分析、酒店/品牌提及排名四个前端路由及占位页面。
- 已删除四个对应的 FastAPI `coming_soon` 占位接口和应用注册。
- 已删除 AI 分析的“情感倾向”预置模板。
- 已保留采集任务的评论抓取、评论预览与评论文件下载能力。
- 验证：前端 `@vben/web-antd` TypeScript 检查通过；后端修改文件 AST 语法检查通过；后端运行时路由检查因本机环境未安装 `fastapi` 未执行。

### 2026-08-02 / v1.2

- 已实现：阶段 2-5 全部落地。
  - 笔记管理：一级采集任务 Table（关键词/状态搜索、分页），二级任务笔记 Table（标题/正文/作者搜索、内容类型+时间范围筛选、时间分组按 7/30/180 天边界重新校正、批量选择+加入 AI 分析、导出、笔记详情 Modal 保留）。
  - 采集任务：新建任务改为 720px 弹窗，按基础信息/采集范围/评论采集分组，加“常用关键词”快捷标签（取自真实历史任务），点赞/收藏范围筛选因后端不支持未展示（不做假控件），关闭有未保存内容二次确认。
  - 追踪任务：单列紧凑 Table，新增真实的 `total_hit_count`（命中记录 COUNT）和 `next_run_at`（读 APScheduler job.next_run_time），未注册/禁用时为 null，不做前端推算假值。
  - 分析报告（新导航项）：新增 `XhsAnalysisReport` 持久化模型（快照式，不受之后项目笔记增删/原分析删除影响），AI 分析页成功结果加“保存为报告”入口，新增全宽报告列表页（搜索/项目筛选/排序/分页）和独立详情页（920px 阅读栏 + 正文引用编号可点击 + 右侧证据抽屉），项目删除时级联清理其报告。
- 变更文件：
  - 后端：`app/xhs/services/tasks.py`（notes 分页/搜索）、`app/xhs/controllers/notes.py`、`app/xhs/services/tracking.py`+`controllers/tracking.py`（真实字段）、`app/xhs/models/xhs_analysis_report.py`（新增）+`models/__init__.py`、`app/xhs/services/report_service.py`（新增）、`app/xhs/services/analysis_project.py`（级联删除）、`app/xhs/services/note_analysis.py`（新增 `get_analysis`）、`app/xhs/controllers/analysis.py`（报告路由）、`app/xhs/schemas/xhs.py`（`SaveReportIn`）。
  - 前端：`views/xhs/notes/index.vue`（重写）、`views/xhs/collect-tasks/index.vue`（弹窗重排）、`views/xhs/tracking/index.vue`（重写为 Table）、`views/xhs/ai-analysis/index.vue`（加保存报告入口）、`views/xhs/analysis-reports/{index,detail}.vue`（新增）、`api/core/xhs.ts`（分页类型+报告 API）、`utils/note-grouping.ts`（分组边界改为 7/30/180 天）、`router/routes/modules/xhs.ts`（新增分析报告路由）。
- 接口变化：
  - `GET /api/xhs/notes`、`GET /api/xhs/notes/{task_id}` 响应结构从裸数组/`PreviewResult` 改为 `{items,total,page,page_size}` 分页信封，并新增 `query/status/page/page_size`（前者）和 `query/note_type/date_range/page/page_size`（后者）查询参数；`note_type` 取值是笔记详情里的真实中文值（图集/视频），不是采集表单里 0/1/2 的枚举。
  - `TrackingTask` 序列化新增 `total_hit_count`、`next_run_at`（均为真实值，非推导/伪造）。
  - 新增 `POST /api/xhs/analysis-projects/{project_id}/analyses/{analysis_id}/report`、`GET /api/xhs/reports`、`GET/DELETE /api/xhs/reports/{report_id}`。
  - 笔记管理首页排序目前仍用 `created_at`（Task 表无 `updated_at` 字段），前端标注为“创建时间”，未伪装成更新时间；文档 10 节建议的 `updated_at DESC` 排序留待后续如确有需要再加字段。
  - 报告正文引用编号 `[N]` 对应报告生成时项目笔记的展示顺序快照（与 AI 分析页 `noteIndexOf` 现有口径一致），而非该次分析实际用到的笔记子集精确复原——历史分析记录未落库当时选中的笔记子集，这是延续现有约定的已知近似，非本次引入的新问题。
- 验证结果：
  - 后端：新增/修改的全部文件 AST 语法检查通过；本机启动 `uvicorn` 无报错，`openapi.json` 确认全部新路由正确注册；对 notes/tracking/reports 各接口用真实登录态做了 curl 验证，包括用临时构造的真实任务+笔记+分析数据跑通“保存报告→列表→详情→项目删除级联”全链路（验证后已清理测试数据，数据库无残留）。
  - 前端：`vue-tsc --noEmit --skipLibCheck` 全量通过；`eslint` 对改动文件通过（仅 1 处既有代码库同款写法的 `v-html` warning，非 error）；Vite 开发服务器可正常编译全部改动/新增的 `.vue` 文件。
  - 浏览器可视化验证：本机 Claude in Chrome 扩展未连接，未能完成真实浏览器走查，此项验收未覆盖，如需请用户自行在浏览器中过一遍关键路径。
- 未完成/风险：
  - 未新增 `Task.updated_at` 字段（文档 10 节建议项），笔记管理任务列表排序暂用创建时间顶替，已在代码注释和前端 Tooltip 中明确标注。
  - 报告引用编号的笔记子集近似问题（见上），如需精确复现历史分析用到的笔记子集，需要给 `XhsNoteAnalysis` 补一个 `note_ids_json` 字段，这次未做（超出本轮范围，未来如有需要可再补）。
  - 互动量筛选（点赞/收藏范围）、笔记打标签，前端均未提供假交互，按钮/输入框直接不展示或禁用+提示，等后端/爬虫具备能力后再接入。
  - 未做真实浏览器可视化走查，仅通过类型检查/lint/Vite 编译/后端 curl 集成测试验证。

### 2026-08-02 / v1.3

- 已实现：v1.2 之后针对文档第 8 节（AI 分析与分析报告）范围内的一批用户反馈驱动的改进：
  - AI 分析页布局重构：项目列表不再常驻左栏，未选中项目时作为主内容全宽展示；选中后改成对话区（更宽）+ 来源笔记两栏，项目列表挪进按需弹出的抽屉（"切换项目"按钮），不再挤占对话区宽度。
  - "整理为报告"（原"导出报告"，之前只是本地下载 markdown，不落库）：改成弹窗勾选要包含哪几轮问答，支持"保存为新报告"或"追加到已有报告"两种方式，都会真正持久化进 `分析报告`。新增后端 `save_combined_report`/`append_to_report`，`POST /api/xhs/analysis-projects/{id}/report`、`PUT /api/xhs/reports/{id}/append`。
  - 分析报告详情页重做成博客式阅读体验：自动从正文 `##/###/####` 标题提取目录、滚动高亮当前章节、补全标题/列表/引用块/分割线等 markdown 排版样式（之前只有 `<p>` 有样式）、预估阅读时长。
  - 排查并修复了两个跟本文档范围强相关的真实 bug：① AI 分析报错时只显示 `HTTP error! status: 400`（根因是共享 SSE 客户端丢弃了后端返回的具体错误信息，已在 `packages/effects/request` 修好，两个模块都受益）；② Gemini 请求 60 秒读超时（大上下文+思考模式导致，已把超时放宽到 `(10, 300)`，并修了 nginx 反向代理的 `proxy_read_timeout`/`proxy_buffering`，否则生产环境这一层会先掐断连接）。
  - 顺带排查修复了笔记管理二级列表"鼠标滚轮无法下滑，只能点下一页"的 CSS bug（flex 容器里 `overflow-hidden` 触发的自动最小尺寸问题），追踪任务、分析报告列表当时也用了同样的写法，一并修了。
- 变更文件：
  - 后端：`app/xhs/schemas/xhs.py`（`SaveCombinedReportIn`/`AppendReportIn`）、`app/xhs/services/report_service.py`（`save_combined_report`/`append_to_report`/共用的笔记快照小函数）、`app/xhs/controllers/analysis.py`（两个新路由）、`app/common/services/gemini_client.py`（超时调整）。
  - 前端：`views/xhs/ai-analysis/index.vue`（布局重构+整理报告弹窗）、`views/xhs/analysis-reports/detail.vue`（博客式重做）、`views/xhs/notes/index.vue`+`views/xhs/tracking/index.vue`+`views/xhs/analysis-reports/index.vue`（滚动 bug 修复）、`api/core/xhs.ts`（新增两个 API 函数）、`packages/effects/request/src/request-client/modules/sse.ts`（错误信息透传，共享包，chat 模块也受益）、`frontend/nginx.conf`（SSE 反代超时/缓冲）。
- 接口变化：
  - 新增 `POST /api/xhs/analysis-projects/{project_id}/report`（body 增加必填的 `analysis_ids`，与单条保存的 `SaveReportIn` 区分开）、`PUT /api/xhs/reports/{report_id}/append`。
  - 这批改动都不影响文档正文列出的核心接口（notes/collect-tasks/tracking-tasks），是在文档范围之上的自然延伸，不是对文档内容的偏离。
- 验证结果：
  - 后端：新增两个接口用真实项目数据（普吉岛游玩攻略项目，288 篇笔记）验证过选择性保存和追加都能正确工作（追加后正文两段内容都在，来源证据笔记按项目当前顺序重新生成）；超时改动验证了 3 层里 gemini_client 超时元组、nginx 配置语法。
  - 前端：改动或新增的文件全部过 `vue-tsc --noEmit --skipLibCheck` 和 `eslint`（除既有的 1 处 v-html warning 外无新增问题）；Vite 开发服务器编译无误。
  - 本次（2026-08-02 收尾核对）：重新跑了一遍导航结构核对（5 个入口 + 1 个隐藏详情路由，和文档第 2 节完全一致）、全量 `vue-tsc` 类型检查、`eslint`、后端全部 xhs 接口 curl 健康检查（notes/collect-tasks/tracking-tasks/analysis-projects/reports 均 200，已删除的旧占位接口确认 404），均通过。
- 未完成/风险：
  - v1.2 里记录的三项（`Task.updated_at` 未加、报告引用编号笔记子集近似、互动量筛选未接入）现状不变。
  - 本次收尾核对同样没有做真实浏览器可视化走查（Claude in Chrome 扩展本机多次尝试均未能稳定连接/响应），后续如果环境允许建议补一次人工或自动化的 UI 走查。
