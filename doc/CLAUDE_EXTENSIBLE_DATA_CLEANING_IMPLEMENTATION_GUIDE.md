# Claude 开发手册：可扩展数据清洗与分析引擎

> 文档版本：v1.1（已按当前代码库校准）  
> 更新时间：2026-08-03  
> 项目目录：`/Users/lipeng01/vscode/workbench`  
> 配套架构文档：`GENERAL_DATA_PIPELINE_TECHNICAL_DESIGN.md`

## 0. 给 Claude 的执行指令

你正在为统一工作台开发一个“采集后数据清洗与分析引擎”。不要把它实现成小红书专用模块，也不要把数据来源、分析类型和模型提供商耦合在一起。

必须按本文档的阶段顺序实施。每个阶段完成后：

1. 运行本阶段测试。
2. 汇报修改文件、数据库迁移、测试结果和遗留问题。
3. 等待确认后再进入下一阶段。
4. 不修改本阶段范围外的小红书、股票或前端页面。

开发前必须阅读：

```text
backend/app/main.py
backend/app/common/models/
backend/app/common/controllers/
backend/app/common/models/task.py
backend/app/common/services/ai_gateway/
backend/app/common/services/skill_runtime/
backend/app/analysis/
backend/app/skills/
backend/app/xhs/controllers/collect_tasks.py
backend/app/xhs/models/xhs_note.py
backend/app/xhs/models/xhs_collect_stats.py
backend/app/xhs/models/xhs_note_structured.py
backend/app/xhs/services/note_preprocess.py
backend/app/xhs/services/note_structurer.py
backend/app/xhs/services/tasks.py
frontend/apps/web-antd/src/router/routes/modules/
frontend/apps/web-antd/src/views/xhs/
GENERAL_DATA_PIPELINE_TECHNICAL_DESIGN.md
```

## 1. 目标和边界

### 目标

上游完成数据采集后，把数据交给统一清洗引擎。引擎需要：

- 接收小红书、淘宝、知乎及未来平台的数据。
- 将不同原始数据映射为统一输入结构。
- 按可配置流水线执行格式校验、去重、质量过滤和语义分析。
- 支持不同分析类型，不局限于“主题相关度”。
- 记录批次、步骤和单条记录的完整处理过程。
- 显示清洗漏斗和分析分布。
- 将符合入库策略的数据写入数据库。
- 让 Skill、报告、搜索和其他业务模块消费干净数据。

### 边界

本模块从“已经采集的数据”开始。平台登录、验证码、翻页、反爬和媒体下载不属于本模块。

本模块第一版不执行用户上传的脚本，不安装 MCP，不自动修改清洗规则。

## 2. 最重要的抽象

系统有四个彼此独立的变化维度：

```text
数据来源 Source
    小红书 / 淘宝 / 知乎 / 文件 / API

数据类型 Entity Type
    content / comment / product / author / topic

分析类型 Analysis Type
    relevance / sentiment / entity_extract / spam / quality / custom

模型提供商 Provider
    deterministic / GLM / Gemini / mock
```

禁止组合成以下类：

```text
XhsRelevanceCleaner
TaobaoSentimentCleaner
ZhihuSpamCleaner
```

这会导致平台数 × 分析类型数的组合爆炸。

正确组合：

```text
XhsInputAdapter
TaobaoInputAdapter
ZhihuInputAdapter

RelevanceProcessor
SentimentProcessor
SpamProcessor
EntityExtractionProcessor

GlmProvider
GeminiProvider
MockProvider
```

运行时按配置组合：

```text
XhsInputAdapter + RelevanceProcessor + GlmProvider
TaobaoInputAdapter + SpamProcessor + GlmProvider
ZhihuInputAdapter + SentimentProcessor + GeminiProvider
```

## 3. 核心领域模型

## 3.1 CleaningInput

所有上游数据必须先转换成统一输入：

```python
@dataclass(frozen=True)
class CleaningInput:
    source: str
    entity_type: str
    source_id: str
    source_url: str | None
    title: str | None
    text: str | None
    author: dict | None
    published_at: datetime | None
    collected_at: datetime
    metrics: dict
    media: list[dict]
    tags: list[str]
    source_fields: dict
    raw_record_id: str
```

核心引擎只能接收 `CleaningInput`，不能直接接收小红书 ORM、淘宝 JSON 或知乎 API 响应。

## 3.2 CleaningPolicy

清洗策略定义本次“如何处理”，而不是写死在 Processor：

```python
@dataclass(frozen=True)
class CleaningPolicy:
    key: str
    version: str
    name: str
    entity_types: list[str]
    pipeline_steps: list[str]
    analysis_configs: list["AnalysisConfig"]
    admission_rule: "AdmissionRule"
```

配置示例：

```json
{
  "key": "social-topic-research",
  "version": "1.0.0",
  "entityTypes": ["content"],
  "pipelineSteps": [
    "schema-validate",
    "text-clean",
    "exact-deduplicate",
    "quality-score",
    "analysis-dispatch",
    "admission-evaluate",
    "clean-data-write"
  ],
  "analyses": [
    {
      "type": "relevance",
      "processor": "semantic-relevance",
      "provider": "glm",
      "parameters": {
        "topic": "新加坡二手家具"
      }
    },
    {
      "type": "spam",
      "processor": "commercial-spam",
      "provider": "glm",
      "parameters": {}
    }
  ],
  "admissionRule": {
    "expression": "relevance.score >= 75 and spam.probability < 0.7"
  }
}
```

第一版不要实现通用 `eval`。入库规则使用受控 JSON 条件树或代码实现的安全表达式解释器。

## 3.3 AnalysisDefinition

每一种分析类型通过注册表声明：

```python
@dataclass(frozen=True)
class AnalysisDefinition:
    key: str
    display_name: str
    supported_entity_types: list[str]
    input_requirements: list[str]
    output_schema: dict
    default_processor: str
    default_provider: str
    version: str
```

内置分析类型：

| key | 用途 | 典型输出 |
|---|---|---|
| relevance | 与研究主题的相关程度 | score、level、reason、evidence |
| sentiment | 情绪和立场 | label、score、targets、evidence |
| entity_extract | 实体抽取 | entities |
| topic_classify | 主题分类 | categories、scores |
| spam | 广告、灌水和低价值内容 | probability、signals |
| quality | 内容质量 | score、issues |
| intent | 购买、咨询、投诉等意图 | intent、confidence |
| summarize | 结构化摘要 | summary、key_points |

新增分析类型时，只增加 Definition、Processor、JSON Schema 和测试，不修改 CleaningEngine。

## 3.4 AnalysisResult

所有分析结果使用统一外壳：

```python
@dataclass
class AnalysisResult:
    analysis_type: str
    analysis_version: str
    status: str
    provider: str
    model: str | None
    prompt_version: str | None
    result: dict | None
    score: float | None
    confidence: float | None
    reason: str | None
    evidence: list[str]
    error_code: str | None
    duration_ms: int
```

`result` 必须通过 AnalysisDefinition 的 output schema 校验。

## 3.5 StepResult

每个步骤统一返回：

```python
@dataclass
class StepResult:
    status: Literal["passed", "filtered", "quarantined", "failed"]
    reason_code: str | None
    reason_text: str | None
    data: CleaningInput | None
    field_changes: dict
    metrics: dict
    analysis_results: list[AnalysisResult]
```

禁止通过异常表示正常过滤。只有技术故障才抛异常；规则过滤返回 `filtered`。

## 4. 扩展接口

## 4.1 InputAdapter

```python
class InputAdapter(Protocol):
    source: str
    version: str

    def supports(self, value: object) -> bool: ...
    def adapt(self, value: object, context: AdapterContext) -> CleaningInput: ...
```

实现：

```text
adapters/xhs.py
adapters/taobao.py
adapters/zhihu.py
adapters/generic_json.py
```

Adapter 只映射字段，不执行相关度、情绪和摘要分析。

## 4.2 CleaningStep

```python
class CleaningStep(Protocol):
    key: str
    version: str

    def supports(self, data: CleaningInput, context: CleaningContext) -> bool: ...
    def execute(self, data: CleaningInput, context: CleaningContext) -> StepResult: ...
```

内置步骤：

```text
schema-validate
text-clean
metric-normalize
exact-deduplicate
quality-score
analysis-dispatch
admission-evaluate
clean-data-write
```

## 4.3 AnalysisProcessor

```python
class AnalysisProcessor(Protocol):
    key: str
    version: str
    supported_analysis_types: set[str]

    def analyze(
        self,
        definition: AnalysisDefinition,
        data: CleaningInput,
        config: AnalysisConfig,
        context: AnalysisContext,
    ) -> AnalysisResult: ...
```

Processor 决定任务如何组织，Provider 只负责模型调用。

## 4.4 ModelProvider

```python
class ModelProvider(Protocol):
    key: str

    def generate_structured(
        self,
        system_instruction: str,
        input_text: str,
        output_schema: dict,
        options: ProviderOptions,
    ) -> ProviderResult: ...
```

Provider 不知道“小红书”和“相关度”，只接收指令、输入和 Schema。

## 4.5 AdmissionEvaluator

```python
class AdmissionEvaluator(Protocol):
    def evaluate(
        self,
        data: CleaningInput,
        analyses: dict[str, AnalysisResult],
        rule: AdmissionRule,
    ) -> AdmissionDecision: ...
```

结果：

```python
AdmissionDecision(
    admitted=True,
    reason_code="STRONG_RELEVANCE",
    reason_text="相关度 88，广告概率 0.12，符合入库策略",
)
```

入库规则与分析逻辑分离。同一份分析结果可以应用不同入库策略而不必重复调用模型。

## 5. 注册表机制

建立进程内注册表：

```text
AdapterRegistry
StepRegistry
AnalysisRegistry
ProcessorRegistry
ProviderRegistry
PolicyRegistry
```

注册示例：

```python
analysis_registry.register(RelevanceAnalysisDefinition())
processor_registry.register(SemanticRelevanceProcessor())
provider_registry.register(GlmProvider(...))
```

第一版使用显式注册，不使用扫描任意目录或动态 import 用户代码。未来插件化时再增加隔离和签名。

启动时检查：

- key 唯一。
- Policy 引用的 Step、Analysis、Processor 和 Provider 全部存在。
- Analysis 输出 Schema 合法。
- Entity Type 兼容。
- Admission Rule 引用的字段存在。

任一失败则拒绝启用该 Policy，不要运行到一半才发现配置错误。

## 6. 清洗执行引擎

```python
class CleaningEngine:
    def run(self, command: StartCleaningCommand) -> CleaningRunSummary:
        policy = policy_registry.get(command.policy_key, command.policy_version)
        run = run_repository.create(command, policy)

        for raw_item in input_repository.iter_batch(command.input_batch_id):
            self._process_record(run, raw_item, policy)

        return run_repository.finalize(run.id)
```

单条处理：

```python
def _process_record(self, run, raw_item, policy):
    data = adapter_registry.for_source(run.source).adapt(raw_item, ...)

    for sequence, step_key in enumerate(policy.pipeline_steps):
        step = step_registry.get(step_key)
        result = step.execute(data, context)
        ledger_repository.save_step_result(run.id, raw_item.id, sequence, result)

        if result.status == "passed":
            data = result.data or data
            continue

        if result.status in {"filtered", "quarantined"}:
            return

        if result.status == "failed":
            retry_or_dead_letter(...)
            return
```

每个步骤结果先写账本，再进入下一步。不能最后才汇总，因为中途崩溃会丢失过程。

## 7. 清洗漏斗与计数规则

## 7.1 批次级不变量

```text
input_count = saved_count + filtered_count + quarantined_count + failed_count
```

如果任务仍在执行，增加 `processing_count`：

```text
input_count = saved + filtered + quarantined + failed + processing + pending
```

## 7.2 步骤级不变量

```text
step.input_count
= step.passed_count
 + step.filtered_count
 + step.quarantined_count
 + step.failed_count
```

下一步骤的 `input_count` 等于上一步的 `passed_count`，除非步骤明确配置旁路。

## 7.3 分析结果与过滤结果分离

例如相关度分析得到：

```text
不相关 10
弱相关 8
中相关 7
强相关 15
总计 40
```

入库策略可能只接收强相关，因此：

```text
分析输入 40
强相关 15
入库 15
策略过滤 25
```

“弱相关”是分析结果，“过滤”是入库决策，两者不能使用同一个字段表达。

## 7.4 统计产生方式

记录级 `cleaning_record_steps` 是事实来源。批次和步骤计数是投影：

- 正常执行时在同一事务增量更新。
- 提供后台校对任务从记录级结果重新聚合。
- 前端只读后端统计，不能自行提交统计值。

## 8. 数据库模型

必须新增以下表；具体字段以配套设计文档为基础。

## 8.1 cleaning_policies

保存策略版本和配置快照：

```text
id, policy_key, version, name, config_json, enabled,
content_hash, created_by, created_at
```

`(policy_key, version)` 唯一。已经被执行引用的版本禁止覆盖。

## 8.2 cleaning_runs

保存清洗批次、主题、策略版本、状态和漏斗总计。

## 8.3 cleaning_step_stats

保存每个步骤的输入、通过、过滤、隔离、失败和耗时。

## 8.4 cleaning_record_steps

建议使用 `cleaning_record_steps` 作为最终表名，比 `cleaning_record_results` 更明确：

```text
id
cleaning_run_id
raw_record_id
step_key/step_version/sequence
status
reason_code/reason_text
score/level
evidence_json
field_changes_json
analysis_result_ids_json
provider/model/prompt_version
duration_ms
created_at
```

唯一约束：

```text
(cleaning_run_id, raw_record_id, sequence)
```

## 8.5 analysis_results

```text
id
cleaning_run_id
raw_record_id
analysis_type/analysis_version
processor_key/processor_version
provider/model/prompt_version
status
result_json
score/confidence
reason/evidence_json
input_hash
duration_ms
created_at
```

同一分析输入、定义、Prompt 和模型可以用 `input_hash` 缓存。

## 8.6 admission_decisions

独立保存入库决策：

```text
id
cleaning_run_id
raw_record_id
rule_version
admitted
reason_code/reason_text
facts_json
created_at
```

## 8.7 clean_records

只保存最终通过的数据，并保留来源、清洗批次、策略版本、分析摘要和当前版本。

`clean_records` 不保存完整步骤历史，步骤历史通过 `cleaning_run_id + raw_record_id` 查询。

## 9. 数据库事务

单条最终入库必须在一个事务中：

```text
insert/upsert clean_records
insert admission_decisions
insert cleaning_record_steps(status=saved)
update cleaning_step_stats
update cleaning_runs counters
insert outbox_events(record.cleaned)
commit
```

事务失败时不能出现“前端显示已入库但 clean_records 不存在”的状态。

计数更新应使用数据库原子表达式或按记录级结果重算，避免并发覆盖。

## 10. API 契约

## 10.1 分析类型与策略

```text
GET  /api/data-cleaning/analysis-types
GET  /api/data-cleaning/policies
POST /api/data-cleaning/policies/validate
POST /api/data-cleaning/policies
GET  /api/data-cleaning/policies/{key}/versions
POST /api/data-cleaning/policies/{key}/{version}/enable
POST /api/data-cleaning/policies/{key}/{version}/disable
```

## 10.2 执行

```text
POST /api/data-cleaning/runs
GET  /api/data-cleaning/runs
GET  /api/data-cleaning/runs/{id}
GET  /api/data-cleaning/runs/{id}/funnel
GET  /api/data-cleaning/runs/{id}/steps
GET  /api/data-cleaning/runs/{id}/records
POST /api/data-cleaning/runs/{id}/cancel
POST /api/data-cleaning/runs/{id}/retry-failed
POST /api/data-cleaning/runs/{id}/reprocess
```

创建请求：

```json
{
  "source": "xhs",
  "input": {
    "type": "collection_run",
    "id": 1001
  },
  "policyKey": "social-topic-research",
  "policyVersion": "1.0.0",
  "parameters": {
    "topic": "新加坡二手家具"
  }
}
```

## 10.3 记录下钻与人工复核

```text
GET  /api/data-cleaning/runs/{run_id}/records/{raw_record_id}
POST /api/data-cleaning/records/{result_id}/review
GET  /api/data-cleaning/clean-records
GET  /api/data-cleaning/clean-records/{id}
```

人工复核必须保存原决策、新决策、操作人、原因和时间，不删除模型原结果。

## 11. 前端实现

建议目录：

```text
frontend/apps/web-antd/src/views/data-cleaning/
├── runs/index.vue
├── runs/detail.vue
├── policies/index.vue
├── policies/editor.vue
├── records/index.vue
└── components/
    ├── CleaningFunnel.vue
    ├── StepStatsTable.vue
    ├── AnalysisDistribution.vue
    ├── FilterReasonRanking.vue
    ├── RecordDecisionDrawer.vue
    └── PolicyBuilder.vue
```

## 11.1 清洗批次列表

字段：任务名称、数据源、主题、策略版本、输入数、过滤数、强相关数、入库数、保留率、状态、耗时和创建时间。

## 11.2 清洗详情

顶部指标：

```text
输入 50 | 已过滤 35 | 强相关 15 | 已入库 15 | 保留率 30%
```

主体：

1. 漏斗图。
2. 步骤统计表。
3. 各分析类型分布。
4. 过滤原因排行。
5. 单条记录明细。

点击任意漏斗层级自动过滤记录列表。例如点击“不相关 10”后显示这 10 条记录。

## 11.3 记录决策抽屉

对比展示：

- 原始标题和正文。
- 清洗后字段。
- 每一步状态和字段变化。
- 相关度、情绪、广告等分析结果。
- 模型理由和证据片段。
- 最终入库决策。
- 人工复核历史。

## 11.4 策略编辑器

第一版采用表单，不提供任意代码编辑：

- 适用实体类型。
- 清洗步骤排序。
- 启用的分析类型。
- Provider 和模型。
- 分析参数。
- 相关度阈值和入库条件。

保存前调用后端 validate API。

## 12. 推荐后端目录

```text
backend/app/data_cleaning/
├── controllers/
│   ├── runs.py
│   ├── policies.py
│   └── records.py
├── models/
│   ├── policy.py
│   ├── run.py
│   ├── step_stat.py
│   ├── record_step.py
│   ├── analysis_result.py
│   ├── admission_decision.py
│   └── clean_record.py
├── schemas/
├── domain/
│   ├── input.py
│   ├── policy.py
│   ├── analysis.py
│   └── results.py
├── adapters/
│   ├── base.py
│   ├── xhs.py
│   ├── taobao.py
│   └── zhihu.py
├── engine/
│   ├── cleaning_engine.py
│   ├── registries.py
│   ├── context.py
│   └── admission.py
├── steps/
├── analyses/
│   ├── relevance.py
│   ├── sentiment.py
│   ├── spam.py
│   └── entity_extract.py
├── providers/
│   ├── base.py
│   ├── glm.py
│   ├── gemini.py
│   └── mock.py
├── repositories/
├── services/
└── tests/
```

## 13. 分阶段开发任务

### 已有能力禁止重复实现

- 统一任务表 `Task` 已存在；清洗任务使用 `module='data_cleaning'`。
- Skill Registry、Skill Runtime、AnalysisRun、Gemini AI Gateway 已存在。
- XHS 已有确定性预处理、GLM 结构化、汇总统计和缓存表，应渐进桥接。
- 数据库目前由 `create_all()` 初始化且没有 Alembic；它不会升级已有表。

## 阶段 1：领域模型和数据库

实施：

- 创建 `data_cleaning` 包。
- 创建领域 dataclass/Pydantic Schema。
- 创建七张核心新表；在 `app/core/database.py` 的初始化导入链路中注册模型。
- 创建 Repository 接口和 SQLAlchemy 实现。
- 复用 `Task`，不要新建第二套通用任务表；不改已有表、不接模型、不做前端。
- JSON 字段沿用项目约定；需要兼容的复杂快照可使用 `Text + json.dumps/loads`。

验收：

- 新数据库可由 `create_all()` 建表；提供删除“本阶段新增表”的开发环境回滚说明。
- 能创建 Policy、CleaningRun 和记录级步骤结果。
- 表约束和索引测试通过。
- 如果实施中发现必须修改已有表，停止并先提交迁移机制设计，不得直接改 ORM 后宣称完成迁移。

## 阶段 2：注册表、Adapter 和确定性步骤

实施：

- 实现六类 Registry。
- 实现 XHS InputAdapter。
- 实现 schema、text、deduplicate 和 quality 步骤。
- Adapter 读取 `XhsNote` 与任务输入清单，不以 `XhsTaskExtra.result_json` 为唯一来源。
- 使用脱敏的小红书 Fixture 测试；不要依赖线上采集。

验收：

- 50 条 Fixture 得到稳定且可重复的步骤结果。
- 正常过滤不产生异常日志。
- 相同数据和版本重复运行结果一致。

## 阶段 3：执行引擎和清洗账本

实施：

- 实现 CleaningEngine。
- Worker 可并行计算，记录账本由单写入器批量提交，避免 SQLite 写锁竞争。
- 记录结果是事实源，步骤和批次计数由记录聚合产生。
- 实现失败、取消、重试和最终聚合。
- 实现漏斗 API。

验收：

- 模拟中途崩溃后已完成过程不丢失。
- 批次、步骤和记录计数满足不变量。
- 漏斗每个数字都能下钻到具体记录。

## 阶段 4：可扩展分析和 Mock Provider

实施：

- 创建 AnalysisDefinition、Processor 和 Provider 接口。
- 实现 relevance、sentiment、spam 三种 Definition。
- 实现 Mock Provider 和 JSON Schema 校验。
- 实现 Analysis Dispatch Step。

验收：

- 新增分析类型不修改 CleaningEngine。
- Provider 返回非法 JSON 时进入隔离/失败流程。
- 分析结果与入库决策独立保存。

## 阶段 5：GLM Provider 和入库策略

实施：

- 先用适配器复用 `app.common.services.ai_gateway.glm_structured`，通过现有配置读取 GLM API Key、模型和超时。
- 使用结构化输出、低温度、有限重试。
- 实现受控 Admission Rule。
- 实现 Clean Data Writer 和数据库事务。

验收：

- 50 条数据显示不相关/弱/中/强分布。
- 只有符合策略的数据写入 `clean_records`。
- `saved_count` 与数据库实际行数一致。
- API Key 不进入 URL、日志和清洗账本。

## 阶段 6：清洗管理前端

实施：批次列表、详情漏斗、步骤统计、分布图、记录下钻和人工复核。

验收：用户能够从“过滤 35”一路下钻到每条过滤数据及原因，并查看最终 15 条入库数据。

## 阶段 7：第二来源和第二实体类型

先接知乎验证来源扩展，再接淘宝商品验证实体类型扩展。

验收：

- 新增来源只添加 Adapter 和测试。
- 新增 product 分析不修改 XHS Adapter。
- 同一个 relevance Processor 可作用于内容和商品，或通过 Definition 明确限制。

## 阶段 8：Skill 和报告集成

实施：定义 `AnalysisRun.context_refs_json` 的 `clean_record_set` 引用，新增上下文数据提供器解析 `clean_records`；继续调用现有 `SkillRuntimeService.prepare_run()` 和 AI Gateway。按主题、来源、分析类型、分数、时间和权限筛选，在传入 `business_context` 前执行字符预算与引用保留策略。

验收：旅行、品牌、舆情等 Skill 不直接读取平台原始表。

## 14. 必须编写的测试

### Adapter Contract

- 必需字段映射。
- 时区、URL、指标和原始字段保留。
- 非法输入产生明确错误。

### Step Contract

- `passed` 必须返回有效数据。
- `filtered` 必须有 reason_code。
- `failed` 必须有技术错误码。
- 同版本步骤具有确定性，AI 步骤除外但必须保存版本。

### Analysis Contract

- Output Schema 验证。
- evidence 能在原文定位。
- 非法模型输出重试后正确失败。
- Provider 切换不改变统一结果外壳。

### Funnel Invariants

- 批次计数平衡。
- 步骤计数平衡。
- 下一步输入等于上一步通过数。
- saved_count 等于 clean_records 数量。
- filtered 与 failed 分开。

### Persistence

- 入库事务回滚。
- 同策略重跑幂等。
- 新策略版本保留历史。
- 人工复核保留原决策。

## 15. 禁止事项

- 禁止在 CleaningEngine 判断具体平台。
- 禁止在 AnalysisProcessor 读取具体平台 ORM。
- 禁止在 Provider 编写具体业务 Prompt。
- 禁止用 Python `eval` 执行入库规则。
- 禁止用异常表示正常过滤。
- 禁止清洗结果覆盖原始数据。
- 禁止模型直接决定数据库写入而不经过 AdmissionEvaluator。
- 禁止只保存汇总数字而不保存记录级依据。
- 禁止前端计算后回写批次统计。
- 禁止为赶进度跳过数据库迁移和测试。
- 禁止新建重复的 Skill、AnalysisRun、AI Gateway 或通用任务系统。
- 禁止把 `result_json` 当作 XHS 全量原始输入；它是预览/兼容快照。
- 禁止直接删除 `XhsCollectStats` 或 `XhsNoteStructured`；迁移期将其作为兼容投影。
- 禁止多个线程直接高频写 SQLite 清洗账本。

## 16. 每阶段汇报模板

Claude 完成每阶段后按照下面格式回复：

```text
阶段：

已完成：
- ...

修改文件：
- path: purpose

数据库变更：
- 新增表 / 初始化方式 / 回滚说明
- 如已引入迁移工具：revision / upgrade / downgrade

测试：
- command
- result

人工验收：
1. ...

已知限制：
- ...

下一阶段建议：
- ...
```

## 17. 第一阶段给 Claude 的可复制提示词

```text
请阅读项目根目录的：
1. CLAUDE_EXTENSIBLE_DATA_CLEANING_IMPLEMENTATION_GUIDE.md
2. GENERAL_DATA_PIPELINE_TECHNICAL_DESIGN.md

只实施《Claude 开发手册》的“阶段 1：领域模型和数据库”，不要提前实现后续阶段，也不要修改现有业务表。

要求：
- 先确认项目当前使用 `Base.metadata.create_all()` 且没有 Alembic；不要把 `create_all()` 当成表结构迁移。
- 创建 data_cleaning 独立模块。
- 实现领域模型、Pydantic Schema、数据库模型和 Repository 接口；只新增表并注册到现有初始化链路。
- 复用 common.models.Task，以 module='data_cleaning' 表示清洗任务。
- 不修改现有小红书业务逻辑。
- 不重建 Skill、AnalysisRun、AI Gateway 或任务中心。
- 不接入 GLM/Gemini。
- 不开发前端。
- 编写并运行本阶段测试。
- 完成后按文档第 16 节格式汇报，等待确认。
```

## 18. 变更记录

| 版本 | 日期 | 内容 |
|---|---|---|
| 1.0 | 2026-08-03 | 初始版本：抽象来源、实体、分析和 Provider 四条扩展轴，提供 Claude 分阶段实施手册 |
| 1.1 | 2026-08-03 | 按当前代码校准：复用统一 Task、Skill Runtime、AnalysisRun、AI Gateway；明确 XHS 兼容桥接、create_all 限制和 SQLite 单写入器策略 |
