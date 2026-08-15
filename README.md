# 统一工作台

把 `stock-report-dashboard`（股票分析）和 `Spider_XHS`（小红书采集分析）合并进一个后台管理系统，并在此基础上扩展出资源搜索（夸克网盘）、Skill 技能平台、数据中心等模块。

技术栈：**FastAPI**（后端，SQLite + SQLAlchemy + APScheduler + JWT）＋ **Vue Vben Admin / Vue 3 + Ant Design Vue**（前端，基于官方 monorepo 裁剪为单应用，只保留 `web-antd` 变体）。

## 功能模块

| 模块 | 说明 |
|---|---|
| 首页 | 数据源状态 / 最近任务 / 摘要，读真实 Task 表 |
| 股票分析 | 行情报价、指标、期权、基本面、市场概览、自选股、AI 报告 |
| 小红书分析 | 采集任务、笔记管理（全局去重缓存 + 素材下载）、AI 分析、分析报告、关键词追踪、登录凭证管理 |
| 数据中心 | 数据源 / 上传 / 导出（通用数据清洗预处理管道） |
| 任务中心 | 运行中 / 已完成 / 失败，读真实 Task 表 |
| 资源搜索 | 聚合 Bing / DuckDuckGo 发现夸克网盘分享链接，配置 Cookie 后一键转存（独立模块，见下方说明） |
| 技能中心 | Skill 的导入、查看、启用/禁用，分析时按 Skill 流程执行（Skill 平台） |
| 系统设置 | API 配置、定时任务、日志、用户管理 |

## 目录结构

```
workbench/
├── backend/                 FastAPI 服务
│   ├── app/
│   │   ├── core/            配置、数据库、JWT、APScheduler、日志
│   │   ├── models/          ORM 模型（User / Task / ScheduleConfig / ApiConfig ...）
│   │   ├── schemas/         Pydantic 模型
│   │   ├── api/             各模块路由入口
│   │   ├── common/          通用能力：AI 网关（Gemini 等）、Skill 运行时、数据清洗管道
│   │   ├── stock/           股票分析（行情/指标/期权/基本面/AI 报告）
│   │   ├── xhs/             小红书（采集任务/笔记缓存/分析/追踪/登录凭证）
│   │   ├── resource/        夸克网盘资源搜索与转存
│   │   ├── skills/          Skill 管理
│   │   └── analysis/        数据分析运行
│   ├── seed.py              初始化管理员账号 + 示例数据（幂等）
│   └── requirements.txt
├── frontend/                Vben Admin monorepo（仅 apps/web-antd）
│   └── apps/web-antd/
│       ├── src/router/routes/modules/   侧边栏路由（home/stock/xhs/data-center/task-center/resource/skills/settings）
│       ├── src/views/                   各模块页面
│       └── src/api/core/                auth / user / workbench 等接口适配
├── doc/                     技术文档（设计、实施手册、交接文档，见「文档索引」）
├── deploy.sh                一键 Docker 构建 + 部署
├── docker-compose.yml       backend + frontend 容器编排
├── .env.example             docker 部署环境变量模板（复制为 .env 后修改）
├── start.sh                 一键启动本地开发环境
├── stop.sh                  一键停止本地开发环境
└── TODO.md                  待实施的优化项
```

## 快速开始（本地开发）

### 一键启动

```bash
./start.sh        # 检测依赖 → 初始化数据库/种子数据 → 启动前后端 → 健康检查
./stop.sh         # 停止前后端
```

启动完成后：

- 前端 http://localhost:5666
- 后端 http://localhost:8010（API 文档 http://localhost:8010/docs）
- 日志 `logs/backend.log`、`logs/frontend.log`

### 手动启动

**后端**（端口 8010）：

```bash
cd backend
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python seed.py          # 建库 + 种子数据（幂等，可重复执行）
.venv/bin/uvicorn app.main:app --port 8010
```

**前端**（端口 5666，dev server 代理 `/api/` → `http://localhost:8010`）：

```bash
cd frontend
pnpm install                                # 需要 pnpm（monorepo 强制）
pnpm --filter @vben/web-antd run dev
```

浏览器打开 `http://localhost:5666`，用 `admin` / `admin123` 登录（仅本地验证用，首次登录后请修改密码）。

> 前端依赖安装慢时可以换成国内镜像：`pnpm config set registry https://registry.npmmirror.com`。

## Docker 部署

本地或服务器一键构建 + 部署：

```bash
cp .env.example .env    # 把 WORKBENCH_SECRET_KEY 换成随机密钥，例如 openssl rand -hex 32
./deploy.sh             # 幂等：首次会建镜像、起容器、初始化管理员账号；之后再跑即增量更新
```

部署完成后访问 `http://<本机或服务器IP>:80`（端口在 `.env` 的 `FRONTEND_PORT` 调整）。

说明：

- `WORKBENCH_SECRET_KEY` 用于签 JWT，**生产环境必须设置强随机密钥**，否则 docker compose 会拒绝启动
- 容器内 SQLite 数据库和素材产出分别挂载在 `backend_data` / `backend_storage` 卷，容器重建不丢数据

## 部署须知：小红书签名脚本

`backend/static/` 下的 `xhs_main_*.js` / `xhs_creator_*.js` / `xhs_rap.js` / `xhs_xray.js` / `xhs_websectiga_env.js`
是小红书的**逆向签名脚本**（平台前端产物），**不进 GitHub 版本库**（公开分发存在合规风险）。

- **影响范围**：缺失时仅影响 xhs 的**搜索 / 笔记详情**等依赖 `x-s` 签名的 API 接口；评论爬取（Playwright 页面级）、素材下载等**不受影响**
- **获取方式**：浏览器 DevTools → Network 面板筛选 `xhs_main` / `xhs_rap` 等关键字，抓取当前页面加载的脚本，放入 `backend/static/` 后重启后端（或从开发者处获取）
- **缺失提示**：后端启动时会打印缺失警告；对应接口调用时会抛出带指引的明确报错，而不是神秘的文件错误

## 资源搜索模块（夸克网盘）

- **搜索**：聚合 Bing / DuckDuckGo 发现 `pan.quark.cn/s/` 分享链接，支持电影 / 剧集 / 电子书等分类；如需更稳定的第三方夸克搜索 API，设置环境变量 `WORKBENCH_QUARK_SEARCH_API`（GET `{url}?keyword=&page=`）后自动优先使用
- **转存**：配置夸克 Cookie 后一键转存到个人网盘（走夸克官方接口，提取码自动识别、可指定目录），转存历史见「转存记录」
- **可扩展**：新增网盘源只需实现 `backend/app/resource/services/base.py` 的 `ResourceSource` 并在 `controllers/resource.py` 注册一行，前端「资源搜索」页自动支持
- Cookie 获取：登录 pan.quark.cn → F12 → Network → 复制请求头 Cookie，存于本服务数据库，仅用于调用夸克接口

## 文档索引

技术文档统一放在 [`doc/`](doc/README.md)：

| 文档 | 说明 |
|---|---|
| [doc/README.md](doc/README.md) | 技术文档总索引 |
| [通用数据清洗与预处理模块设计](doc/GENERAL_DATA_PIPELINE_TECHNICAL_DESIGN.md) | 通用数据清洗漏斗 / 去重 / 相关度判断设计 |
| [可扩展数据清洗与分析引擎 · 开发手册](doc/CLAUDE_EXTENSIBLE_DATA_CLEANING_IMPLEMENTATION_GUIDE.md) | 数据清洗引擎的分阶段实施手册 |
| [Skill 平台技术设计](doc/SKILL_PLATFORM_TECHNICAL_DESIGN.md) | Skill 管理中心与运行服务设计 |
| [小红书笔记结构化预处理 · 技术方案](doc/小红书笔记结构化预处理-技术方案.md) | 单篇 token 降 80% 的预处理方案 |
| [小红书分析 UI 重构交接文档](doc/XHS_UI_CLAUDE_HANDOFF.md) | 小红书模块 UI 重构交接材料 |
