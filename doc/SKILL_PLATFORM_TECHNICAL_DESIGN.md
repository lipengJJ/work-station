# 统一工作台 Skill 平台技术设计

> 文档状态：Draft v1.1（已按当前代码库校准）  
> 更新时间：2026-08-03  
> 适用项目：`/Users/lipeng01/vscode/workbench`  
> 目标读者：产品、UI、前端、后端及负责实现的 AI 编程助手

## 1. 背景与目标

工作台需要把 Skill 从“服务器目录中的提示词文件”升级为可管理、可调用、可审计的能力资产。用户应当能够导入和查看 Skill，并在股票、小红书、旅行等分析场景中选择 Skill，让 AI 按 Skill 中预先定义的流程、规则和模板完成分析。

第一阶段目标：

1. 建立统一的 Skill 管理中心，支持导入、查看、启用、禁用和删除。
2. 建立统一的 Skill 运行服务，负责安全加载 Skill 并组合 AI 请求。
3. 在工作台的分析入口提供 Skill 选择器。
4. 支持 Skill 提供输入表单定义、执行规则、参考资料和输出模板。
5. 复用现有 Gemini REST 客户端与 API 配置，不重复建设模型接入。
6. 保存每次执行时实际使用的 Skill 版本、输入、结果和引用来源。

第一阶段不包含：

- 在线 Skill 商店和自动搜索社区 Skill。
- 自动执行 Skill 中的任意脚本。
- MCP Server 的安装与运行。
- 多 Skill 自动规划和复杂 Agent 编排。
- 自动发布或覆盖已有 Skill。

## 2. 核心概念

### 2.1 Skill

一个 Skill 是独立目录，最低要求包含 `SKILL.md`：

```text
skill-name/
├── SKILL.md                  # 必需：名称、触发描述和执行规则
├── agents/
│   └── openai.yaml           # 可选：展示名称、简介和默认提示
├── references/               # 可选：按需加载的参考规则
├── assets/                   # 可选：输出模板或静态资源
└── scripts/                  # 后续版本支持，第一阶段禁止执行
```

### 2.2 Skill 定义与分析模板

两者不是同一个概念：

- Skill 定义“AI 应当如何工作”，例如核验来源、安排路线、计算预算和输出检查。
- 分析模板定义“本次执行需要收集什么输入、使用什么默认提示、输出什么结构”。

一个 Skill 可以有多个模板。例如 `gemini-travel-planner` 可以提供：

- 城市周末游
- 多城市自由行
- 亲子旅行
- 美食主题旅行
- 机酒预算比较

### 2.3 Skill 执行记录

每次 AI 分析都必须记录 Skill ID、版本快照和输入。即使 Skill 后续更新，历史报告仍能解释当时使用了什么规则。

## 3. 用户流程

### 3.1 导入 Skill

```text
进入 Skill 管理
→ 点击“导入 Skill”
→ 上传 ZIP 或选择服务器目录
→ 后端解压到临时目录
→ 校验结构、名称和文件安全
→ 展示名称、说明、文件清单和风险
→ 用户确认
→ 写入正式目录和数据库
→ 默认启用
```

第一阶段推荐只支持 ZIP 上传和已有本地目录登记。GitHub URL 导入放到第二阶段。

### 3.2 使用 Skill 进行分析

```text
进入 AI 分析
→ 选择业务场景
→ 选择已启用 Skill
→ 选择模板
→ 填写动态表单
→ 预览将使用的数据和能力
→ 发起分析
→ 后端构建 System Instruction
→ Gemini 生成结果
→ 前端流式展示
→ 保存报告及 Skill 版本快照
```

### 3.3 旅行攻略示例

用户选择：

```text
Skill：Gemini 旅行攻略规划师
模板：多城市自由行
目的地：大阪、京都、奈良
日期：2026-10-02 至 2026-10-10
出发地：新加坡
人数：2 名成人
预算：5000 SGD
偏好：美食、古建筑、摄影
节奏：均衡
```

系统加载：

1. `SKILL.md` 核心流程。
2. `references/source-policy.md` 信息核验规则。
3. `assets/itinerary-template.md` 输出模板。
4. 用户输入和业务数据。
5. Gemini Google Search 等允许的工具配置。

最终生成攻略报告并保存为一条分析执行记录。

## 4. 总体架构

```text
┌──────────────────────────── 前端 Vue ────────────────────────────┐
│ Skill 管理 │ Skill 详情 │ 导入向导 │ AI 分析 │ 报告详情          │
└───────────────────────────────┬───────────────────────────────────┘
                                │ REST / SSE
┌──────────────────────────── FastAPI ──────────────────────────────┐
│ Skill Controller              │ Analysis Controller               │
│ - 列表/详情/导入/启停          │ - 创建执行/流式输出/取消/历史      │
├───────────────────────────────┴───────────────────────────────────┤
│ Skill Registry │ Skill Validator │ Prompt Builder │ AI Gateway    │
│ 文件与元数据    │ 结构与安全检查   │ 组合执行上下文   │ Gemini REST  │
├───────────────────────────────────────────────────────────────────┤
│ SQLAlchemy 数据库                     │ skills/ 文件存储            │
└───────────────────────────────────────────────────────────────────┘
```

设计原则：

- 控制面与执行面分离：Skill 管理负责资产；AI 分析负责执行。
- 数据库保存可查询元数据，文件系统保存 Skill 原始内容。
- AI 调用不能直接接受前端传入的文件路径或 system prompt。
- 所有业务模块统一调用 `SkillRuntimeService`，不各自拼接 Skill。
- 第一阶段单 Skill 执行；接口结构预留多 Skill 能力。

## 5. 模块拆分

## 5.1 模块 A：Skill 文件规范

### 必需校验

- 目录名与 `SKILL.md` 的 `name` 完全一致。
- 名称只能包含小写字母、数字和短横线，长度 1–64。
- `SKILL.md` 必须包含 YAML frontmatter 的 `name` 和 `description`。
- 禁止绝对路径、`..` 路径逃逸和符号链接。
- 解压后的单个文件和总体积必须受限。
- 第一阶段拒绝二进制可执行文件。
- `scripts/` 允许展示但禁止执行，并在导入时标记风险。

### 扩展清单

建议增加工作台自己的可选文件：

```text
workbench.yaml
```

示例：

```yaml
version: "1.0"
category: "travel"
tags:
  - "旅行"
  - "攻略"
  - "预算"
runtime:
  preferred_provider: "gemini"
  recommended_model: "gemini-3.6-flash"
  tools:
    google_search: true
    url_context: true
inputs:
  schema: "./assets/input-schema.json"
templates:
  - id: "multi-city"
    name: "多城市自由行"
    prompt: "./assets/prompts/multi-city.md"
    output: "./assets/itinerary-template.md"
```

没有 `workbench.yaml` 的通用 Skill 仍然可以导入，只是使用通用文本输入界面。

## 5.2 模块 B：Skill 管理后端

建议新增目录：

```text
backend/app/skills/
├── controllers/
│   └── skills.py
├── models/
│   ├── skill.py
│   ├── skill_version.py
│   └── skill_template.py
├── schemas/
│   └── skill.py
└── services/
    ├── registry_service.py
    ├── import_service.py
    ├── validator_service.py
    ├── manifest_service.py
    └── storage_service.py
```

职责：

- `registry_service`：列表、搜索、详情、启停和状态汇总。
- `import_service`：上传、临时解压、确认导入和失败回滚。
- `validator_service`：格式、安全、大小和重复名称检查。
- `manifest_service`：解析 `SKILL.md`、`openai.yaml` 和 `workbench.yaml`。
- `storage_service`：安全读写 Skill 文件、计算摘要和管理版本目录。

正式存储建议：

```text
workbench/storage/skills/<skill-name>/<version>/
```

项目当前的 `workbench/skills/` 可作为开发期内置 Skill 来源；生产运行目录与源码目录分开，避免上传内容进入 Git 工作区。

## 5.3 模块 C：Skill 管理前端

左侧增加一级菜单：

```text
Skill 管理
```

建议页面：

```text
frontend/apps/web-antd/src/views/skills/
├── index.vue                 # 列表与搜索
├── detail.vue                # Skill 详情
├── import.vue                # 导入向导或抽屉
└── components/
    ├── SkillCard.vue
    ├── SkillDetailDrawer.vue
    ├── SkillImportWizard.vue
    ├── SkillRiskPanel.vue
    └── SkillFileTree.vue
```

列表字段：

- 图标、展示名称和 Skill ID
- 分类和标签
- 版本与更新时间
- 来源：内置、本地上传、GitHub（后续）
- 启用状态
- 风险状态
- 被调用次数和最后调用时间

详情页分区：

- 概览
- 使用方式和默认提示
- 分析模板
- 文件清单与预览
- 所需工具和权限
- 版本与执行历史

操作：查看、启用/禁用、导出、删除。内置 Skill 默认禁止删除，只允许禁用。

## 5.4 模块 D：Skill Runtime 运行服务

建议放到公共服务层：

```text
backend/app/common/services/skill_runtime/
├── loader.py
├── prompt_builder.py
├── context_resolver.py
├── permission_resolver.py
└── runtime_service.py
```

### Loader

根据数据库中登记的受控路径加载 Skill，禁止接收任意绝对路径。加载后返回标准对象：

```python
LoadedSkill(
    id="gemini-travel-planner",
    version="1.0.0",
    instruction="...",
    references=[...],
    templates=[...],
    tool_policy={...},
    content_hash="sha256:...",
)
```

### Context Resolver

决定本次需要加载哪些内容：

- 始终加载 `SKILL.md`。
- 只加载模板声明或 Skill 明确要求的 references。
- 只加载用户选中的输出模板。
- 用户数据、采集笔记和股票数据作为业务上下文单独注入。
- 对总输入大小设上限，超限时摘要或拒绝，不能静默截断关键规则。

### Prompt Builder

统一构建请求，不允许各业务控制器自行拼接：

```text
[平台级安全与输出规则]
[Skill 核心指令]
[选中的参考规则]
[选中的模板]
[业务上下文及数据来源]
[用户本次输入]
```

优先级必须固定：平台安全策略 > Skill > 模板 > 用户数据与请求。

### Permission Resolver

将 Skill 声明转换为实际 Gemini 工具：

```text
google_search=true  → tools.googleSearch
url_context=true    → tools.urlContext
structured_output   → generationConfig/response schema
```

Skill 只能请求能力，平台白名单决定最终是否允许。前端不能通过参数绕过平台策略。

## 5.5 模块 E：统一 AI Gateway

现有 Gemini 代码位于：

```text
backend/app/common/services/gemini_client.py
backend/app/common/services/gemini_config.py
```

建议逐步抽象为：

```text
backend/app/common/services/ai_gateway/
├── base.py
├── gemini_provider.py
├── schemas.py
└── service.py
```

统一请求对象：

```python
AIRequest(
    provider="gemini",
    model="gemini-3.6-flash",
    system_instruction="...",
    messages=[...],
    tools=["google_search"],
    output_schema=None,
    stream=True,
)
```

第一阶段仍可保留现有 REST 实现，但 `stream_chat` 需要支持：

- `system_instruction`
- `tools`
- `output_schema`
- `request_id`
- 返回 usage、引用元数据和结束原因，而不只返回文本增量

流式事件建议统一为：

```text
event: started
event: delta
event: citation
event: usage
event: completed
event: error
```

## 5.6 模块 F：AI 分析与模板执行

建议新增通用分析模块，而不是把 Skill 执行限制在小红书或股票目录：

```text
backend/app/analysis/
├── controllers/analyses.py
├── models/analysis_run.py
├── models/analysis_report.py
├── schemas/analysis.py
└── services/analysis_service.py
```

它负责：

1. 校验 Skill 和模板已启用。
2. 校验模板输入 Schema。
3. 获取业务数据引用。
4. 创建执行记录。
5. 调用 Skill Runtime 和 AI Gateway。
6. 持续写入状态、结果、引用和 token 使用量。
7. 生成并保存报告。

以后小红书 AI 分析和股票 AI 分析逐步迁移到这一通用服务，但第一阶段不要求一次性重构所有旧逻辑。

## 6. 数据模型

### 6.1 skills

| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint | 主键 |
| skill_key | varchar(64) unique | 例如 `gemini-travel-planner` |
| display_name | varchar(128) | 展示名称 |
| description | text | 触发描述 |
| category | varchar(64) | 分类 |
| source_type | varchar(32) | builtin/upload/local/github |
| source_uri | text nullable | 原始来源 |
| current_version_id | bigint | 当前版本 |
| enabled | boolean | 是否可执行 |
| risk_level | varchar(16) | low/medium/high/blocked |
| created_by | bigint | 导入用户 |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 更新时间 |

### 6.2 skill_versions

| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint | 主键 |
| skill_id | bigint | Skill |
| version | varchar(64) | 版本号 |
| storage_path | text | 受控存储路径 |
| content_hash | varchar(80) | 内容摘要 |
| manifest_json | json/text | 解析后的清单 |
| validation_json | json/text | 校验与风险结果 |
| created_at | datetime | 导入时间 |

### 6.3 skill_templates

| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint | 主键 |
| skill_version_id | bigint | 所属版本 |
| template_key | varchar(64) | 模板 ID |
| name | varchar(128) | 模板名称 |
| description | text | 使用说明 |
| prompt_path | text | 提示模板相对路径 |
| output_template_path | text | 输出模板相对路径 |
| input_schema_json | json/text | 动态表单 Schema |
| enabled | boolean | 是否启用 |

### 6.4 analysis_runs

| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint | 主键 |
| request_id | varchar(64) unique | 请求追踪 ID |
| user_id | bigint | 发起用户 |
| skill_id | bigint | Skill |
| skill_version_id | bigint | 固定版本 |
| template_id | bigint nullable | 选中模板 |
| provider | varchar(32) | gemini |
| model | varchar(128) | 实际模型 |
| status | varchar(32) | queued/running/completed/failed/cancelled |
| input_json | json/text | 表单输入 |
| context_refs_json | json/text | 业务数据引用 |
| system_snapshot | text | 实际指令快照，可加密或限制管理员查看 |
| output_text | longtext | 最终输出 |
| output_json | json/text nullable | 结构化结果 |
| citations_json | json/text | 引用来源 |
| usage_json | json/text | token 与费用数据 |
| error_message | text nullable | 失败原因 |
| created_at | datetime | 创建时间 |
| finished_at | datetime nullable | 完成时间 |

## 7. API 设计

### 7.1 Skill 管理

```text
GET    /api/skills
GET    /api/skills/{skill_key}
POST   /api/skills/import/validate
POST   /api/skills/import/confirm
PATCH  /api/skills/{skill_key}
POST   /api/skills/{skill_key}/enable
POST   /api/skills/{skill_key}/disable
DELETE /api/skills/{skill_key}
GET    /api/skills/{skill_key}/versions
GET    /api/skills/{skill_key}/files
GET    /api/skills/{skill_key}/files/content?path=...
GET    /api/skills/{skill_key}/templates
```

导入采用两步制：`validate` 只写临时目录并返回风险报告；`confirm` 才正式安装。

### 7.2 AI 分析

```text
POST   /api/analyses
GET    /api/analyses/{run_id}
GET    /api/analyses/{run_id}/stream
POST   /api/analyses/{run_id}/cancel
GET    /api/analyses
DELETE /api/analyses/{run_id}
```

创建示例：

```json
{
  "skillKey": "gemini-travel-planner",
  "templateKey": "multi-city",
  "provider": "gemini",
  "model": "gemini-3.6-flash",
  "inputs": {
    "origin": "新加坡",
    "destinations": ["大阪", "京都", "奈良"],
    "startDate": "2026-10-02",
    "endDate": "2026-10-10",
    "adults": 2,
    "budget": 5000,
    "currency": "SGD",
    "preferences": ["美食", "古建筑", "摄影"],
    "pace": "balanced"
  },
  "contextRefs": [],
  "options": {
    "enableSearch": true,
    "thinkingEnabled": true,
    "outputFormat": "markdown"
  }
}
```

注意：`enableSearch` 只是用户偏好，最终值由 Skill 权限和平台白名单共同决定。

## 8. 前端交互设计

### 8.1 Skill 管理列表

顶部：搜索、分类、来源、状态筛选，以及“导入 Skill”按钮。

列表默认按最近更新排序。卡片展示名称、描述、标签、版本、风险和启用状态。点击打开详情抽屉，避免频繁跳转。

### 8.2 导入向导

分三步：

1. 上传：拖拽 ZIP，展示大小与文件数。
2. 校验：展示基础信息、缺失项、危险文件、权限和冲突。
3. 确认：选择覆盖策略；第一阶段已有同名 Skill 默认拒绝，要求以新版本导入。

### 8.3 AI 分析页

页面分为三栏或两栏：

- 左侧：Skill 与模板选择。
- 中间：模板动态表单、业务数据选择和补充要求。
- 右侧：本次将使用的工具、参考文件、预计输出和风险提示。

开始执行后切换为进度与结果页，展示阶段状态：准备上下文、查询资料、生成分析、整理报告。

### 8.4 报告详情

展示：报告正文、Skill 与版本、模板、用户输入、引用、生成时间、模型、token 使用量。支持复制、导出和基于原输入重新运行。

## 9. 安全设计

### 导入安全

- ZIP 解压必须防 Zip Slip。
- 禁止符号链接、硬链接和设备文件。
- 限制文件数量、单文件大小、压缩包大小和解压后总大小。
- 文件必须位于临时目录内，通过校验后原子移动到正式目录。
- 拒绝 `.env`、密钥、私钥和常见凭证文件。
- 第一阶段不执行任何导入包中的代码。

### 运行安全

- Skill Key 映射到数据库记录，不能由请求直接拼路径。
- 所有引用文件使用相对路径并再次做根目录校验。
- Skill 不能自行开启平台未允许的工具。
- System Instruction 不得包含数据库密码、API Key 和 Cookie。
- API Key 继续保存在系统配置服务中，调用 Gemini 时使用请求头，不进入 URL 和日志。
- 记录导入人、启停人、删除人和每次执行者。

### Prompt Injection 防护

- 把采集笔记和网页内容标记为“不可信数据”，不能覆盖系统和 Skill 规则。
- 社交媒体中出现的操作指令只作为被分析内容。
- URL Context 和 Google Search 结果不得触发服务器命令。
- 输出报告前执行格式与来源完整性检查。

## 10. 缓存与性能

- Skill 目录内容按 `skill_version_id + content_hash` 缓存。
- 不在每个流式分片重复读取文件。
- 模板列表和 Skill 列表使用短期缓存；导入、启停和更新时主动失效。
- 大型业务上下文先做筛选或摘要，保留原数据引用。
- SSE 断开后停止继续向客户端发送，但是否取消上游生成由执行状态决定。

## 11. 错误处理

统一错误码：

```text
SKILL_NOT_FOUND
SKILL_DISABLED
SKILL_INVALID
SKILL_IMPORT_CONFLICT
SKILL_FILE_BLOCKED
SKILL_TEMPLATE_NOT_FOUND
SKILL_INPUT_INVALID
AI_PROVIDER_NOT_CONFIGURED
AI_MODEL_UNAVAILABLE
AI_TOOL_NOT_ALLOWED
AI_REQUEST_FAILED
ANALYSIS_CANCELLED
```

前端显示用户可理解的信息，同时日志保留 request_id 和技术详情，禁止回传 API Key、完整 Cookie 或敏感请求头。

## 12. 分阶段实施计划

> 当前实现状态：阶段 1 和阶段 3 的核心后端能力已存在，包括 `app/skills`、`app/common/services/skill_runtime`、`app/common/services/ai_gateway`、`app/analysis`，前端已有 Skill 列表页。后续开发应补缺口，不得按下述原始计划从零重建。

### 阶段 1：Skill 只读登记与查看

后端：

- 新建 Skill 数据模型和迁移。
- 扫描 `workbench/skills/` 中的内置 Skill。
- 实现解析、校验、列表和详情接口。

前端：

- 增加 Skill 管理路由和菜单。
- 完成列表、搜索、详情和文件预览。

验收：用户可以看到 `gemini-travel-planner` 的名称、说明、模板和文件，但不能修改文件。

### 阶段 2：安全导入与生命周期管理

后端：

- 实现 ZIP 临时上传、校验、确认导入和回滚。
- 实现启用、禁用、删除和版本记录。
- 增加导入审计日志。

前端：

- 完成三步导入向导、风险报告和状态操作。

验收：合法 Skill 可导入；路径逃逸、符号链接、同名冲突和危险文件被阻止。

### 阶段 3：Skill Runtime 与 Gemini 接入

后端：

- 实现 Loader、Context Resolver、Prompt Builder 和 Permission Resolver。
- 扩展 `gemini_client.py` 支持 system instruction、Google Search、引用和统一 SSE 事件。
- 创建通用 Analysis Run 模型和接口。

验收：使用旅行 Skill 和表单输入可以生成攻略；Gemini 请求实际包含 Skill 内容，执行记录固定 Skill 版本。

### 阶段 4：模板化分析界面

前端：

- 根据输入 Schema 动态生成表单。
- 完成 Skill/模板选择器、运行进度、报告页和引用展示。

后端：

- 支持结构化 JSON 输出和模板渲染。

验收：旅行模板能形成按日行程、预算、预约、风险和来源等结构化内容。

### 阶段 5：业务模块复用

- 小红书 AI 分析接入通用 Skill Runtime。
- 股票基本面和研究报告接入通用 Skill Runtime。
- 支持从采集任务、笔记、股票数据中选择业务上下文。
- 对清洗数据使用 `AnalysisRun.context_refs_json` 保存 `clean_record_set` 引用，由上下文提供器查询有权限且通过质量门禁的数据；不要在运行表复制全部正文。
- 继续通过 `SkillRuntimeService.prepare_run(..., business_context=...)` 和现有 AI Gateway 执行，遵守 Context Resolver 的 60,000 字符上限。
- 逐步迁移旧的硬编码 Prompt，保留兼容适配层。

验收：同一个 Skill 可从不同业务入口调用，执行记录和报告体验保持一致。

### 阶段 6：扩展商店与高级能力

- GitHub 和公开 Skill 目录搜索。
- 更新检查、版本锁定和来源签名。
- MCP 依赖管理。
- 多 Skill 编排。
- 团队权限和审核发布流程。

此阶段必须在导入安全、权限模型和审计稳定后再开始。

## 13. 测试计划

### 单元测试

- YAML 解析和字段校验。
- 安全路径解析。
- ZIP Slip、符号链接和大小限制。
- Prompt 组合顺序。
- 工具权限交集计算。
- 输入 Schema 校验。
- Skill 内容哈希和缓存失效。

### 集成测试

- 导入 → 启用 → 运行 → 保存报告完整流程。
- Gemini SSE 正常、超时、限流和错误响应。
- Google Search 引用元数据保存。
- Skill 更新后历史执行仍指向旧版本。
- 用户取消和浏览器断线。

### 端到端测试

1. 导入旅行 Skill。
2. 在列表中查看详情。
3. 选择多城市模板。
4. 填写新加坡到日本关西行程。
5. 启动分析并观察流式进度。
6. 查看报告、预算和引用。
7. 禁用 Skill 后确认无法新建分析，但历史报告仍可查看。

## 14. Claude 实施约束

交给 Claude 开发时，应要求：

1. 严格按阶段提交，每个阶段单独可运行、可测试。
2. 先阅读项目现有 FastAPI、SQLAlchemy、Vue Router、API 请求和 SSE 实现风格。
3. 复用现有认证、数据库会话、错误处理和 API 配置。
4. 不在业务控制器复制 Skill 加载和 Prompt 拼装代码。
5. 不执行上传 Skill 中的脚本。
6. 不允许任意路径读取。
7. 每个阶段提供数据库迁移、测试和人工验收步骤。
8. 不顺带重构无关的小红书或股票模块。
9. 保留当前 Gemini 调用兼容性，再逐步迁移调用方。
10. 修改本设计范围时同步更新本文件的变更记录。

## 15. 变更记录

| 版本 | 日期 | 内容 |
|---|---|---|
| 1.0 | 2026-08-02 | 初始设计：Skill 管理、模板、运行时、Gemini 接入与分阶段实施方案 |
| 1.1 | 2026-08-03 | 补充当前实现基线及通用清洗数据通过 context_refs 接入 Skill Runtime 的方案 |
