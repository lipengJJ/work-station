# 主题聚合 + RAG 周报 — 增量 PRD：接入 Tavily 开放互联网检索

> 本文为「热点聚合 / 主题订阅」的**增量 PRD**，不是从零设计一个新系统。
> 既有能力已经很完整：`HotTopic` 支持语义检索召回（`embedding_service.py`）、漏斗式候选池收敛（`topic_report_service.py` 的 L0→L1→L2）、LLM 生成周报（`app.common.services.ai_gateway`）、按 `digest_cron` 定时出报（`scheduler_jobs.register_topic_job`）——这套「主题聚合 + RAG 周报」骨架**已经在跑**，本次不动。
> 唯一的缺口：候选池的数据来源目前**只有用户自己配置并绑定给主题的 RSS 源**（`fetch_candidate_pool()` 严格按 `_topic_source_ids` 过滤 `HotItem`），没有开放式互联网检索能力——用户关心的话题如果没人做 RSS 源，主题就是空的。本次增量：接入 [Tavily Search API](https://docs.tavily.com) 作为**可选的、主题级开关**的补充检索渠道。
> 团队已经踩过坑（见 `services/adapters/__init__.py` 注释）：自建 NewsNow/HN/GitHub/HuggingFace/arXiv 等专用适配器维护成本不划算，全下掉了。Tavily 是托管 API（不用自己维护爬虫/反爬），本次设计要确保不重蹈"自定义适配器"的覆辙——**不新增常驻 adapter/爬虫，只在生成报告这一个时机按需调用一次**。

| 项目信息 | 内容 |
|---|---|
| Language | 中文 |
| Programming Language | 与既有 hotlist 模块一致：FastAPI + SQLAlchemy 2.0 + APScheduler（后端）；Vue3 + Vben Admin / web-antd + ant-design-vue（前端）；SQLite |
| Project Name | `hotlist` 模块内增量（`HotTopic` 加字段 + 新增 `internet_search_service.py`，**零新表**） |
| 原始需求 | 做一个"新闻主题聚合 + RAG 周报系统"，用 Tavily（<https://app.tavily.com/playground>）检索互联网相关新闻，补进现有主题周报里 |

---

## 1. 产品定义（增量）

### 1.1 Product Goals

**一句话**：给主题订阅加一个"开放互联网检索"开关，让没有对应 RSS 源、或 RSS 源覆盖不全的关注话题，也能在周报里看到全网相关新闻，而不是干等有没有人做了对应的 RSS 源。

**三个衡量指标**：
1. **覆盖补全率**：对开启互联网检索的主题，本周期候选池中来自 Tavily 的条目占比 > 0（即真的补上了内容，不是摆设开关）。
2. **零回归**：未开启该开关的主题，报告生成行为、耗时、产出与今天完全一致——增量代码路径不影响存量主题。
3. **成本可控**：Tavily 调用严格挂在"生成一次报告"这个动作上（cron 周期触发 或 手动触发生成），不额外起轮询/定时任务；单主题单周期的 Tavily 调用次数固定为 1 次（不因候选池分页、重试等放大）。

### 1.2 User Stories（新增 3 条）

1. 作为**开发者**，我希望给某个主题（比如「Agentic Coding 进展」）打开"互联网检索"开关，以便系统在生成周报时不只看我配置的那几个 RSS 源，还能从全网搜到相关新闻，覆盖我没来得及配 RSS 源的信息源。
2. 作为**开发者**，我希望在报告详情页能区分一条引用是来自"我配置的源"还是"互联网检索"，以便判断这条信息的可信度/来源，需要时能点进原文核实。
3. 作为**开发者**，我希望 Tavily 额度用完/接口超时时报告依然能正常生成（只是少了互联网这部分），而不是整份周报因为一个外部依赖挂掉而失败。

---

## 2. 现状 vs 目标对比表

| 维度 | 现状 | 目标 | 差异说明 |
|---|---|---|---|
| **候选池数据来源** | 仅 `_topic_source_ids` 对应的 `HotSource`（清一色 RSS），`fetch_candidate_pool()` 按时间窗口查 `HotItem` | 新增可选来源：主题开启开关后，候选池额外包含 Tavily 本周期搜到的条目 | 候选池组装逻辑本身**不改**——新增条目照样落进 `HotItem`，只要挂在主题绑定的源集合里，下游语义召回/漏斗/生成全部照常复用 |
| **数据接入方式** | RSS：`crawl_service.py` 按 `cron_expr` 常驻定时抓取一个固定 URL，与主题解耦（源是全局的，主题只是"订阅"哪些源） | Tavily：**主题级、查询驱动、按需触发**——用 `topic.interest_query` 当搜索词，只在"生成本周期报告"这个时机调用一次，不是常驻轮询 | 这是两种本质不同的接入模型：RSS 是"源不知道谁订阅了它"，Tavily 检索是"每个主题的搜索词都不一样，必须绑定主题上下文才能查"——所以不能塞进现有 `crawl_service` 的定时抓取框架，得在报告生成入口单独接一刀 |
| **主题配置** | `interest_query` / `retrieval_mode` / `similarity_threshold` / `retrieval_size` / `digest_strategy` / `digest_period` / `digest_cron` / `max_items` / `shortlist_size` / `fulltext_size` / `skill_key` 等一整套检索与生成参数 | **新增** `enable_internet_search`（开关）/ `internet_search_max_results`（单次拉取上限）/ `internet_search_depth`（basic/advanced） | 三个新字段，其余全部复用，不改现有字段语义 |
| **成本/风控** | 无外部按量计费依赖（embedding 走内部 gateway，AI 生成走已配置好的 LLM provider） | 新增一个按 credit 计费的外部 API；必须把调用频率锁死在"每主题每周期最多 1 次"，且失败要能降级而不是让整份报告失败 | Tavily 是本次唯一新增的外部付费依赖，风控设计是本次的重点，不能像 AI_TRENDING 早期那样"想调就调" |
| **可解释性** | 语义召回结果落 `HotReportCandidate` 快照（含 score/rank_no/model_key/query_hash），报告可复现、可审计 | Tavily 检索到的条目同样先落 `HotItem`，再走同一套语义召回 + 快照逻辑，**不跳过**可解释性这一环 | 明确排除"直接把 Tavily 的 `include_answer` 塞进报告"这种黑盒做法（现有 `ai_gateway` 已支持 Gemini 的 `google_search` tool，但那是 LLM 侧黑盒、无法落快照——本次刻意选择"先检索落库、再走漏斗"这条更重但可审计的路径，与既有架构原则保持一致） |

---

## 3. 技术规范（增量）

### 3.1 需求池

**P0（必做）**
- [ ] `HotTopic` 新增字段：`enable_internet_search: bool = False`、`internet_search_max_results: int = 15`、`internet_search_depth: str = "basic"`（basic/advanced，映射 Tavily `search_depth`）
- [ ] 新建单例 `HotSource`：`id="internet-search"`，`name="开放互联网检索（Tavily）"`，`adapter="internet_search"`——**不参与** `crawl_service.py` 的常规定时抓取（`enabled` 语义与普通源不同，见 3.2.1），种子数据在 `source_service.seed_default_sources()` 里补一条（幂等，`enabled=False`/不注册 cron job）
- [ ] 新建 `services/internet_search_service.py`：`search_and_ingest(topic, time_range) -> list[str]`，调 Tavily `/search`（`topic="news"`, `time_range` 由 `digest_period` 映射, `max_results=topic.internet_search_max_results`, `search_depth=topic.internet_search_depth`, `include_raw_content="markdown"`, `include_answer=False`），结果按现有 `normalize_url` + upsert 逻辑写入 `HotItem`（`source_id="internet-search"`）
- [ ] `topic_report_service.generate_report()` 里：若 `topic.enable_internet_search`，在 `fetch_candidate_pool()` **之前**调用一次 `search_and_ingest`；主题开启开关时自动把 `internet-search` 加进 `HotTopicSource`（关闭时移除），这样 `fetch_candidate_pool()` 零改动即可纳入
- [ ] Tavily API Key：走 `ApiConfig`（系统设置表，对齐 `ai_gateway`/`embedding_config` 现有模式），**不**走 `core/config.py` 的 env var Settings（那个是给 `rsshub_base_url` 这类部署期配置用的，外部付费凭证一律进 DB 系统设置，避免两套凭证管理方式并存）
- [ ] 失败降级：Tavily 请求异常（超时/401/429/额度用尽）只记 `logger.warning` + 跳过这一步，**不**抛异常中断 `generate_report()`；报告仍用现有候选池（RSS 部分）正常生成
- [ ] 前端：主题编辑/新建表单新增"互联网检索"开关 + 展开态的检索深度/最大条数两个高级选项（默认折叠，对齐现有表单里"高级选项默认收起"的交互习惯）
- [ ] 报告详情页：引用列表里来自 `source_id="internet-search"` 的条目加一个 🌐 徽标区分（复用现有来源徽标渲染逻辑，只是多一种来源类型）

**P1（重要）**
- [ ] Tavily 返回结果若已带 `raw_content`（`include_raw_content="markdown"` 命中），`_fetch_fulltexts_concurrent()` 对这批条目跳过重复抓取——省一轮网络请求，也避免部分站点对二次抓取的反爬拦截（这是调研现有 L2 全文抓取逻辑时发现的免费优化点）
- [ ] `language`/`country` 参数：中文用户关注的话题默认加 `language="zh"` 提升中文结果占比（P0 先用 Tavily 默认语言判定，观察实际效果再决定要不要写死）
- [ ] 手动"立即生成报告"的节流：避免用户手快连点导致同一主题短时间内多次调用 Tavily 消耗额度（对齐现有"立即抓取"类按钮的限频模式，具体节流窗口待确认，见第 5 节）

**P2（可选）**
- [ ] 主题级 Tavily 用量统计（本周期消耗多少 credit，帮用户判断要不要开这个开关）
- [ ] `include_domains`/`exclude_domains`：主题级黑白名单域名过滤（P0 不做，先用 `topic="news"` 的默认新闻源质量）
- [ ] 多主题共享搜索结果去重（同一时间窗口内两个主题搜索词高度相似时，是否值得缓存/复用 Tavily 结果——P0 不做，各主题独立调用，逻辑简单优先）

### 3.2 数据模型草案

**`hot_topic` 表新增字段**

| 字段 | 类型 | 约束/默认 | 说明 |
|---|---|---|---|
| enable_internet_search | bool | 默认 False | 主题级开关；关闭时行为与今天完全一致 |
| internet_search_max_results | int | 默认 15 | 对应 Tavily `max_results`（1–20），控成本用 |
| internet_search_depth | str(16) | 默认 "basic" | `basic`（1 credit）/ `advanced`（2 credit，更精但更贵），映射 Tavily `search_depth` |

不新建独立表——Tavily 检索到的内容复用 `HotItem`/`HotReportCandidate` 现有结构，只是多了一个 `source_id`。

#### 3.2.1 为什么用"单例 HotSource"而不是给 Tavily 单独建一套接入方式？

`fetch_candidate_pool()` 今天的实现就是"按主题绑定的 `source_id` 集合过滤 `HotItem`"，这个逻辑已经是通用的、跟"源是怎么来的"无关。把 Tavily 结果包装成一个特殊的 `HotSource`（`adapter="internet_search"`），下游候选池组装、语义召回、快照、漏斗、AI 生成**全部零改动**直接复用。唯一要处理的特殊性只有两点：①这个源不接入 `crawl_service.py` 的常规 cron 抓取（避免被当成普通 RSS 源定时爬，那是无意义的——它没有固定 URL 可爬）；②它的"抓取"动作由 `generate_report()` 主动触发、绑定单个主题的查询词，而不是全局抓一次给所有订阅它的主题共享（因为不同主题的 `interest_query` 不同，搜索结果天然是主题专属的，不能像 RSS 那样"一次抓取、多主题复用"）。

这个决定的代价：`HotItem` 里会出现 `source_id="internet-search"` 但内容其实是"专属于某个主题查询"的条目，理论上不适合被*另一个*没开互联网检索的主题通过候选池"顺手"捞到。缓解方式：`fetch_candidate_pool()` 的候选池本来就是按 `_topic_source_ids` 严格过滤的——只有真正把 `internet-search` 绑进 `HotTopicSource` 的主题（即开了开关的主题）才会看到这些条目，未开开关的主题即使源表里存在这些条目，因为没绑定关系也查不到，天然隔离。

### 3.3 Tavily 请求参数映射

| HotTopic 字段 / 上下文 | Tavily 参数 | 说明 |
|---|---|---|
| `topic.interest_query` | `query` | 直接复用主题的自然语言关注需求，与语义召回用的 query 是同一个文本，检索语义保持一致 |
| 固定值 | `topic="news"` | Tavily 官方定义为"real-time updates, particularly about politics, sports, and major current events"，比 `general` 更贴合"新闻聚合"场景 |
| `topic.digest_period` | `time_range` | `daily→day` / `weekly→week` / `monthly→month`（若 `digest_period` 实际取值与此不完全一致，需在实现时对照 `topic_report_service.compute_period()` 校正，见第 5 节待确认） |
| `topic.internet_search_max_results` | `max_results` | 1–20，默认 15 |
| `topic.internet_search_depth` | `search_depth` | basic/advanced |
| 固定值 | `include_raw_content="markdown"` | 减少后续 L2 全文抓取次数（见 P1） |
| 固定值 | `include_answer=False` | **不用** Tavily 自带的 LLM 摘要——生成这一步交给已有的 `ai_gateway` + `skill_key`，避免同一份内容被两个 LLM 各摘要一次，职责保持单一 |
| 固定值 | `include_images=False` | 周报当前不消费图片，减少无用 payload |

### 3.4 与既有约定的对齐

- 外部付费 API 凭证：进 `ApiConfig`（系统设置），对齐 `ai_gateway`/`embedding_config`，不新增 env var 配置通道。
- 错误语义：Tavily 调用失败按"可降级依赖"处理（`logger.warning` + 跳过），不抛 502 中断报告生成——这与"RSS 源抓取失败会记 `last_error` 但不阻塞其他源"的既有容错哲学一致。
- 依赖最小化：Tavily 是纯 HTTP REST 调用，复用现有 `requests` 用法（对齐 `opml_service.fetch_opml` 的错误处理写法：`try/except requests.RequestException` + 结构化日志），零新增 Python 依赖。
- 调度：**不**新注册任何 cron job——互联网检索完全挂在已有的 `register_topic_job`（`digest_cron` 驱动）触发的 `generate_report()` 内部，调度器改动为零。

---

## 4. 验收口径

- 主题开启"互联网检索"开关并保存后：`HotTopicSource` 出现 `(topic_id, "internet-search")` 关联行；关闭后该行被移除。
- 开启该开关的主题触发一次报告生成（cron 到点 或 手动触发）：`HotItem` 中出现 `source_id="internet-search"` 的新条目（前提：网络可达 + Tavily Key 已在系统设置配置且有效）；报告详情页引用列表中至少一条带 🌐 徽标。
- 未开启该开关的主题：报告生成耗时、候选池条目数、最终产出与本次改动上线前完全一致（回归测试对照）。
- 断网 / Tavily Key 未配置 / Tavily 返回 401 或 429：报告仍能正常生成完成，日志里能看到降级警告，用户在前端看不到任何报错弹窗（静默降级，只是这部分内容缺失）。
- 关闭开关的主题即使 `HotItem` 里存在别的主题产生的 `internet-search` 条目，候选池也不会误纳入（隔离性验证，见 3.2.1）。

---

## 5. 待确认问题（Open Questions，附建议）

1. **`digest_period` 的实际取值范围**：本次调研只确认默认值是 `"weekly"`，未逐一核实是否还支持 `daily`/`monthly` 或其他自定义周期字符串。**建议**：实现前先读一遍 `topic_report_service.compute_period()` 的实际分支，按真实取值补全 3.3 节的映射表；若存在无法映射到 Tavily `day/week/month/year` 的自定义周期（比如"每 3 天"），该周期下 `time_range` 退化为最接近的档位（就近取整，宁可搜宽一点也不漏）。
2. **手动"立即生成报告"的节流窗口**：调研未深入 report 生成端点当前是否已有限频保护。**建议**：如果 `generate_report()` 或其触发端点已有节流（比如复用"立即抓取"的限频模式），直接复用同一节流即可覆盖 Tavily 调用频率，不用为互联网检索单独设计一套节流；如果目前完全没有限频，本次增量顺带补一个（比如同一主题 60 秒内只允许触发一次报告生成），既保护 Tavily 额度也保护 AI 生成成本。
3. **ApiConfig 里 Tavily Key 的管理入口**：调研确认了 `ai_gateway`/`embedding_config` 走 DB 系统设置这个模式，但没有细看现有系统设置页面/端点是否已经是"通用 key-value 配置"可以直接加一行 Tavily 配置，还是需要专门为每个 provider 写死字段。**建议**：优先复用现有通用配置入口（如果有）；如果现有系统设置是为 LLM/embedding provider 专门建模的强类型结构，Tavily 作为"检索类"外部服务可能需要单独一个轻量配置项（一个 key 字段即可，不需要 provider/model 这类字段），实现时按现有系统设置模块的扩展方式来，不额外发明新的配置管理机制。
4. **中文内容占比**：新闻类查询很多用户关心的是中文信息源，Tavily 默认语言判定对中文查询的召回质量待验证。**建议**：P0 先不写死 `language`/`country`，上线后观察开了互联网检索的主题报告里中文条目占比，效果不理想再在 P1 补 `language="zh"` 或做用户可配置。
5. **`internet_search_depth="advanced"` 的开放范围**：`advanced` 是 `basic` 两倍 credit 消耗，要不要在 UI 上对所有用户开放，还是先只给 `basic` 默认值、`advanced` 作为"高级选项"藏起来但不强限制。**建议**：P0 两个选项都开放（本来就是主题级开关，用户自己承担额度消耗），只是默认值给 `basic`，UI 上用小字提示"advanced 消耗更多额度"，不做强制限制。
