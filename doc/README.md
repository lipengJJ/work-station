# 技术文档索引

统一工作台的设计方案、实施手册与交接文档。按主题归档，新增技术文档请放在本目录并在此登记。

## 数据管道

| 文档 | 说明 |
|---|---|
| [通用数据清洗与预处理模块设计](GENERAL_DATA_PIPELINE_TECHNICAL_DESIGN.md) | 与数据平台无关的通用数据清洗/过滤/去重/相关度判断模块设计（Draft v1.2） |
| [可扩展数据清洗与分析引擎 · 开发手册](CLAUDE_EXTENSIBLE_DATA_CLEANING_IMPLEMENTATION_GUIDE.md) | 面向开发者的分阶段实施手册，配套上面的架构文档 |

## 小红书

| 文档 | 说明 |
|---|---|
| [小红书笔记结构化预处理 · 技术方案](小红书笔记结构化预处理-技术方案.md) | 单篇 token 降 80% 的结构化预处理方案（v1.0） |
| [小红书分析 UI 重构交接文档](XHS_UI_CLAUDE_HANDOFF.md) | 小红书模块产品与 UI 重构的交接材料（v1.1） |

## 技能平台

| 文档 | 说明 |
|---|---|
| [Skill 平台技术设计](SKILL_PLATFORM_TECHNICAL_DESIGN.md) | Skill 管理中心、运行服务与 AI 组合请求的技术设计（Draft v1.1） |
| [热点聚合模块 · 融合技术设计](HOTLIST_INTEGRATION_DESIGN.md) | TrendRadar 核心逻辑融合方案（app/hotlist 统一承载，ai_trending 下线） |
| [热点聚合模块 · 实施交接文档](HOTLIST_IMPLEMENTATION_HANDOFF.md) | 分阶段实施细则、当前进度与待办 |

## 相关目录

- `../README.md` — 项目总览、启动方式、目录结构
- `../TODO.md` — 已记录但暂未实施的优化项
