# Workbench 云端部署 + 手机 App 客户端 — 需求分析与技术可行性报告

> 出品：软件开发团队（产品经理 许清楚 · 需求分析 ｜ 架构师 高见远 · 技术评估）｜ 日期：2026-08-14
> 范围：**仅分析与设计，不含代码实现**。本文档为后续开发决策依据。

---

## TL;DR

- **核心价值**：把统一工作台的关键数据装进口袋——手机 App 以原生体验随时查看行情、AI 报告、任务状态、采集笔记，弥补桌面端无法随身携带的空白；H5 因「显示效果差」已被用户证伪，App 方向成立。
- **选型结论**：uni-app（Vue3 + TS + CLI 工程）首选，复用现有 Vue 技术栈、单开发者成本最低；Flutter 备选（仅当追求上架原生性能时）。
- **后端结论**（架构师逐文件核实）：**后端几乎不用改**，App 靠适配层消化（登录 form 编码、Bearer 注入、detail 错误解析、UTC 转本地、媒体图片带 token 等均已确认可行）。
- **部署结论**：自购轻量云服务器 + Docker Compose 原样部署 + Caddy 自动 HTTPS；公网只暴露 443/80。
- **工作量**：约 25~35 人日（MVP 12~16 + P1 8~12 + P2 4~6 + 云部署 1~2），不含备案/上架等待。

---

## 一、需求理解与目标（产品经理）

**一句话定义**：在手机上以原生 App 体验，随时查看/跟踪 workbench 后端的关键业务数据（行情、AI 报告、任务状态、采集笔记）。

**为什么做 App 而不是 H5 响应式改造**：

| 维度 | H5 响应式改造 | 原生/跨端 App |
|---|---|---|
| 开发成本 | 低（复用现有 Vue 代码） | 中高（需新开客户端工程） |
| 显示效果 | 桌面组件在窄屏挤压变形，**用户已明确不满意** | 可按移动端重排布局 |
| 交互体验 | 长列表/图表/下拉刷新流畅度差 | 原生级滚动与手势 |
| SSE 流式 | 移动浏览器切后台易断、无可靠重连 | 可做断线重连+增量渲染 |
| 系统推送 | 基本不可用 | 可用（本地通知/厂商通道） |
| 离线缓存 | 受限 | 可缓存最近数据离线查看 |
| 上架/分发 | 无需 | 上架或侧载（自用侧载成本可控） |

**判断依据**：① 用户原话「整体显示效果在手机上不好」是已验证痛点，H5 路线已被证伪；② 自用为主 + 单用户，App 可侧载分发，规避上架审核最大成本；③ 看行情/读报告/查任务是移动端典型高频场景。**结论：认可原生 App 方向**，但 App 是「数据查看优先」的轻客户端，管理类功能留在桌面。

**用户画像**：本人（技术背景、admin 单账号、自用高频）；潜在共享（P2，只读为主，需后端开放多账号——待确认）。

**典型场景**：通勤碎片时间看行情/自选股（高频）、睡前读 AI 报告（高频）、任务完成收通知（高频）、外出看小红书采集进度（中频）、临时上传数据（低频）。

---

## 二、App 形态选型（产品经理 + 架构师一致）

| 维度 | 原生双端 | Flutter | React Native | **uni-app（推荐）** |
|---|---|---|---|---|
| 开发语言 | Swift+Kotlin（两套） | Dart（需新学） | React（与 Vue 割裂） | **Vue3（现有技术栈直接上手）** |
| 单开发者成本 | 最高 | 中 | 中 | **最低** |
| 学习曲线 | 陡 | 中 | 中 | **缓** |
| 性能 | 最优 | 接近原生 | 中上 | 中上（自用足够） |
| 额外红利 | — | 可出 Web/桌面 | 可出 Web | **可顺带出 H5/小程序兜底** |

**结论**：首选 **uni-app + Vue3 + TypeScript（CLI/Vite 工程）**，UI 库用 **uv-ui**，状态管理 Pinia。Flutter 需 1.5~2 倍工期，仅当确定上架且追求原生性能再评估。

---

## 三、功能范围与需求池（产品经理）

### P0（MVP 必备）——「能连、能看」

| ID | 功能 | 说明 |
|---|---|---|
| P0-01 | 服务地址配置 | 首启引导配置后端 Base URL（https://域名），可编辑/切换/健康探测 |
| P0-02 | 登录认证 | 对接 /api/auth，JWT 存储，过期处理（401 引导重登） |
| P0-03 | 首页数据概览 | /api/home 聚合数据卡片化展示 |
| P0-04 | 股票行情查看 | 行情/指数/市场概览轻量卡片 |
| P0-05 | AI 报告列表+详情 | 列表 + Markdown 渲染 |
| P0-06 | 任务中心状态 | 任务列表、状态、失败标记、日志摘要 |
| P0-07 | 小红书采集/笔记 | 采集任务进度 + 笔记列表 |
| P0-08 | 错误/断网容错 | 友好提示 + 重试，不做白屏 |

### P1（重要）——「补体验」

| ID | 功能 | 说明 |
|---|---|---|
| P1-01 | 自选股管理 | 增删自选 + 行情卡片 |
| P1-02 | AI 报告 SSE 流式 | 弱网断线重连、增量渲染 |
| P1-03 | 推送通知 | 任务完成/失败通知（本地轮询 + 本地通知兜底） |
| P1-04 | 数据上传 | 拍照/文件选择上传 datacenter（**需后端新增 multipart 接口**，~0.5 人日） |
| P1-05 | Markdown 增强渲染 | 表格/代码块/图片放大 |

### P2（可选）——「锦上添花」

| ID | 功能 | 说明 |
|---|---|---|
| P2-01 | 资源搜索转存 | 夸克网盘搜索与转存（只读触发） |
| P2-02 | 技能中心查看 | 只读查看 |
| P2-03 | 设置项 | 主题/字体/通知开关/多服务地址 |
| P2-04 | refresh token | 后端改造（~0.5 人日），长会话体验 |

### 明确不做（留在桌面端）
复杂表格管理（多列/行内编辑）、批量数据管理、数据源/系统级配置、技能编辑、大文件导出管理——窄屏交互成本高、误操作风险大。

---

## 四、云端部署方案（架构师）

### 4.1 现有 docker-compose 上云补充清单

| 补充项 | 做法 | 优先级 |
|---|---|---|
| 域名 + HTTPS | Caddy 自动 Let's Encrypt（最省事）或 nginx+certbot | P0 |
| 反向代理 | Caddy：`api.域名 → backend:8010`、`域名 → frontend:8080`；`/api/` 配 flush（等价 nginx proxy_buffering off） | P0 |
| 端口暴露 | **公网只开放 443/80**；backend 8010 不暴露公网 | P0 |
| CORS 变量 | `.env` 加 `WORKBENCH_CORS_ORIGINS=https://前端域名`（原生 App 不受 CORS 约束，为 H5 调试兜底） | P0 |
| 数据库备份 | cron 每日 `sqlite3 workbench.db ".backup 'backup.db'"` + storage 目录云快照；**备份含 .env** | P0 |
| 安全加固 | 改默认密码 admin/admin123；确认 WORKBENCH_SECRET_KEY 强随机；公网可加 fail2ban/IP 白名单 | P0 |

### 4.2 两种方案对比

| 维度 | **A：自购轻量云服务器（推荐）** | B：云容器托管（Railway/Render） |
|---|---|---|
| 成本 | 2C2G 约 24~60 元/月 | 免费档**休眠**（后台任务失效）；付费 $5~7/月起 |
| 适配度 | Docker Compose 原样跑，零改造 | 需拆服务；APScheduler/SQLite/产物卷与无状态理念冲突 |
| HTTPS | Caddy 一键 | 平台自带，自定义域名需付费档 |
| 后台任务 | 7×24 常驻 | 免费档休眠即停 |
| **结论** | ★★★★★ | ★★ 不适合本项目 |

**推荐：方案 A。待拍板：服务器区域**——国内需 ICP 备案（2~3 周）；不想备案选香港/新加坡/日本轻量服务器（免备案、自用延迟可接受）。

### 4.3 App 访问后端关键点
- 原生 App 不受 CORS 约束（无 Origin 头）
- App 永远走 `https://api.域名`（Caddy 反代），**不要直接暴露 8010**
- **HTTPS 是硬要求**：iOS ATS 强制；Android 9+ 默认禁明文

---

## 五、后端适配评估（架构师 · 逐文件核实）

### 5.1 代码核实结论

| 核实项 | 现状 | 对 App 的影响 |
|---|---|---|
| CORS | 已配置 CORSMiddleware，allow_origins 来自 WORKBENCH_CORS_ORIGINS | 原生 App 无 Origin 头，**不拦截**；H5 调试需把域名加入环境变量 |
| JWT | HS256，payload `{sub, exp}`，**有效期 12h，无 refresh token** | 移动端长会话不友好 → 见 5.2 |
| 登录接口 | `/api/auth/login` 为 **OAuth2PasswordRequestForm（form-urlencoded）** | App 请求层必须按 form 编码提交，勿按 JSON |
| 统一响应 | **无 {code,data,message} 包装**；错误统一 HTTPException `{detail}` | App 请求层统一解析 detail 即可 |
| 分页 | 大部分 `{items,total,page,page_size}`；`/api/tasks-center` 无分页；`/api/xhs/collect-tasks` 扁平 list | 自用数据量可控，App 侧本地截断 |
| 时间 | ISO8601 **UTC** | App 转本地时区展示 |
| SSE | strategy-ai/analyze 与 xhs analyses 均为 `data: {json}` 事件行（delta/error/rating/done）；nginx 已配缓冲关 | 客户端无原生 EventSource 且**无法带 Authorization 头** → MVP 轮询降级（见 5.3） |
| 媒体代理 | `/api/xhs/proxy/media` 支持 `?token=` 查询参数 | **App image 组件可直接拼 token 渲染图片，零后端改动** |
| AI 密钥 | ApiConfig 表明文存储；`GET /api/system/api-configs` 返回全部含 key | 单用户自用可接受；多人必须改造 |

**总判断：后端几乎不用改，App 主要靠适配层消化。**

### 5.2 JWT 过期策略（三选一）

1. **（MVP 推荐）App 记住用户名密码 + 401 自动重登**——零后端改动，自用可接受
2. **（P1）后端加 refresh token**（登录返回 refresh_token + `/api/auth/refresh`，~0.5 人日）——体验最好
3. 调大过期时间到 30 天——密钥泄露窗口变大，**不推荐**作为唯一手段

### 5.3 SSE 移动端可行性

- H5 端：EventSource 带不了 Authorization 头 → 需 fetch/ReadableStream 流式或轮询
- App 端：无原生 EventSource → ① 社区 SSE 插件（P1 评估）② 自写原生插件（成本高）③ **MVP 降级方案（推荐）：提交分析 → 轮询 reports 列表直到 completed → 拉详情全文**，轮询间隔 3~5s，零后端改动零插件依赖
- P1 真流式时后端补 `Cache-Control: no-cache`、`X-Accel-Buffering: no` 两个响应头（一行代码）

### 5.4 后端改动最小清单

| 改动 | 工作量 | 说明 |
|---|---|---|
| `.env` 增加 WORKBENCH_CORS_ORIGINS | 0.1 人日 | 配置类，为 H5 调试兜底 |
| （可选）SSE 响应补两个头 | 0.2 人日 | P1 做真流式时 |
| （可选）tasks-center 加分页 | 0.3 人日 | 任务量增长后 |
| （可选）login 兼容 JSON body | 0.2 人日 | 非必需，App 侧 form 编码即可 |
| （P1）refresh token | 0.5 人日 | 体验项 |
| （P1）datacenter 上传接口 | 0.5 人日 | 手机上传需 multipart 接口 |

**后端不用改、App 侧消化**：登录 form 编码、Bearer 注入、detail 错误读取、UTC 转本地、watchlist 冗余字段忽略、tasks-center 无分页、媒体图片带 token、报告 markdown 全文渲染、轮询式 SSE 降级。

---

## 六、App 端总体架构（架构师）

### 6.1 分层结构

```
页面层    pages/  login home stock reports tasks xhs
请求层    api/ + utils/request.ts    baseURL注入 token 401统一处理 错误提示 超时
存储层    store/(pinia) + utils/storage.ts   登录态 服务地址 设置 自选股缓存
配置层    config/server.ts   首次引导配置 https://api.域名 → storage → 健康校验
```

### 6.2 目录结构草案（uni-app CLI 工程）

```
workbench-mobile/
├── package.json / vite.config.ts / tsconfig.json / index.html
├── src/
│   ├── main.ts / App.vue / pages.json / manifest.json
│   ├── config/server.ts            # 服务地址配置（读/写/校验）
│   ├── utils/request.ts            # uni.request 封装
│   ├── utils/format.ts             # UTC→本地、数字/涨跌幅格式化
│   ├── utils/markdown.ts           # markdown-it → mp-html 适配
│   ├── utils/sse.ts                # P1：SSE 客户端
│   ├── store/user.ts / server.ts   # pinia
│   ├── api/auth.ts home.ts stock.ts reports.ts tasks.ts xhs.ts
│   ├── components/MarkdownView.vue ReportCard.vue Empty.vue ErrorView.vue
│   └── pages/
│       ├── login/index.vue
│       ├── home/index.vue
│       ├── stock/watchlist.vue stock/kline.vue
│       ├── reports/list.vue reports/detail.vue
│       ├── tasks/index.vue
│       └── xhs/tasks.vue xhs/notes.vue
```

### 6.3 关键技术决策表

| # | 决策项 | 推荐 | 理由 |
|---|---|---|---|
| 1 | 跨端框架 | uni-app（Vue3+TS） | 复用现有技术栈、成本最低 |
| 2 | 工程形态 | CLI(Vite) | 可 Git 审查可 CI；HBuilderX 仅打包调试 |
| 3 | UI 库 | uv-ui | 组件全、Vue3+TS 支持 |
| 4 | JWT 存储 | MVP uni.setStorage；P1 评估 Keychain 插件 | 自用可接受明文 |
| 5 | 网络层 | uni.request 自研轻封装 | 统一 token/错误/超时 |
| 6 | SSE | MVP 轮询；P1 插件 | 轮询零依赖零后端改动 |
| 7 | Markdown 渲染 | mp-html + markdown-it | 表格/代码块支持好 |
| 8 | 图表（K线） | uCharts（P1） | MVP 只展示价格+涨跌幅 |

---

## 七、工作量与里程碑（单开发者）

| 阶段 | 范围 | 人日 | 验收标准 |
|---|---|---|---|
| MVP (P0) | 服务地址配置、登录、首页概览、行情只读、报告列表+详情、任务中心、XHS 状态、错误容错 | **12~16** | **Android APK** 可用；8 个核心页面可用；弱网兜底；401 引导重登；markdown 正常渲染 |
| P1 | 自选股增删、SSE 流式、本地通知、数据上传、Markdown 增强 | **8~12** | 流式断线可恢复；通知可达；上传有校验 |
| P2 | 资源转存只读、技能只读、设置项、refresh token | **4~6** | 功能闭环；长会话体验 |
| 云部署 | 服务器/备案、Caddy+HTTPS、备份、加固 | **1~2** | https 可访问；每日自动备份 |

**合计约 25~35 人日**（不含备案/上架等待）。

---

## 十、决策记录

### 决策 1（2026-08-14 · 用户拍板）：App 工程采用独立 git 仓库 `workbench-mobile`

**背景**：现有 workbench 为单 git 仓（backend/ + frontend/ + doc/ + 部署脚本），根目录无 package.json，前端 pnpm workspace 隔离在 frontend/ 子目录内；新 App 为 uni-app CLI 工程（Vue3+TS）。

**架构师推荐理由**（高见远）：
1. 与后端零代码共享（后端 Python、App 不复用 Vben 组件、TS 类型自建），同仓无实质收益
2. uni-app 与 Vben pnpm workspace 是两套独立 npm 生态，独立仓彻底规避工程形态冲突（含未来根目录建 workspace 的风险）
3. App 按商店发版节奏独立 CI/tag，与后端 docker-compose 部署链路完全解耦
4. 独立 context 对 AI 协作/代码检索更友好（不被 backend/frontend 数千文件污染）
5. docker-compose.yml / deploy.sh / lefthook.yml 均零改动，对现有部署零风险

**落地要点**：
- 仓库命名：`workbench-mobile`（不绑定框架，未来换 Flutter/RN 亦成立）
- 模板：`npx degit dcloudio/uni-preset-vue#vite-ts`（CLI/Vite+TS 形态，可进 Git/CI；不用 HBuilderX 可视化工程）
- .gitignore 排除 `node_modules/`、`dist/`、`unpackage/`、`.hbuilderx/`、`.env.local`、`.DS_Store`；**`src/pages.json`、`src/manifest.json`、`src/uni_modules/` 必须提交**
- 本分析报告复制一份进新仓 `docs/decisions/`（作 ADR 设计沿革），workbench 原件保留
- 两仓 README 互引 API 契约位置（后端 API 文档：workbench/doc/）

### 决策 2（待用户拍板）：云服务器区域（国内需备案 vs 香港/新加坡免备案）
### 决策 3（待用户拍板）：MVP 接受轮询代替 SSE 流式（强烈建议接受）
### 决策 4（待用户拍板）：token 策略（MVP 记住密码+401 重登；P1 是否加 refresh token）
### 决策 5（2026-08-14 · 用户提供信息）：目标平台为 Android 单端 → 分发方式闭环
- **用户手机为 Android**，MVP 构建目标收敛为 Android 单端（uni-app 一套代码保留未来出 iOS 能力，但不纳入本轮范围）
- **分发**：侧载 APK，零成本零审核；不需要 iOS 开发者账号 / TestFlight / 上架（上架国内商店需软著+备案，后置为可选）
- **HTTPS 调整**：iOS ATS 顾虑消除；Android 9+ 默认禁明文，可先通过 network security config 允许指定域名/IP 明文（自用兜底），有域名后仍推荐 Caddy HTTPS
- **推送**：不上架 → 厂商推送通道（小米/华为）不可申请，确认采用「本地轮询 + 本地通知」方案（Android 13+ 需申请 POST_NOTIFICATIONS 权限）
- **真机调试**：Android USB/局域网 IP 联调方便，QA 可在 Android 模拟器/真机验证
### 决策 6（待用户拍板）：是否多人使用
### 决策 7（待用户拍板）：App 端 AI 报告交互（只读历史 vs 发起新分析）

---

## 八、风险清单

| 类别 | 风险 | 缓解措施 |
|---|---|---|
| 技术 | SSE 移动端实现复杂、弱网断流 | MVP 轮询降级先闭环；P1 插件+断线重连 |
| 技术 | Markdown 长报告渲染卡顿 | 分块渲染、懒加载图片 |
| 技术 | Android 真机调试 | 预留 2~3 天；先局域网 IP 连本地后端联调 |
| 外部 | **（Android-only 后消除）** iOS 开发者账号/审核/TestFlight；Android 国内商店需软著 | MVP 直接侧载 APK，零门槛；上架后置为可选 |
| 外部 | 国内服务器 ICP 备案周期长 | 选香港/新加坡轻量服务器免备案 |
| 安全 | JWT 明文存 App、AI key/cookie 明文存 DB | 单用户可接受；多人则需脱敏+加密（后端改造） |
| 安全 | SQLite 备份一致性 | sqlite3 .backup + 云快照 + cron；备份含 .env |
| 安全 | 公网暴露 8010 | 只暴露 443/80；防火墙；fail2ban 可选 |

---

## 九、待用户拍板的决策点

1. **云服务器区域**：国内（需备案 2~3 周）vs 香港/新加坡（免备案，推荐自用）
2. **MVP 是否接受「轮询代替 SSE 流式」**：强烈建议接受（零后端改动先闭环），SSE 放 P1
3. **token 策略**：MVP 记住密码+401 重登；P1 是否加 refresh token（后端 ~0.5 人日）
4. **上架 vs 侧载**：MVP 默认侧载（Android APK + iOS TestFlight），是否投入 iOS 开发者账号
5. **是否多人使用**：单用户自用 → 后端零改动；多人 → 需用户体系 + AI key 加密
6. **App 端 AI 报告交互**：只读历史报告（MVP）vs 手机上发起新分析（P1）
