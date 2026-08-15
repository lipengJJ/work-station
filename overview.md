# 策略驱动的 AI 个股分析 — 交付说明

## 功能简介

在股票分析模块新增「策略驱动的 AI 个股分析」：用户管理一个可复用的**策略库**（内置 3 个预设 + 自定义），对任意股票发起分析时选择一个策略，AI 按该策略的框架（关注范围 / 风险偏好 / 关键因子 / 买入倾向）分析近期情况，输出 markdown 报告并在末尾给出**买入 / 观望 / 回避**分级结论 + 关键指标依据。

- 页面入口：侧边栏「股票分析 → AI研究报告」（`/stock/ai-report`，原静态 mock 页改造）
- 后端前缀：`/api/stock/strategy-ai`

## 新增/修改文件

**后端（backend/app/stock/）**
- 新增 `models/stock_strategy.py` — 策略表 `stock_strategies`（含 is_preset 标记）
- 新增 `models/stock_strategy_report.py` — 报告表 `stock_strategy_reports`（策略/数据双快照，历史可追溯）
- 新增 `schemas/strategy_ai.py` — StrategyIn / AnalyzeIn
- 新增 `services/strategy_service.py` — 策略 CRUD + 3 个内置预设幂等 seed（价值投资 / 趋势交易 / 稳健防守）
- 新增 `services/strategy_analysis_service.py` — context 组装（复用 orchestrator cache-first 数据管道 + K线技术面摘要）、策略渲染 Prompt、结论 JSON 块提取（失败降级 glm 结构化兜底）
- 新增 `controllers/strategy_ai.py` — 8 个接口（见下）
- 修改 `models/__init__.py`、`app/main.py` — 注册模型与路由

**前端（frontend/apps/web-antd/src/）**
- 新增 `api/core/strategy-ai.ts` — API 封装（CRUD + postSSE 流式分析，支持 AbortController 取消）
- 重写 `views/stock/ai-report/index.vue` — 三段式 Tab 布局：**AI 分析**（操作条 + 全宽流式报告 + 分级结论横幅 + 当前策略提示条）/ **策略库**（响应式卡片网格，卡片可一键"使用此策略"切回分析）/ **历史报告**（全宽表格 + 详情弹窗）；全宽铺满 + 响应式（flex-wrap / grid 断点 / min-w-0 防溢出，2026-08-11 优化）

## 接口清单

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/stock/strategy-ai/strategies | 策略列表（首次访问自动 seed 预设） |
| POST/PUT/DELETE | /strategies、/strategies/{id} | 策略 CRUD（预设禁改 rules；有报告引用拒删） |
| POST | /api/stock/strategy-ai/analyze | SSE 流式分析（delta / rating / error / done 事件） |
| GET | /reports、/reports/{id}、DELETE /reports/{id} | 报告历史分页列表 / 详情 / 删除 |

## 验证结果（2026-08-10）

- [x] 预设 seed：首次访问自动插入 3 个内置策略
- [x] 自定义策略创建/删除正常；预设策略 rules 保护生效
- [x] 真实数据分析（AAPL + 价值投资）：SSE 流式输出完整，AI 引用真实数据（PE_TTM 35.97、PE 分位 68.6%、ROE 148.75%）给出「回避」结论，rating JSON 提取正确
- [x] 报告落库：status/model/rating/策略快照完整，历史列表与详情（markdown 全文）正常
- [x] 删除保护：有报告引用的策略返回 400 拒删
- [x] 前端 typecheck 通过（新文件零错误）、vite dev 编译 200
- [x] 2026-08-11 UI 重构：Tabs 三段式布局、分析区全宽铺满、策略库卡片网格、响应式自适应，typecheck 零错误 + vite 编译 200

## 使用方式

服务已在运行：前端 http://localhost:5666（admin/admin123）→ 股票分析 → AI研究报告。
输入股票代码（如 AAPL）→ 选策略 → 开始分析 → 流式出文 → 末尾分级结论；历史报告可查看/删除。
AI 走系统统一的 AI 配置（当前为 DeepSeek，可在 系统设置 → API 配置 切换模型/厂商）。

## 已知限制

- 分级结论提取依赖模型在文末输出 JSON 块；提取失败时会尝试 glm 结构化兜底（需配置 zhipu_api_key），两者都失败则结论为空、报告正文不受影响
- 分析数据来自 yfinance + SEC EDGAR（美股为主），首次分析需拉取真实数据、耗时较长，之后走缓存会明显变快
- 页面未做浏览器端自动化截图验证（工具不可用），但类型检查、编译与后端全链路已验证
