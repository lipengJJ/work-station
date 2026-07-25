# 统一工作台

把 `stock-report-dashboard`（股票分析）和 `Spider_XHS`（小红书采集分析）合并进一个后台管理系统。

技术栈：**FastAPI**（后端）+ **Ant Design Pro / React**（前端，基于官方模板裁剪）。

## 当前进度：Phase 2 骨架

- ✅ Phase 1：框架选型（FastAPI + Ant Design Pro）
- ✅ Phase 2（本次）：骨架搭建 —— 见下方"骨架范围"
- ⬜ Phase 3：接入 `stock-report-dashboard/collector/*` 和 `Spider_XHS/webapp/backend/*` +
  `apis/`/`xhs_utils/`/`spider/` 的真实业务逻辑（把代码**拷贝**进本仓库，不跨仓库 import/挂载）

## 骨架范围

侧边栏结构已经按最终设计搭好（首页 / 股票分析 / 小红书分析 / 数据中心 / 任务中心 / 系统设置），
每个子页面都能正常导航、渲染。其中：

- **真实可用**：登录（JWT）、首页（数据源状态/最近任务/摘要，读真实 Task 表）、任务中心（运行中/已完成/失败，读真实 Task 表）
- **后端已有真实 CRUD、前端还是占位**：系统设置里的 API 配置、定时任务（`backend/app/api/system.py`
  已经是可用的接口，Phase 3 把前端页面接上就行）
- **纯占位**（前后端都还没有真实逻辑）：股票分析、小红书分析、数据中心的各个子页面——导航得到、
  显示"开发中"，不报错白屏

## 目录结构

```
workbench/
├── backend/            FastAPI 服务，见 backend/app/main.py
│   ├── app/
│   │   ├── core/        配置、数据库、JWT、APScheduler
│   │   ├── models/      User / Task / ScheduleConfig / ApiConfig
│   │   ├── schemas/     Pydantic 模型
│   │   └── api/         各模块路由
│   └── seed.py          初始化管理员账号 + 示例任务数据
└── frontend/            Ant Design Pro（React + TypeScript + Umi Max）
    ├── config/routes.ts  侧边栏路由树
    └── src/pages/        Home / Stock / Xhs / DataCenter / TaskCenter / Settings
```

## 本地运行

### 后端

```bash
cd backend
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python seed.py          # 建库 + 种子数据（管理员 admin / admin123，仅本地验证用）
.venv/bin/uvicorn app.main:app --port 8010
```

### 前端

```bash
cd frontend
npm install
npm run dev      # http://localhost:8000，代理 /api/ 到 http://localhost:8010
```

浏览器打开 `http://localhost:8000`，用 `admin` / `admin123` 登录。

## Phase 3 要做的事

1. 把 `stock-report-dashboard/collector/{runner,scheduler,oauth}.py`、`analyze.sh`、`run_analysis.md`
   拷贝进来，改造成 `backend/app/api/stock.py` 的真实实现，`Task` 表记录每次分析跑批
2. 把 `Spider_XHS/webapp/backend/{login,tasks,token_store}.py` 和它依赖的 `apis/`、`xhs_utils/`、
   `spider/` 拷贝进来，改造成 `backend/app/api/xhs.py` 的真实实现
3. 前端把 `Stock/*`、`Xhs/*`、`DataCenter/*`、`Settings/*` 下的占位页面逐个替换成真实页面
4. 补 `docker-compose.yml`（backend + frontend 静态资源）
