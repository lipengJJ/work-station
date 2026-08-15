# 消息通知模块 · UI 重构与多通道扩展实施文档

> **文档性质**：设计规格 + 实施说明（Design Handoff），供执行 agent 按此实现。
> **版本**：v1.0（2026-08-15）｜ **适用范围**：`workbench-notify` 工作区，`feature/wechat-notify` 分支

---

## 1. 背景与目标

### 1.1 现状问题
- 通知配置为**单通道**：页面用 Segmented 单选切换，一次只能激活一个通道（企业微信群机器人 `wecom_webhook` / Server酱 `serverchan`）
- 配置表单在卡片内联展开，不同通道字段数量不同 → **卡片高度参差**，视觉不统一
- 其他模块（任务中心、小红书等）**无法查询**当前有哪些可用的通知方式，也无法调用发送

### 1.2 目标
| # | 目标 | 验收点 |
|---|---|---|
| G1 | 支持**多通道同时配置、独立启用** | 任务完成/失败时，所有已启用通道均收到推送（扇出） |
| G2 | 通道列表 UI **外观/长短/高度完全一致**（等高卡片） | 任意通道数量下，列表卡片等高同构；深浅主题均正常 |
| G3 | 新通道**数据驱动扩展**，无需改布局 | 接入新通道 = 注册表加一行（以 PushPlus 占位验证） |
| G4 | 其他模块可**查询可用通知方式**并**调用发送** | 公共接口 `GET /api/notify/channels` + 可复用发送组件 |

---

## 2. 工作区与现状

- 工作目录：`/Users/lipeng01/vscode/workbench-notify`（git worktree，分支 `feature/wechat-notify`）
- 不要改动 `/Users/lipeng01/vscode/workbench`（原工作区，feature/ai-trending）
- 端口约定：前端 5668 / 后端 8012（已有配置，勿改）
- 现有实现文件（改造对象）：
  - `backend/app/common/models/notification.py` — NotificationConfig（**当前单例** id=1）+ NotificationLog
  - `backend/app/common/services/notify_service.py` — send_wecom_message / send_serverchan / send_by_config / notify_task_result（daemon 线程 + 静默跳过 + 失败落 log）
  - `backend/app/common/controllers/notify.py` — GET/PUT `/api/notify/config`、POST `/api/notify/test`、POST `/api/notify/send`、GET `/api/notify/logs`（均 JWT 鉴权）
  - `backend/app/common/schemas/notify.py` — Config/Log/分页/SendResult schema
  - `backend/app/core/database.py` — `_ensure_notification_config_sendkey()` 轻量加列模式（无 Alembic，可复用此模式做迁移）
  - 前端 `frontend/apps/web-antd/src/views/settings/notify/index.vue` + `src/api/core/notify.ts`
  - 测试 `backend/tests/test_notify.py`（34）+ `test_notify_serverchan.py`（32）= **66 个用例全绿**

---

## 3. 后端改造（P0）

### 3.1 配置模型多通道化
- **现状**：`NotificationConfig` 单例一行，`channel` 字段表示"当前启用哪个通道"
- **目标**：**每通道一行**，`channel` 为唯一键（primary key / unique），一行存一个通道的独立配置：
  ```
  channel        varchar PK      # wecom_webhook / serverchan / ...（注册表驱动）
  webhook_url    varchar(512)    # 企业微信用
  sendkey        varchar(256)    # Server酱用
  mention_all    bool            # 企业微信 @所有人
  enabled        bool            # 独立启用开关
  created_at / updated_at
  ```
- **数据迁移**（老库单例 → 多行）：
  - 沿用 `database.py` 现有 `_ensure_*` 模式：init_db 时 inspect，幂等、异常只记日志不阻断启动
  - 迁移逻辑：若表内存在旧单例行（id=1）→ 拆分为 `wecom_webhook` 行（保留其 webhook_url/enabled/mention_all）；`serverchan` 行如已配置 sendkey 则同步建行；删除旧单例行语义
- **任务通知扇出**：`notify_task_result` 改为**遍历所有 enabled 通道**逐通道发送（同一线程循环或逐通道独立线程均可；要求：单通道失败不影响其他通道，每通道独立落 NotificationLog，整体异常绝不影响任务主流程）
- **兼容**：`send_by_config`、`normalize_channel`、`config_missing_hint` 保留复用；`send_serverchan`/`send_wecom_message` 不动

### 3.2 通道目录接口（G4 的公共入口）
新增 **`GET /api/notify/channels`**（JWT 鉴权），返回全部已注册通道的元信息与实时状态：

```json
{
  "channels": [
    {
      "channel": "wecom_webhook",
      "label": "企业微信群机器人",
      "icon": "message-circle",
      "description": "任务通知推送到企业微信群，可邀请个人微信入群接收",
      "configured": true,
      "enabled": true,
      "summary": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc…",
      "capabilities": ["text", "markdown", "mention_all"]
    },
    {
      "channel": "serverchan",
      "label": "Server酱",
      "icon": "send",
      "description": "推送直达个人微信（方糖服务号），无需建群",
      "configured": false,
      "enabled": false,
      "summary": null,
      "capabilities": ["markdown"]
    }
  ]
}
```

- **通道注册表**（代码内维护，新通道扩展点）：`CHANNEL_REGISTRY: dict[channel, {label, icon, description, fields, capabilities}]`
  - `fields`：该通道配置表单的**数据驱动字段定义**（见 3.3），前端弹窗按此渲染
- **配置 CRUD 改造**：
  - `GET /api/notify/configs` — 返回全部通道配置（供列表页一次拉取）
  - `PUT /api/notify/config/{channel}` — 保存单通道配置（upsert）
  - `GET /api/notify/config/{channel}` — 单通道配置（可并入 configs，二选一，保持简洁优先）
  - 旧的 `GET/PUT /api/notify/config`（单例语义）**移除或改为别名**，前端同步迁移
- **发送接口扩展**：
  - `POST /api/notify/test` body 支持 `{channel}`：不传 = 第一个 enabled 通道；无 enabled 通道 → 200 + `{success:false, message:"尚未启用任何通知通道"}`
  - `POST /api/notify/send` body 支持 `{channel?, title, content, msgtype?}`：channel 可选，**允许指定任意已配置通道**（不要求 enabled，便于先测再启用）；默认 = 第一个 enabled 通道

### 3.3 数据驱动字段定义（G3 核心）
每个通道在注册表中定义 `fields`，前端弹窗按字段类型渲染，**所有通道弹窗骨架一致**：

```json
{
  "channel": "wecom_webhook",
  "fields": [
    { "key": "webhook_url", "label": "Webhook 地址", "type": "textarea", "mono": true,
      "placeholder": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…",
      "extra": "从企业微信群机器人复制完整地址" },
    { "key": "mention_all", "label": "@所有人", "type": "switch",
      "extra": "text 消息附带 @all" }
  ]
}
```
- 字段类型枚举：`text / password / textarea / switch / select`
- Server酱 `fields`：`sendkey`（password，extra 指引 sct.ftqq.com 扫码获取）
- PushPlus 占位通道（演示扩展性，可只注册不实现发送或留 TODO）：`token` 字段

---

## 4. 前端改造

### 4.1 设置页通道列表（P0，按设计稿）
页面结构（`views/settings/notify/index.vue` 重构）：
```
┌ 消息通知（h2）+ 统计 chip「X 个通道 · Y 个已启用」──────┐
├ 通道卡片列表（等高，见下方规格）                        │
│   [图标] 通道名 [状态chip]        [配置][测试] [启用]   │
│   [图标] 通道名 [状态chip]        [配置][测试] [启用]   │
│   [图标] 通道名 [状态chip]（未配置: 虚线边框, 去配置）  │
├ 发送记录表格（保留现状）                               │
└ 手动发送入口（保留现状，弹窗内通道下拉改为已启用通道）  │
```

**等高卡片统一规格（强制）**：
| 项 | 规格 |
|---|---|
| 卡片 | 容器内等宽，折叠态 `height: 68px`（`box-sizing: border-box`），圆角 12px，padding 16px，卡片间距 10px |
| 图标 | 36×36px，圆角 10px，`background: color-mix(primary 12%)` / 未配置用中性色 |
| 名称行 | 13.5px / weight 500；右侧状态 chip（已启用=success 色、已配置=中性、未配置=中性弱）同位置同尺寸 |
| 描述 | **固定单行**，`white-space: nowrap; overflow: hidden; text-overflow: ellipsis`（等高关键） |
| 操作区 | 右侧固定宽度、同列对齐：`[配置] [测试] [启用开关]`；未配置通道显示 `[去配置]` |
| 配置入口 | 卡片内**不展开**配置区（防高度参差）→ 点「配置」打开统一弹窗 |
| 数据来源 | `GET /api/notify/configs` + `GET /api/notify/channels` 合并渲染，**前端不硬编码通道列表**（图标用 lucide 名称映射） |

**配置弹窗（统一样式）**：标题 = 通道名；正文按 `fields` 定义渲染表单（Input/TextArea/Switch 自动映射，mono 字段用等宽字体）；底部：启用开关 + 「测试发送」+「保存」；不同通道仅字段内容不同，骨架一致。

### 4.2 全局发送组件（P1）
新增可复用能力，供任意模块"查询可用通知方式并调用发送"（G4）：

1. `src/components/notify/NotifySenderModal.vue`
   - props：`open / context(来源模块名，如 '任务中心') / defaultTitle / defaultContent`
   - 打开时调 `GET /api/notify/channels` → 仅列出 `enabled` 通道，单选卡片式选择（显示能力标签：@所有人 / Markdown）
   - 发送 → `POST /api/notify/send`（带所选 channel）→ 成功关闭并提示；失败展示错误
   - 无可用通道 → 空态：提示文案 +「去配置」按钮跳转 `/settings/notify`
2. `src/composables/useNotifySender.ts` — 函数式入口：`openNotifySender({ context, title, content })`，全局唤起弹窗
3. **试点接入**：任务中心页（`views/task-center/index.vue`）头部或操作列加「通知我」按钮，点击唤起组件

---

## 5. 实施顺序与依赖

| 阶段 | 内容 | 依赖 |
|---|---|---|
| P0 | 后端：模型多通道化 + 老库迁移 + channels/configs 接口 + test/send 扩展 + 测试适配 | 无 |
| P0 | 前端：设置页等高卡片列表 + 配置弹窗（数据驱动） | 后端 P0 |
| P1 | 前端：NotifySenderModal + useNotifySender + 任务中心试点 | 后端 P0 |
| P2 | 推广其他模块接入（小红书/资源搜索/首页） | P1 |

---

## 6. 验收标准

- [ ] 多通道可同时启用；任务完成/失败时**所有已启用通道**都收到推送，单通道失败不影响其他
- [ ] 列表页卡片在 2 / 3 / 5 个通道时均等高同构；浅色/深色主题正常
- [ ] 接入 PushPlus 演示通道仅需注册表加一行 + fields 定义，前端零改动
- [ ] `GET /api/notify/channels` 返回状态正确；任务中心「通知我」可查询通道并成功发送
- [ ] 后端 pytest 全绿（现有 66 用例适配后 + 新增用例）；前端 `vue-tsc` 零新增错误
- [ ] 无启用通道时：测试发送返回友好错误；发送组件显示空态引导

---

## 7. 参考文件

- 现状代码：`backend/app/common/{models/notification.py, services/notify_service.py, controllers/notify.py, schemas/notify.py}`、`backend/app/core/database.py`
- 现状页面：`frontend/apps/web-antd/src/views/settings/notify/index.vue`、`src/api/core/notify.ts`
- 现有测试：`backend/tests/test_notify.py`、`backend/tests/test_notify_serverchan.py`（66 用例）
- 设计稿（等高卡片列表 + 发送弹窗）已随对话提供，实现以其为视觉基准
