# 统一工作台通用数据清洗与预处理模块设计

> 文档状态：Draft v1.2（已按当前代码库校准）  
> 更新时间：2026-08-03  
> 适用项目：`/Users/lipeng01/vscode/workbench`  
> 目标读者：产品、架构、前端、后端及负责实现的 AI 编程助手

## 1. 建设目标

建立一个与数据平台无关的通用数据清洗模块。上游可以来自小红书、淘宝、知乎、文件上传或其他采集服务；本模块从“已采集的原始数据”开始，完成规范化、过滤、去重、相关度判断、语义预处理、质量校验和清洗结果入库。

本模块最重要的交付物不是一段 AI 摘要，而是可追溯的清洗漏斗。例如某次任务采集 50 条数据，系统必须明确显示：

```text
原始输入                    50 条
├─ 格式无效                  2 条
├─ 完全重复                  5 条
├─ 低质量/正文不足           3 条
├─ 主题不相关               10 条
├─ 弱相关                    8 条
├─ 中等相关                  7 条
└─ 强相关并最终入库          15 条
```

任意统计都必须能够下钻到具体记录、处理步骤、命中规则、相关度分数和过滤原因。

模块必须满足：

1. 清洗核心不依赖平台；上游只需把数据转换成统一输入协议。
2. 不同平台原始字段可以映射到统一数据模型，同时完整保留原始数据。
3. 确定性清洗和 AI 语义处理分离，避免大模型替代可靠的数据处理代码。
4. 支持 GLM、Gemini 等模型提供商替换和分层使用。
5. 支持批量清洗、失败重试、断点续跑和历史数据重洗。
6. 每条数据可以追溯到来源、采集任务、清洗批次、步骤、规则版本和模型版本。
7. 支持平台级权限、敏感信息处理、审计和数据生命周期管理。
8. 为 Skill、AI 分析、搜索、报告和追踪任务提供统一数据接口。

## 2. 非目标

第一阶段不建设：

- 绕过登录、验证码、访问控制或平台反爬策略的能力。
- 任意第三方脚本直接在主服务进程执行。
- 用大模型完成精确数值计算、数据库 Join、排序或类型转换。
- 一次性重写现有全部小红书业务。

## 2.1 当前代码基线与对接结论

本文不是绿地方案。实现前必须以当前代码为基线，禁止重复建设已有模块。

| 当前能力 | 代码位置 | 对接结论 |
|---|---|---|
| FastAPI + SQLAlchemy 2.0 + SQLite | `backend/app/main.py`、`backend/app/core/database.py` | 新建 `app/data_cleaning` 领域；首期只新增表并在 `init_db()` 导入模型 |
| 统一任务中心 | `backend/app/common/models/task.py` | 清洗运行复用 `tasks`，`module='data_cleaning'`；清洗专属进度放扩展表 |
| Skill 注册、版本和模板 | `backend/app/skills/` | 不重新开发 Skill Registry，只消费现有 Skill/version/template |
| Skill Runtime | `backend/app/common/services/skill_runtime/` | 不自行拼 Prompt；通过 `prepare_run()` 传入经过预算控制的业务上下文 |
| 通用 AI Gateway | `backend/app/common/services/ai_gateway/` | Gemini 复用现有 Gateway；GLM 结构化处理复用 `glm_structured`，再逐步抽象 Provider |
| 通用分析运行 | `backend/app/analysis/` | `AnalysisRun.context_refs_json` 作为清洗数据集引用入口，不把大量正文直接塞进运行表 |
| 小红书原始/缓存数据 | `backend/app/xhs/models/xhs_note.py` | XHS Adapter 优先从 `XhsNote` 读取，不能以 `XhsTaskExtra.result_json` 作为唯一事实源 |
| 小红书清洗/结构化 | `note_preprocess.py`、`note_structurer.py` | 首期保留并桥接，随后把规则迁入通用步骤；禁止一次性删除 |
| 小红书旧统计与结构化表 | `XhsCollectStats`、`XhsNoteStructured` | 作为兼容投影双写，通用记录级账本成为新事实源 |

关键限制：当前项目没有 Alembic，`Base.metadata.create_all()` 只能创建新表，不能给已有表补列。阶段 1 不修改已有表；以后如需改表，必须先引入可回滚的版本化迁移机制。当前 SQLite 不适合多个 Worker 高频并发写账本，首期采用“并行计算、单写入器批量提交”。

### 小红书渐进式桥接

```text
XHS 搜索/详情抓取
  -> XhsNote（现有缓存/原始事实）
  -> XhsInputAdapter
  -> 通用 CleaningRun + 记录级 Cleaning Ledger
  -> CleanRecord / AnalysisResult
  -> 兼容投影：XhsCollectStats、XhsNoteStructured
  -> AnalysisRun.context_refs_json
  -> 现有 SkillRuntimeService + AI Gateway
```

现有低内容过滤发生在采集流程内部，部分记录不会进入 `result_json`。过渡期应在该决策点双写记录级过滤原因，或在过滤前保存本次抓取的 `note_id` 输入清单；不能事后仅从预览 JSON 重建漏斗。
- 为每个平台复制一套任务、数据表和分析页面。
- 在清洗模块内重新实现登录、分页和平台采集逻辑；采集属于上游模块。

## 3. 设计原则

### 3.1 平台与核心解耦

核心流程只认识统一清洗输入协议，不认识“小红书笔记”“淘宝商品”或“知乎回答”。平台差异由上游 Connector 和输入 Normalizer 处理。

### 3.2 原始数据不可丢失

所有记录必须保留原始响应或原始文件引用。统一字段用于查询和分析，不能替代原始证据。

### 3.3 分层处理

```text
确定性层：格式、类型、空值、哈希、去重、规则校验
语义层：分类、标签、实体、情绪、主题、摘要和风险识别
业务层：行业、旅行、品牌、股票等领域规则和 Skill
```

### 3.4 幂等与可重放

相同来源记录和相同处理版本重复执行时不应生成不可控的重复数据。原始数据可以使用新规则或新模型重新处理。

### 3.5 配置优先，代码扩展兜底

简单平台通过字段映射配置接入；涉及认证、分页、签名、文件下载等复杂逻辑时使用代码适配器。

## 4. 总体架构

```text
┌──────────────────────────── 上游输入层 ──────────────────────────┐
│ 小红书采集 │ 淘宝采集 │ 知乎采集 │ 文件上传 │ 其他数据服务      │
└───────────────────────────────┬─────────────────────────────────┘
                                │ RawEnvelope / 已采集记录
┌──────────────────────────── 清洗流水线 ──────────────────────────┐
│ Normalize → Validate → Deduplicate → Relevance → Quality → Save │
└───────────────────────────────┬─────────────────────────────────┘
                                │ CleanRecord + CleaningLedger
┌──────────────────────────── 存储与索引 ──────────────────────────┐
│ Raw Store │ Relational DB │ Search Index │ Vector Index（后续） │
└───────────────────────────────┬─────────────────────────────────┘
                                │
┌──────────────────────────── 消费与应用 ──────────────────────────┐
│ 笔记管理 │ 商品分析 │ 舆情分析 │ Skill 分析 │ 报告 │ 追踪任务 │
└─────────────────────────────────────────────────────────────────┘
```

核心思想：上游负责“可靠地拿到数据”，清洗模块负责“记录每一步怎样把数据变得可用”，业务模块只消费最终入库的干净数据。Connector 规范保留在本文档中作为上游边界，但不是清洗模块第一阶段的实现重点。

## 5. 模块拆分

## 5.1 Source Registry：数据源注册中心

统一登记每个数据源的能力和状态。

建议目录：

```text
backend/app/data_pipeline/sources/
├── registry.py
├── schemas.py
├── capability.py
└── builtins.py
```

数据源定义：

```python
SourceDefinition(
    key="xhs",
    display_name="小红书",
    connector="xhs_connector",
    supported_entities=["content", "comment", "author"],
    auth_modes=["cookie", "qr_login"],
    incremental=True,
    media_supported=True,
    rate_limit_profile="xhs_default",
)
```

注册中心提供：

- 数据源列表和能力查询。
- 启用、禁用和健康状态。
- 认证方式及所需配置 Schema。
- 支持的实体类型、过滤器和增量策略。
- 对应 Connector 版本。

禁止在核心任务代码中使用大量 `if source == "xhs"`。平台分支必须收敛到注册中心和适配器。

## 5.2 Connector SDK：采集连接器

每个平台实现相同接口：

```python
class SourceConnector(Protocol):
    def validate_config(self, config: dict) -> ValidationResult: ...
    def health_check(self, config: dict) -> HealthResult: ...
    def preview(self, request: CollectRequest) -> PreviewResult: ...
    def collect(self, context: CollectContext) -> Iterator[RawEnvelope]: ...
    def checkpoint(self) -> dict: ...
    def close(self) -> None: ...
```

建议目录：

```text
backend/app/data_pipeline/connectors/
├── base.py
├── manager.py
├── xhs/
│   ├── connector.py
│   ├── auth.py
│   ├── mapper.py
│   └── manifest.yaml
├── taobao/
│   ├── connector.py
│   ├── auth.py
│   ├── mapper.py
│   └── manifest.yaml
└── zhihu/
    ├── connector.py
    ├── auth.py
    ├── mapper.py
    └── manifest.yaml
```

Connector 负责：

- 认证和连接状态。
- 请求参数转换。
- 分页、游标和增量水位。
- 限流、退避和平台错误映射。
- 原始响应封装。
- 必要的媒体元数据发现。

Connector 不负责：

- 情绪、主题、实体等 AI 分析。
- 跨平台统一字段命名。
- 业务报告生成。
- 把平台特有字段强行丢弃。

### Connector Manifest

```yaml
key: "zhihu"
version: "1.0.0"
display_name: "知乎"
entities:
  - "content"
  - "comment"
  - "author"
auth:
  modes:
    - "cookie"
capabilities:
  incremental: true
  preview: true
  media: true
filters:
  - key: "keywords"
    type: "string_array"
    required: true
  - key: "published_after"
    type: "datetime"
  - key: "content_types"
    type: "enum_array"
    options: ["question", "answer", "article"]
```

前端使用 Manifest 动态生成不同数据源的采集表单，避免每新增平台都重写完整页面。

## 5.3 Raw Store：原始数据存储

Connector 每获取一条数据，先生成统一原始信封：

```json
{
  "source": "zhihu",
  "entityType": "content",
  "sourceId": "answer_123456",
  "sourceUrl": "https://www.zhihu.com/question/.../answer/...",
  "collectedAt": "2026-08-03T10:00:00+08:00",
  "publishedAt": "2026-08-01T15:20:00+08:00",
  "connectorVersion": "1.0.0",
  "taskId": 1001,
  "payload": {},
  "payloadHash": "sha256:...",
  "checkpoint": {}
}
```

原始数据建议采用“数据库元数据 + 文件/Object Storage 内容”的方式：

```text
storage/raw/<source>/<yyyy>/<mm>/<dd>/<task-id>/<record-id>.json
```

数据库只保存可查询元数据和 `payload_path`，避免超大 JSON 影响业务表性能。小规模部署可先把 JSON 保存到本地文件，接口保持未来可切换 S3/MinIO。

原始数据不可在预处理时覆盖；新响应生成新 revision 或更新原始版本记录。

## 5.4 Canonical Model：统一数据模型

不要设计一个包含所有平台字段的超宽表。采用“公共字段 + 类型扩展 + 平台扩展”模式。

### CanonicalRecord

```json
{
  "id": "uuid",
  "source": "xhs",
  "sourceId": "note_123",
  "entityType": "content",
  "contentType": "post",
  "title": "新加坡二手家具怎么买",
  "text": "...",
  "author": {
    "sourceId": "user_1",
    "name": "作者",
    "profileUrl": "..."
  },
  "publishedAt": "2026-08-01T10:00:00+08:00",
  "collectedAt": "2026-08-03T10:00:00+08:00",
  "url": "...",
  "language": "zh-CN",
  "metrics": {
    "likes": 100,
    "comments": 20,
    "favorites": 40,
    "shares": null,
    "views": null
  },
  "media": [],
  "tags": [],
  "location": null,
  "sourceFields": {},
  "rawRecordId": "uuid",
  "schemaVersion": "1.0"
}
```

### 统一实体类型

第一阶段定义：

- `content`：笔记、回答、文章、帖子、视频描述。
- `comment`：评论及回复。
- `author`：作者、店铺或机构账号。
- `product`：淘宝等平台商品。
- `topic`：话题、问题、标签或搜索主题。

公共接口允许通过 `entityType` 过滤。类型特有字段放入扩展结构：

```json
{
  "entityType": "product",
  "extensions": {
    "product": {
      "price": 199.0,
      "currency": "CNY",
      "shopName": "示例店铺",
      "salesCount": 1200,
      "skuCount": 5
    }
  }
}
```

平台原始字段放在 `sourceFields`，不能污染公共字段，也不能因统一模型不支持而丢失。

## 5.5 Normalizer：规范化处理

每个平台提供 Mapper，把 RawEnvelope 转换为 CanonicalRecord：

```python
class SourceNormalizer(Protocol):
    source: str
    version: str

    def normalize(self, raw: RawEnvelope) -> CanonicalRecord: ...
```

规范化包括：

- 字段命名和类型转换。
- 时间统一为带时区 ISO 8601。
- 数值和币种格式统一。
- HTML/富文本转换为保留结构的纯文本。
- 作者、指标、媒体和 URL 标准化。
- 内容类型映射。

Normalizer 必须是确定性代码，同样的输入和版本必须得到相同输出。

## 5.6 Deterministic Pipeline：规则预处理

建议将处理器设计成可组合步骤：

```python
class PipelineStep(Protocol):
    key: str
    version: str

    def supports(self, record: CanonicalRecord) -> bool: ...
    def process(self, record: CanonicalRecord, context: StepContext) -> StepResult: ...
```

默认步骤：

```text
schema_validate
→ text_sanitize
→ language_detect
→ metric_normalize
→ url_normalize
→ exact_deduplicate
→ rule_tagging
→ pii_detection
→ quality_score
```

每一步记录输入摘要、输出摘要、版本、耗时和状态。单步骤失败可按照策略跳过、重试或终止，不覆盖上一阶段结果。

### 5.6.1 Cleaning Ledger：清洗过程账本

清洗过程必须作为正式业务数据保存，不能只写日志。一次清洗生成一个 `cleaning_run`，每个步骤生成一条步骤统计，每条输入记录生成一组记录级处理结果。

批次级统计示例：

```json
{
  "runId": 3001,
  "source": "xhs",
  "topic": "新加坡二手家具",
  "inputCount": 50,
  "invalidCount": 2,
  "duplicateCount": 5,
  "lowQualityCount": 3,
  "irrelevantCount": 10,
  "weakRelevantCount": 8,
  "mediumRelevantCount": 7,
  "strongRelevantCount": 15,
  "savedCount": 15,
  "failedCount": 0
}
```

步骤级统计示例：

```text
步骤                    输入   通过   过滤   异常
格式与必填字段校验        50     48      2      0
完全去重                 48     43      5      0
内容质量过滤             43     40      3      0
主题相关度判断            40     30     10      0
强相关入库规则            30     15     15      0
数据库写入               15     15      0      0
```

记录级账本必须回答：

- 这条记录是否最终入库。
- 在哪个步骤被过滤。
- 命中了什么规则或模型判断。
- 清洗前后的字段发生了什么变化。
- 主题相关度等级和分数是多少。
- 使用了哪个规则、Prompt 和模型版本。
- 是否允许人工纠正和重新处理。

记录结果统一状态：

```text
pending       等待处理
passed        当前步骤通过
filtered      按规则过滤，不进入下一步
quarantined   数据异常，等待人工处理
failed        技术执行失败，可重试
saved         已写入清洗结果库
```

过滤是正常业务结果，不等同于失败。报表必须将 `filtered` 与 `failed` 分开统计。

### 5.6.2 Relevance Scoring：主题相关度

清洗任务必须绑定一个主题或研究目标，例如“新加坡二手家具”。相关度采用规则与模型结合：

1. 关键词和排除词产生基础分。
2. 标题、正文、标签和地点分别计算特征。
3. GLM 对语义相关性输出结构化分数、等级、理由和证据。
4. 规则引擎根据最终分数决定入库策略。

建议统一为 0–100 分：

| 等级 | 分数 | 默认处理 |
|---|---:|---|
| irrelevant | 0–29 | 过滤，但保留账本 |
| weak | 30–49 | 不进入主分析库，可在“弱相关”中查看 |
| medium | 50–74 | 入候选库，支持人工选择 |
| strong | 75–100 | 写入清洗结果库，供 Skill 和报告使用 |

阈值必须由清洗策略配置，不能硬编码在平台 Connector 中。模型输出示例：

```json
{
  "score": 88,
  "level": "strong",
  "reason": "正文讨论新加坡本地二手家具购买渠道和搬运成本",
  "evidence": ["在 Carousell 买了二手餐桌", "新加坡本地搬运费约为……"],
  "confidence": 0.91
}
```

证据片段必须能够在原文中定位；缺少证据的高分结果降级为待复核。

### 5.6.3 Clean Data Writer：清洗结果入库

最终通过入库策略的数据写入独立的 `clean_records` 表，而不是只更新原始表状态。写入使用数据库事务：

```text
写 clean_records
→ 写 cleaning_record_results 的 saved 状态
→ 更新 cleaning_runs.saved_count
→ 写 outbox event
→ 同一事务提交
```

`clean_records` 保存：

- 标准化后的核心字段。
- 来源、source_id、raw_record_id。
- 清洗批次和策略版本。
- 相关度等级、分数和证据。
- 质量分、主题、标签和实体。
- 清洗内容哈希和当前版本。
- 创建时间和最近重洗时间。

唯一约束建议为：

```text
(source, entity_type, source_id, cleaning_policy_version)
```

相同数据使用同一策略重跑时执行幂等 upsert；使用新策略重洗时保留新版本，并可指定哪一版是当前有效结果。

## 5.7 Deduplication：去重体系

采用三级策略：

### 一级：来源主键去重

唯一键建议为：

```text
(source, entity_type, source_id)
```

### 二级：内容哈希去重

对标准化标题、正文、作者和发布时间计算确定性哈希，用于发现同平台重复抓取和完全转载。

### 三级：语义近似去重

使用向量或模型判断近似内容，只标记 `duplicate_group_id` 和相似度，不直接删除。跨平台转载、改写和引用必须保留来源关系。

## 5.8 AI Enrichment：通用 AI 语义预处理

GLM 等模型只处理需要语义理解的任务：

- 内容分类和多标签。
- 主题、实体、品牌、地点和产品提取。
- 情绪、立场、购买意图和风险信号。
- 摘要、关键观点和证据片段。
- 广告推广、亲身体验和转载内容的可能性判断。
- 跨平台字段语义补全。

AI 处理不执行：

- 精确数值计算。
- 时间和币种格式转换。
- SQL 聚合和 Join。
- 唯一键判断。
- 无依据的缺失字段编造。

### Provider 抽象

```python
class SemanticModelProvider(Protocol):
    def enrich(
        self,
        task: SemanticTask,
        records: list[CanonicalRecord],
        output_schema: dict,
    ) -> SemanticResult: ...
```

实现：

```text
providers/glm.py
providers/gemini.py
providers/mock.py
```

路由建议：

- 大批量分类、标签和抽取：GLM Flash 系列。
- 高价值复杂分析：Gemini 或配置的高性能模型。
- 测试环境：Mock Provider，禁止测试依赖真实付费 API。

### 结构化输出

所有语义任务必须声明 JSON Schema。例如：

```json
{
  "category": "second_hand_furniture",
  "topics": ["搬家", "闲置交易"],
  "entities": [
    {
      "type": "location",
      "name": "新加坡"
    }
  ],
  "sentiment": "neutral",
  "commercialIntent": "low",
  "summary": "...",
  "evidence": ["..."],
  "confidence": 0.86
}
```

结果必须经过 Schema 校验。失败时最多重试指定次数，仍失败则进入死信队列，不能把无效文本写入正式字段。

## 5.9 Quality Gate：质量门禁

每条处理结果计算质量状态：

```text
valid       可供下游使用
warning     可使用，但存在缺失或低置信度
quarantined 数据异常，隔离等待处理
rejected    不满足基本规范
```

质量指标包括：

- 必需字段完整度。
- 正文有效长度。
- 发布时间合理性。
- 来源 URL 和主键完整性。
- AI 输出 Schema 合法性。
- 证据是否能在原文中定位。
- 模型置信度和规则冲突。
- 垃圾、广告、重复和敏感信息风险。

质量分不能只依赖大模型自报置信度，应结合确定性规则。

## 5.10 Pipeline Orchestrator：流水线编排

```python
PipelineDefinition(
    key="social-content-default",
    version="1.0.0",
    entity_types=["content"],
    steps=[
        "normalize",
        "validate",
        "clean",
        "deduplicate",
        "semantic_enrich",
        "quality_gate",
        "publish",
    ],
)
```

支持：

- 不同数据源复用相同流水线。
- 不同实体类型使用不同流水线。
- 任务级关闭某个可选步骤。
- 使用新 Pipeline 版本重放历史原始数据。
- 批次状态、步骤进度和失败原因查询。

第一阶段可使用数据库任务表和后台 Worker；高吞吐后再引入专用消息队列。接口不要绑定某一种队列实现。

## 5.11 Storage and Query：存储与查询

数据分层：

```text
Bronze：原始响应和原始文件
Silver：统一模型和确定性清洗结果
Gold：AI 标签、主题、指标和业务聚合
```

推荐：

- 关系数据库：任务、记录元数据、统一字段、处理状态。
- 文件/Object Storage：原始 JSON、图片、附件和大文本。
- 搜索引擎（后续）：全文搜索和复杂筛选。
- 向量索引（后续）：语义检索、近似去重和 RAG。

业务查询只能通过 Repository/Query Service，不直接依赖平台原始表。

## 5.12 Event Bus：下游分发

处理完成后发布领域事件：

```text
record.collected
record.normalized
record.enriched
record.quality_changed
batch.completed
batch.failed
```

下游可以订阅：

- 追踪任务检测新增内容。
- Skill 分析构建上下文。
- 报告模块更新统计。
- 搜索索引更新。
- 通知中心推送异常。

第一阶段事件可采用数据库 Outbox，确保业务写入和事件写入处于同一事务，后续再接消息队列。

## 6. 数据库设计

## 6.1 data_sources

| 字段 | 说明 |
|---|---|
| id | 主键 |
| source_key | xhs/taobao/zhihu |
| display_name | 展示名称 |
| connector_key | Connector 标识 |
| connector_version | 当前版本 |
| enabled | 是否启用 |
| capability_json | 能力清单 |
| config_schema_json | 配置 Schema |
| created_at/updated_at | 时间 |

## 6.2 source_credentials

| 字段 | 说明 |
|---|---|
| id | 主键 |
| source_id | 数据源 |
| account_label | 账号备注 |
| credential_type | cookie/oauth/api_key |
| encrypted_value | 加密凭证 |
| status | valid/expired/invalid |
| expires_at | 可空 |
| last_checked_at | 最近检查时间 |

凭证不得写入普通任务参数、日志或原始响应。

## 6.3 collection_jobs

| 字段 | 说明 |
|---|---|
| id | 主键 |
| source_id | 数据源 |
| name | 任务名称 |
| entity_types_json | 实体类型 |
| filters_json | 平台过滤条件 |
| pipeline_key | 处理流水线 |
| schedule | 定时配置 |
| enabled | 是否启用 |
| created_by | 创建人 |

## 6.4 collection_runs

| 字段 | 说明 |
|---|---|
| id | 主键 |
| job_id | 任务 |
| status | queued/running/completed/partial/failed/cancelled |
| checkpoint_json | 增量游标 |
| counters_json | 拉取、成功、重复、失败数量 |
| started_at/finished_at | 时间 |
| error_summary | 错误摘要 |

## 6.5 raw_records

| 字段 | 说明 |
|---|---|
| id | UUID |
| run_id | 采集批次 |
| source | 数据源 |
| entity_type | 实体类型 |
| source_id | 平台 ID |
| source_url | 原始链接 |
| payload_path | 原始文件路径 |
| payload_hash | 原始内容摘要 |
| published_at | 发布时间 |
| collected_at | 采集时间 |
| revision | 原始版本 |

## 6.6 canonical_records

保存统一公共字段、`source_fields_json`、`extensions_json`、当前状态、schema 版本和 raw_record_id。

唯一约束：

```text
(source, entity_type, source_id, schema_version)
```

## 6.7 cleaning_runs

一条记录代表一次清洗批次：

| 字段 | 说明 |
|---|---|
| id | 主键 |
| collection_run_id | 可空，上游采集批次 |
| source | 数据来源 |
| topic | 清洗主题/研究目标 |
| policy_key/policy_version | 清洗策略和版本 |
| pipeline_key/pipeline_version | 流水线和版本 |
| status | queued/running/completed/partial/failed/cancelled |
| input_count | 原始输入数 |
| invalid_count | 格式无效数 |
| duplicate_count | 重复数 |
| low_quality_count | 低质量数 |
| irrelevant_count | 不相关数 |
| weak_relevant_count | 弱相关数 |
| medium_relevant_count | 中相关数 |
| strong_relevant_count | 强相关数 |
| filtered_count | 总过滤数 |
| saved_count | 最终入库数 |
| failed_count | 技术失败数 |
| started_at/finished_at | 时间 |

计数字段可以冗余保存以提高看板性能，但必须由记录级结果聚合产生或定期校验，不能由前端自行计算后回写。

## 6.8 cleaning_step_stats

| 字段 | 说明 |
|---|---|
| id | 主键 |
| cleaning_run_id | 清洗批次 |
| step_key/step_version | 步骤和版本 |
| sequence | 执行顺序 |
| input_count | 输入数 |
| passed_count | 通过数 |
| filtered_count | 过滤数 |
| quarantined_count | 隔离数 |
| failed_count | 技术失败数 |
| duration_ms | 耗时 |
| status | 状态 |

## 6.9 cleaning_record_results

每条输入记录在每个清洗步骤产生一条结果：

| 字段 | 说明 |
|---|---|
| id | 主键 |
| cleaning_run_id | 清洗批次 |
| raw_record_id | 原始记录 |
| canonical_record_id | 标准记录，可空 |
| step_key/step_version | 清洗步骤 |
| status | passed/filtered/quarantined/failed/saved |
| reason_code | 稳定的过滤原因码 |
| reason_text | 用户可读原因 |
| score | 当前步骤分数，可空 |
| level | irrelevant/weak/medium/strong，可空 |
| evidence_json | 判断证据 |
| field_changes_json | 字段变更前后摘要 |
| provider/model/prompt_version | AI 判断信息，可空 |
| created_at | 时间 |

常用 `reason_code`：

```text
MISSING_REQUIRED_FIELD
EMPTY_CONTENT
CONTENT_TOO_SHORT
EXACT_DUPLICATE
SEMANTIC_DUPLICATE
IRRELEVANT_TOPIC
WEAK_RELEVANCE
LOW_QUALITY
INVALID_AI_OUTPUT
MANUAL_REJECTED
```

## 6.10 clean_records

保存最终可供查询、Skill 和报告消费的干净数据。核心字段包括：

```text
id
source/entity_type/source_id
raw_record_id/canonical_record_id
current_cleaning_run_id
cleaning_policy_key/cleaning_policy_version
title/text/author/published_at/url
metrics_json/media_json/source_fields_json/extensions_json
relevance_score/relevance_level/relevance_evidence_json
quality_score/topics_json/tags_json/entities_json
content_hash/version/is_current
created_at/updated_at
```

业务默认查询 `is_current=true` 的记录；历史版本用于审计和策略效果比较。

## 6.11 processing_runs

记录批次使用的 Pipeline、步骤版本、模型、Prompt 版本、输入输出摘要、状态、耗时和错误。它偏技术执行信息；`cleaning_runs` 和 `cleaning_record_results` 是用户可见的业务账本。

## 6.12 semantic_annotations

独立保存 AI 结果，不直接覆盖 CanonicalRecord：

```text
record_id
annotation_type
schema_version
provider
model
prompt_version
result_json
confidence
status
created_at
```

这样可以同时保留不同模型和不同版本的分析结果，便于比较和回滚。

## 6.13 outbox_events

保存待发布领域事件，Worker 成功投递后更新状态。

## 7. API 设计

### 数据源

```text
GET  /api/data-pipeline/sources
GET  /api/data-pipeline/sources/{source_key}
POST /api/data-pipeline/sources/{source_key}/validate-config
POST /api/data-pipeline/sources/{source_key}/health-check
```

### 采集任务

```text
GET    /api/data-pipeline/jobs
POST   /api/data-pipeline/jobs
GET    /api/data-pipeline/jobs/{job_id}
PATCH  /api/data-pipeline/jobs/{job_id}
DELETE /api/data-pipeline/jobs/{job_id}
POST   /api/data-pipeline/jobs/{job_id}/preview
POST   /api/data-pipeline/jobs/{job_id}/run
```

### 执行批次

```text
GET  /api/data-pipeline/runs
GET  /api/data-pipeline/runs/{run_id}
GET  /api/data-pipeline/runs/{run_id}/events
POST /api/data-pipeline/runs/{run_id}/cancel
POST /api/data-pipeline/runs/{run_id}/retry
```

### 统一数据查询

```text
GET  /api/data-pipeline/records
GET  /api/data-pipeline/records/{record_id}
GET  /api/data-pipeline/records/{record_id}/raw
GET  /api/data-pipeline/records/{record_id}/processing-history
POST /api/data-pipeline/records/reprocess
```

### 清洗任务与过程

```text
POST /api/data-cleaning/runs
GET  /api/data-cleaning/runs
GET  /api/data-cleaning/runs/{run_id}
GET  /api/data-cleaning/runs/{run_id}/funnel
GET  /api/data-cleaning/runs/{run_id}/steps
GET  /api/data-cleaning/runs/{run_id}/records
GET  /api/data-cleaning/runs/{run_id}/records/{raw_record_id}
POST /api/data-cleaning/runs/{run_id}/cancel
POST /api/data-cleaning/runs/{run_id}/retry-failed
POST /api/data-cleaning/runs/{run_id}/reprocess
POST /api/data-cleaning/records/{result_id}/review
GET  /api/data-cleaning/clean-records
GET  /api/data-cleaning/clean-records/{record_id}
```

漏斗响应示例：

```json
{
  "runId": 3001,
  "inputCount": 50,
  "savedCount": 15,
  "retentionRate": 0.3,
  "stages": [
    {"key": "schema_validate", "label": "格式校验", "input": 50, "passed": 48, "filtered": 2, "failed": 0},
    {"key": "exact_deduplicate", "label": "完全去重", "input": 48, "passed": 43, "filtered": 5, "failed": 0},
    {"key": "quality_filter", "label": "质量过滤", "input": 43, "passed": 40, "filtered": 3, "failed": 0},
    {"key": "relevance", "label": "主题相关度", "input": 40, "passed": 30, "filtered": 10, "failed": 0},
    {"key": "save", "label": "强相关入库", "input": 30, "passed": 15, "filtered": 15, "failed": 0}
  ],
  "relevance": {
    "irrelevant": 10,
    "weak": 8,
    "medium": 7,
    "strong": 15
  }
}
```

查询参数统一支持：

```text
source
entityType
contentType
jobId
publishedFrom/publishedTo
collectedFrom/collectedTo
qualityStatus
keyword
tags
sort
page/pageSize
```

平台特有过滤条件放在命名空间参数或 JSON filter 中，不能持续扩张公共查询接口。

## 8. 前端设计

左侧建议使用统一名称：

```text
数据中心
├── 数据源
├── 采集任务
├── 数据清洗
├── 执行记录
├── 数据资源库
└── 处理规则
```

### 数据源页

展示小红书、淘宝、知乎等卡片：连接状态、支持的数据类型、认证方式、最近检查和任务数。

### 新建采集任务

采用统一外壳和动态表单：

1. 选择数据源。
2. 选择实体类型。
3. 根据 Connector Manifest 渲染过滤条件。
4. 选择采集数量、时间范围和增量策略。
5. 选择预处理流水线和 AI 增强能力。
6. 预览匹配结果。
7. 保存或立即执行。

### 数据资源库

默认按主题/采集任务聚合，也支持切换到全部记录。统一表格展示标题、来源、实体类型、作者、发布时间、互动量、主题标签、质量状态和处理状态。

点击记录后显示：

- 标准化内容。
- 原始数据。
- AI 标签和证据。
- 处理流水线与版本。
- 来源链接和采集任务。

### 数据清洗页

数据清洗是本模块的主页面，默认展示最近清洗批次列表。点击批次进入详情，详情包含：

1. 顶部摘要：输入 50、过滤 35、强相关 15、最终入库 15、保留率 30%。
2. 清洗漏斗：展示每一步输入、通过、过滤、异常和留存率。
3. 相关度分布：不相关、弱相关、中相关、强相关数量及比例。
4. 过滤原因排行：重复、正文为空、主题不相关、低质量等。
5. 记录明细表：支持按步骤、状态、原因、相关度和来源筛选。
6. 数据下钻：查看原始数据、清洗后数据、字段变化、模型理由和证据。
7. 人工复核：可把误过滤数据改为保留，或把误保留数据改为过滤，并记录操作人和原因。

记录列表建议字段：

```text
标题/内容摘要
来源
清洗状态
停止步骤
过滤原因
相关度等级与分数
质量分
是否入库
处理时间
操作
```

过滤记录不会从系统删除，只是不进入 `clean_records` 主数据表。用户可以切换“全部、已入库、已过滤、待复核、失败”查看。

### 执行记录

显示批次进度、各步骤计数、失败原因、重试和下载错误记录。

## 9. 新增平台的标准流程

新增知乎或淘宝 Connector 时必须按以下步骤：

1. 创建 Connector Manifest。
2. 实现 `SourceConnector`。
3. 实现 `SourceNormalizer`。
4. 注册数据源定义。
5. 编写认证、分页、限流和断点测试。
6. 提供原始数据 Fixture，不依赖实时平台完成单元测试。
7. 验证映射到 CanonicalRecord 后不丢失关键字段。
8. 接入已有通用流水线；只有确有差异才增加平台专属 Step。
9. 前端确认 Manifest 可以动态生成任务表单。
10. 完成小批量灰度后再开放定时任务。

新增平台不应修改：

- 通用任务数据表结构。
- AI Provider 接口。
- 报告与 Skill Runtime 接口。
- 统一记录查询的核心逻辑。

## 10. 安全与合规

- 仅采集公开、用户授权或依法可访问的数据。
- 尊重平台服务条款、robots、API 限额和访问频率。
- Cookie、Token、API Key 加密存储并在日志中脱敏。
- 平台原始 HTML/文本视为不可信数据，不能成为系统指令。
- 下载媒体前校验域名、类型、大小和重定向目标。
- 导出数据时执行权限和敏感字段检查。
- 支持按来源、任务、用户和时间范围删除数据。
- 记录采集人、处理人、导出人和删除人。
- AI 请求前根据策略删除或掩码个人敏感信息。

## 11. 可观测性

关键指标：

- 每个 Source 的请求成功率、限流率和认证失效率。
- 每分钟采集、规范化和 AI 处理记录数。
- 重复率、隔离率和 Schema 校验失败率。
- AI 平均延迟、token、费用和重试率。
- 队列积压、批次耗时和步骤耗时。
- 每个 Connector 与 Pipeline 版本的错误分布。

所有日志携带：

```text
request_id
job_id
run_id
record_id（适用时）
source
connector_version
pipeline_version
```

日志中不得写完整原始正文、凭证或敏感个人信息。

## 12. 失败与重试策略

错误分为：

- `AUTH_ERROR`：暂停任务，要求更新凭证。
- `RATE_LIMITED`：指数退避并保留 checkpoint。
- `SOURCE_TEMPORARY_ERROR`：有限次数重试。
- `SOURCE_DATA_INVALID`：单条隔离，不终止整个批次。
- `NORMALIZE_ERROR`：进入隔离区并保存原始数据。
- `AI_PROVIDER_ERROR`：重试或降级到备用 Provider。
- `AI_SCHEMA_INVALID`：按修复提示重试，超限进入死信队列。
- `STORAGE_ERROR`：终止当前批次，防止状态和数据不一致。

重试必须幂等，不能因网络重试重复创建业务记录。

## 13. 分阶段实施

### 阶段 1：统一模型与小红书适配

- 新建 `backend/app/data_cleaning/`，只新增通用表；导入模型供现有 `init_db()` 创建。
- 复用统一 `Task`，以 `module='data_cleaning'` 记录任务；专属批次、步骤与记录结果放新表。
- XHS Adapter 从 `XhsNote` 和本次任务输入清单读取，不依赖 `result_json` 反推全部输入。
- 保持 `XhsCollectStats`、`XhsNoteStructured` 和现有 API 可用，通过兼容服务双写/投影。
- 采用现有同步 Worker 风格和 `SessionLocal`，工作线程计算、单写入器批量持久化。

验收：现有小红书采集功能不回退；50 条测试数据可以展示完整清洗漏斗，每个过滤数量都能下钻到对应记录和原因，最终强相关数据写入数据库。

### 阶段 2：通用任务与流水线

- 暂不新建另一套 collection_jobs；复用当前 `tasks`，建立 CleaningRun 和 PipelineStep。
- 把确定性清洗、去重和质量门禁模块化。
- 前端新增数据清洗批次、漏斗、相关度分布和记录明细页面。

验收：清洗任务可停止、重试和断点续跑；批次计数与记录级结果聚合一致。

### 阶段 3：GLM 语义预处理

- 在现有 `ai_gateway.glm_structured` 之上建立 SemanticModelProvider 适配器。
- 复用现有结构化输出与配置，补齐统一结果外壳、批处理和费用统计。
- AI 结果写入独立 annotation 表。

验收：相同原始数据可使用不同模型/Prompt 版本重处理；旧结果不被覆盖。

### 阶段 4：第二数据源接入

优先选择知乎验证“内容型平台”扩展：

- 实现 Zhihu Connector、Manifest 和 Normalizer。
- 复用小红书已经使用的内容流水线。
- 通用资源库支持来源筛选和跨平台搜索。

验收：新增知乎时不修改流水线核心代码和数据库公共字段。

### 阶段 5：商品型数据源接入

使用淘宝验证不同实体类型：

- 增加 product extension schema。
- 实现 Taobao Connector 和 Normalizer。
- 建立商品价格、店铺和 SKU 的确定性校验。

验收：商品数据和内容数据共用任务、运行、Raw Store、质量和 AI Provider 基础设施。

### 阶段 6：Skill 与分析平台整合

- 为现有 `AnalysisRun.context_refs_json` 定义 `clean_record_set` 引用协议，按来源、任务、主题和时间范围解析上下文。
- 扩展 Context Resolver/业务上下文提供器，不复制 `SkillRuntimeService.prepare_run()` 与 AI Gateway。
- Prompt Builder 只接收有权限且通过质量门禁的 CanonicalRecord 和可信 annotation，并受 60,000 字符总预算约束。
- 旅行、品牌、舆情、商品和股票 Skill 复用统一数据查询接口。

验收：Skill 不需要知道数据来自小红书、知乎还是淘宝，除非其业务逻辑明确要求平台特征。

### 阶段 7：规模化能力

- Object Storage、搜索索引和向量索引。
- 消息队列和分布式 Worker。
- Connector 插件隔离运行。
- 数据血缘、质量看板、成本配额和团队权限。

只有单机版本的接口和幂等语义稳定后再进行此阶段。

## 14. 测试策略

### Contract Tests

所有 Connector 使用同一组契约测试：

- 配置校验。
- 预览不写正式数据。
- 分页不重复、不漏游标。
- checkpoint 可恢复。
- 限流退避。
- close 总能释放资源。

### Fixture Tests

每个平台保存脱敏原始 Fixture，测试 Mapper、Schema 和处理器，不把线上平台作为 CI 依赖。

### Pipeline Tests

- 步骤顺序与条件执行。
- 单步骤失败策略。
- 相同版本重放幂等。
- 新版本不覆盖历史结果。
- AI 输出无效时隔离。
- 每个步骤满足 `input = passed + filtered + quarantined + failed`。
- 下一步骤输入与上一步通过数量一致（允许明确声明旁路的步骤除外）。
- 批次 `saved_count` 与 `clean_records` 实际写入数量一致。
- 过滤结果保留原因码、规则版本和证据，不写入主清洗结果表。
- 数据库写入和 saved 状态更新保持事务一致。

### E2E

```text
创建数据源配置
→ 创建采集任务
→ 预览
→ 执行采集
→ 查看批次进度
→ 查看统一记录
→ 查看 AI 标签与证据
→ 选择记录调用 Skill 分析
→ 保存报告
```

## 15. Claude 开发约束

交给 Claude 实现时必须要求：

1. 按阶段实现，每阶段独立提交、测试和验收。
2. 先为现有小红书代码增加兼容适配层，禁止直接大规模删除重写。
3. 核心模块不得出现散落的平台条件分支。
4. 原始数据先落盘，再进行规范化和 AI 处理。
5. AI 结果不得覆盖原始字段或确定性字段。
6. 新增数据源必须通过 Connector Contract Tests。
7. 所有文件路径、URL、凭证和媒体下载经过安全校验。
8. 所有数据库变更提供迁移和回滚方案。
9. 不把实时平台访问作为自动化测试前提。
10. 修改架构范围或接口时同步更新本文档变更记录。
11. 当前没有迁移框架：首期只新增表；任何已有表变更必须先补迁移工具，禁止误以为 `create_all()` 会升级表结构。
12. 不重复创建 Skill Registry、Skill Runtime、Analysis Run 或 AI Gateway。
13. SQLite 首期不得让多个线程高频写清洗账本；使用单写入器或序列化批量提交。

## 16. 第一阶段建议目录

```text
backend/app/data_pipeline/
├── controllers/
├── models/
├── schemas/
├── sources/
├── connectors/
│   └── xhs/
├── normalizers/
├── pipeline/
│   ├── orchestrator.py
│   ├── context.py
│   └── steps/
├── providers/
│   ├── base.py
│   ├── glm.py
│   └── mock.py
├── repositories/
├── services/
└── workers/

frontend/apps/web-antd/src/views/data-pipeline/
├── sources/
├── jobs/
├── runs/
├── records/
└── rules/
```

## 17. 架构决策摘要

| 决策 | 结论 |
|---|---|
| 平台扩展方式 | Connector + Manifest + Normalizer |
| 公共数据结构 | CanonicalRecord + 类型扩展 + sourceFields |
| 原始数据 | 永久保留引用，不被处理结果覆盖 |
| 数据清洗 | 确定性代码优先 |
| AI 预处理 | Provider 抽象、结构化输出、独立 annotation |
| 清洗过程 | 批次、步骤、记录三级账本，所有统计可下钻 |
| 清洗结果 | 强相关/符合策略的数据写入独立 clean_records 表 |
| 过滤数据 | 保留原始记录和过滤原因，不进入主分析数据集 |
| 去重 | 主键、哈希、语义三级策略 |
| 任务执行 | 幂等、checkpoint、可重放 |
| 当前任务承载 | 复用 `tasks`，清洗专属状态放扩展表 |
| 下游集成 | Query Service + 领域事件 |
| Skill 对接 | `AnalysisRun.context_refs_json` + 现有 Skill Runtime/AI Gateway |
| XHS 迁移 | `XhsNote` 作为 Adapter 输入；旧统计/结构化表作为兼容投影 |
| 第一扩展验证 | 知乎验证内容平台，淘宝验证商品实体 |
| 规模化路径 | 单机接口稳定后接对象存储、队列和索引 |

## 18. 变更记录

| 版本 | 日期 | 内容 |
|---|---|---|
| 1.0 | 2026-08-03 | 初始设计：通用 Connector、统一数据模型、处理流水线、AI 预处理与平台扩展规范 |
| 1.1 | 2026-08-03 | 收敛为数据清洗核心模块；增加清洗漏斗、相关度分级、批次/步骤/记录三级账本和 clean_records 入库设计 |
| 1.2 | 2026-08-03 | 按现有代码校准：复用 tasks、Skill Runtime、AnalysisRun 和 AI Gateway；增加 XHS 双写桥接、SQLite 单写入器及无迁移框架约束 |
