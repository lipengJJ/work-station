# AI 开发热点聚合 — 增量 PRD：AI 热点定时推送

> 本文为「AI 开发热点聚合」的**增量 PRD**，仅描述本次新增的「定时推送」能力。
> 既有功能、架构约定、模块风格以 `doc/AI_TRENDING_PRD.md` 与 `doc/AI_TRENDING_ARCHITECTURE.md` 为准，不重复描述。

| 项目信息 | 内容 |
|---|---|
| Language | 中文 |
| Programming Language | 与既有 ai_trending 模块一致：FastAPI + SQLAlchemy + APScheduler（后端）；Vue3 + Vben Admin / web-antd + ant-design-vue（前端）；SQLite |
| Project Name | `ai_trending` 模块内增量（新增表 `ai_trending_push_config` / `ai_trending_push_log`，路由 `/api/ai-trending/push/*`） |
| 原始需求 | 在 AI 热点模块新增「定时推送」：用户配置企业微信机器人 webhook，每天固定时间（可配，默认 09:00）自动汇聚当天热点 → AI 总结 Top10（每条 1-2 句摘要 + 原文链接）+ 整体趋势综述，推送到企业微信群，收到后点链接可查看原文；前端 AI 热点页提供推送开关与配置（开关、webhook URL、推送时间、Top N 条数）。 |
| 上游约定 | 复用 AI 网关（`app/common/services/ai_gateway/`，ProviderSpec 注册表 + `service.stream()`），API Key/模型统一走 `ai_config.get_ai_credentials()`；定时任务走 `app/core/scheduler.py` 单例 + `register_all_enabled_jobs()` 生命周期（参考 `ai_trending/services/scheduler_jobs.py`） |

---

## 1. 产品定义（增量）

### 1.1 Product Goals

**一句话**：让开发者/技术团队每天早上在企业微信群里自动收到一份「今天 AI 圈发生了什么」的日报——Top10 热点各带一句摘要与原文链接，外加整体趋势综述，点链接即看原文，无需打开工作台。

**三个衡量指标（增量）**：
1. **推送成功率**：近 7 天已启用配置的定时推送成功率 ≥ 95%（webhook 有效 + AI 降级兜底后仍失败算失败）。
2. **内容有效性**：推送消息中 AI 生成的 Top10 条目点击可达（原文 URL 有效）比例 ≥ 95%，摘要由 AI 生成或规则截断兜底，不允许空摘要条目。
3. **配置可用性**：用户在页面上配置后，次日即可在配置时间收到推送；webhook 配置错误能在 30 秒内通过「测试推送」或最近推送状态获知。

### 1.2 User Stories（新增 5 条）

1. 作为**开发者/技术团队负责人**，我希望每天固定时间（如 09:00）在企业微信群自动收到 AI 热点日报，以便上班前快速掌握当天 AI 圈动态，不用逐个打开 HN / GitHub / arXiv 等站点。
2. 作为**工作台用户**，我希望在「AI 开发热点」页用开关一键开启/关闭推送，并配置 webhook URL、推送时间、Top N 条数，以便按团队作息和关注粒度定制推送。
3. 作为**群成员**，我希望推送消息里每条热点包含 1-2 句摘要 + 原文链接 + 来源标识，以便直接在群里判断要不要点开、点开即达原文。
4. 作为**工作台用户**，我希望页面上能看到最近一次推送的状态（成功/失败/内容预览/失败原因），以便 webhook 配错或 AI 失败时能快速定位并修复。
5. 作为**工作台用户**，我希望在配置完成后能点击「测试推送」立刻验证 webhook 是否可用，以便不用等到第二天才发现配置有误。

---

## 2. 技术规范（增量）

### 2.1 需求池

**P0（必做）**
- [ ] 企微 webhook 推送通道：`POST {webhook_url}`，JSON body `{"msgtype":"markdown","markdown":{"content":...}}`；支持可选「加签」（机器人安全设置选了加签时，按企微规范拼 `timestamp` + `sign` 参数）；响应 `errcode==0` 视为成功，非 0 记录 `errcode/errmsg` 到日志与推送记录
- [ ] AI 总结生成：调 AI 网关（复用当前选中 provider 的 Key/模型，`ai_config.get_ai_credentials()`），生成 Top10（每条 1-2 句摘要 + 原文链接 + 来源）+ 整体趋势综述（2-4 句）；失败自动重试，重试仍失败则**规则降级**（直接用库内 `summary` 截断 80 字 + 链接），保证推送不中断
- [ ] 每日定时任务：APScheduler cron job（job id `ai_trending_push`），时间取配置 `push_time`（默认 09:00），每天一次；时间可配置，配置变更后重调度
- [ ] 前端开关+配置：AI 热点页新增「定时推送」配置卡片（开关、webhook URL 输入、推送时间选择、Top N 条数、保存/测试推送按钮、最近推送状态展示）
- [ ] 推送记录表：每次推送写入 `ai_trending_push_log`（成功/失败、错误信息、条目数、内容预览）

**P1（重要）**
- [ ] 手动测试推送按钮：点击后立即用当前配置发送一条测试消息（不改变每日定时），返回发送结果
- [ ] 推送失败重试策略：webhook 发送失败自动重试（如 5s/30s 退避 2 次）；AI 总结失败重试 + 规则降级（见 P0）
- [ ] 总结内容 prompt 可配置：系统/模块级提供默认 prompt，高级用户可自定义（存 config 表 `summary_prompt` 字段，前端 P1 提供文本域）

**P2（可选）**
- [ ] 多群推送：支持配置多个 webhook URL（一个配置多行/JSON 数组），同一份日报推送到多个群
- [ ] 定时推送历史列表页：分页展示所有推送记录（时间/状态/条目数/预览），支持查看详情与手动重发

### 2.2 数据模型草案

**表 `ai_trending_push_config`（单行配置，id 恒为 1）**

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | int | PK | 恒为 1（单行配置） |
| enabled | bool | 默认 false | 推送总开关 |
| webhook_url | str(1024) | | 企业微信机器人 webhook URL |
| webhook_secret | str(128) | 可空 | 加签 secret（机器人安全设置选了「加签」时必填）；为空则不签名 |
| push_time | str(5) | 默认 "09:00" | 每天推送时间（HH:MM） |
| top_n | int | 默认 10，范围 5-20 | 推送 Top N 条数 |
| summary_prompt | Text | 可空 | 自定义总结 prompt（P1；空则用默认） |
| created_at / updated_at | DateTime | | 时间戳 |

**表 `ai_trending_push_log`（推送记录）**

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | int | PK | 主键 |
| pushed_at | DateTime | index | 推送时间 |
| status | str(16) | index | `success` / `failed` / `degraded`（AI 失败用规则降级但仍推送成功） |
| error | Text | 可空 | 失败原因（webhook 错误 / AI 错误 / 超时），截断 500 字 |
| items_count | int | | 实际推送条数（= min(top_n, 当日热点数)） |
| summary_preview | Text | | 内容预览（综述前 200 字 + 首条摘要，前端卡片展示用） |
| created_at | DateTime | | 记录创建时间 |

> 注：消息完整 markdown 体量小（Top10 + 链接约 2-3KB），可只存 `summary_preview`；如 P2 需要「查看完整消息/重发」，可加 `message_full` Text 字段，暂不设计。

### 2.3 推送消息格式（企业微信 markdown）

企业微信机器人消息格式为 markdown，`content` 上限 **4096 字节**。推荐模板：

```
# 🚀 AI 开发热点日报 2026-08-16

## 📊 今日趋势综述
{AI 生成的 2-4 句整体趋势}

## 🔥 Top 10 热点
1. **{标题}**（{来源} · {热度}）
   > {1-2 句摘要}
   [查看原文]({url})

2. **{标题}**（{来源} · {热度}）
   ...
```

要点：
- 每条热点固定 3 行结构（标题行 + 摘要引用行 + 原文链接行），链接可点击直达原文。
- 来源标识用小写短码或中文名（HN / GitHub / arXiv / HF / InfoQ / 36氪），与热榜页来源 Tab 一致。
- 内容超 4096 字节时：优先截断摘要长度，其次减少条数（不低于 top_n 的 50%），保证消息可发送。
- 若机器人安全设置配置了「自定义关键词」，推送内容必须包含该关键词，否则企微返回 `errcode=93000`——见 4. 待确认问题。

### 2.4 API 草案（增量，全部 `Depends(get_current_user)`）

```
GET  /api/ai-trending/push/config
     → { enabled, webhook_url, webhook_secret_set, push_time, top_n, summary_prompt }
     # webhook_url 明文返回（当前单用户本地部署）；webhook_secret 只返回是否已设置（*_set），不回显原文

PUT  /api/ai-trending/push/config          # 保存配置；webhook_url 必填校验（https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...）
     body: { enabled, webhook_url, webhook_secret?, push_time, top_n, summary_prompt? }
     → 保存后的 config（同 GET）；若 enabled 从关→开或 push_time 变化，同步重调度定时任务

POST /api/ai-trending/push/test            # P1：立即用当前配置发送测试消息（不写入每日记录？写一条 type=test 的 log 亦可）
     → { sent: true, message } | 400 { detail: "webhook 未配置或格式错误" }

GET  /api/ai-trending/push/latest          # P0：最近一次推送记录（卡片展示最近推送状态用）
     → { id, pushed_at, status, error, items_count, summary_preview } | null

GET  /api/ai-trending/push/logs?page=&page_size=   # P2：推送记录分页
     → { items: [...], total, page, page_size }
```

### 2.5 定时任务设计（增量）

- **job id**：`ai_trending_push`（前缀 `ai_trending_`，`replace_existing=True`）。
- **注册/重调度**：`register_all_enabled_jobs()` 中新增——读取 `ai_trending_push_config`，若 `enabled` 且 `webhook_url` 非空则按 `push_time` 注册 cron（`hour=HH, minute=MM`）；配置变更时由 PUT 接口触发重调度（幂等）。`enabled=false` 时确保 job 不注册/被移除。
- **执行体**（调度器线程，`SessionLocal()` 自开自关，参考 `scheduler_jobs._run_source_job`）：
  1. 读配置：未启用 → 直接 return；
  2. 取热点：按 `fetched_at >= 当日 00:00` 且 `heat_score DESC` 取前 `top_n` 条（「当天」以入库时间为准，避免跨源发布时间口径不一致）；
  3. AI 总结：调 AI 网关生成 Top10 摘要 + 综述（重试 2 次，退避 5s/15s）；失败 → 规则降级；
  4. 组 markdown → 发送 webhook（失败重试 2 次，退避 5s/30s）；
  5. 写 `ai_trending_push_log`（success / degraded / failed）。
- **时区**：沿用调度器默认（服务器本地时区），与现有 cron 一致。

### 2.6 AI 网关调用模式（对齐现有使用方）

- 使用 `app/common/services/ai_config.get_ai_credentials(db)` 拿当前选中 provider 的 `(provider, api_key, model, thinking_enabled)`，**不在 controller/scheduler 里硬编码厂商**（与 xhs/stock 调用模式一致）。
- 组装 `AIRequest(provider=..., model=..., system_instruction=总结prompt, messages=[{role:"user", content: 当日热点JSON}])`，经 `ai_gateway_service.stream(request, api_key)` 消费事件流（`EVENT_DELTA` 累积文本 / `EVENT_ERROR` 判失败）。
- 若 AI 网关不可用（未配置 Key），**仍走规则降级推送**并标记 `degraded`（webhook 是独立于 AI 的通道，不应因 AI 未配置而中断推送）。

### 2.7 UI 设计稿（增量：AI 热点页「定时推送」配置卡片）

在「AI 开发热点」页热榜列表上方（操作栏下方）新增一张配置卡片（暗色卡片，风格与既有页面一致）：

```
┌─────────────────────────────────────────────────────────────┐
│ ⚙ 定时推送（企业微信群日报）                      [开关 Switch]│
│                                                             │
│  Webhook URL  [https://qyapi.weixin.qq.com/cgi-bin/webhook/…]│
│  加签 Secret  [••••••••]  （可选，机器人选了「加签」时填）     │
│  推送时间      [🕘 09:00]      Top N 条数  [10]              │
│                                                             │
│  [保存]  [测试推送]             最近推送：成功 · 今天 09:00 ·  │
│                                 10 条 · 预览…（失败时红色警示）│
└─────────────────────────────────────────────────────────────┘
```

- 开关：默认关；打开时若 webhook 为空，保存时表单校验提示「请先填写 Webhook URL」。
- 测试推送按钮（P1）：点击后调用 `POST /push/test`，结果用 message 提示成功 / 错误原因（如 errcode 93000 关键词不匹配）。
- 最近推送状态（P0）：调用 `GET /push/latest`，展示 `状态徽标 + 时间 + 条数 + 预览截断`；failed 显示红色 Alert 与 error 摘要。
- 提示文案（信息帮助）：附企微机器人创建指引链接，说明 webhook 获取方式与「加签/关键词」安全设置的关系（见 4）。

### 2.8 文件结构（增量）

```
backend/app/ai_trending/
├── models/
│   ├── __init__.py                  [修改] 导出 PushConfig / PushLog
│   ├── push_config.py               [新建] AiTrendingPushConfig ORM（单行）
│   └── push_log.py                  [新建] AiTrendingPushLog ORM
├── schemas/
│   ├── __init__.py                  [修改]
│   └── push.py                      [新建] PushConfigIn/Out、PushTestOut、PushLogOut
├── services/
│   ├── __init__.py                  [修改]
│   ├── push_service.py              [新建] 组消息 → AI 总结 → webhook 发送 → 写 log
│   ├── push_webhook.py              [新建] 企微 webhook 客户端（markdown 组装、加签、发送、重试、errcode 解析）
│   └── scheduler_jobs.py            [修改] register_all_enabled_jobs() 注册/重调度 ai_trending_push
└── controllers/
    ├── __init__.py                  [修改]
    └── push.py                      [新建] /api/ai-trending/push/* 路由

frontend/apps/web-antd/src/
├── api/core/ai-trending.ts          [修改] 新增 push config/test/latest/logs 请求函数
└── views/ai-trending/index.vue      [修改] 新增「定时推送」配置卡片
```

### 2.9 与既有约定的对齐

- 错误语义：400 参数错误 / 404 不存在 / 429 限频（如测试推送限频） / 502 上游失败。
- 日志：`loguru`，正常 `logger.info`、异常 `logger.exception`；webhook 发送成功/失败必须留痕。
- 时间：`datetime.now(timezone.utc)` 存储；`push_time` 为纯 HH:MM 配置串，调度时按服务器本地时区解析。
- SQLite 并发：调度器线程内 `SessionLocal()` 自开自关，不跨线程共享 Session。
- 敏感信息：`webhook_url`/`webhook_secret` 属敏感配置，写入不落日志、API 不回显 secret 明文。

---

## 3. 验收口径（增量）

- 配置页保存后，次日 `push_time` 触发推送；`ai_trending_push_log` 新增一条 `success` 记录，`items_count = min(top_n, 当日热点数)`。
- 推送消息在企微群里可正常渲染：Top N 条标题 + 摘要 + 可点击原文链接；点击链接在新窗口打开原文。
- webhook URL 无效时：定时推送记录 `failed` + error 含 errcode/errmsg；页面卡片展示失败状态与原因。
- 未配置 AI Key 或 AI 调用失败：推送仍成功发出（规则降级），log 标记 `degraded`。
- `enabled=false` 或 `webhook_url` 为空：不产生定时推送，也不报错。

---

## 4. 待确认问题（Open Questions）

1. **企微机器人「自定义关键词」问题**：企业微信群机器人创建时可配置安全设置——「自定义关键词 / 加签 / IP 段」，三种可任选或都不选（仅建议至少选一项）。若用户配置了「自定义关键词」，推送内容必须包含该关键词，否则企微返回 `errcode=93000`（无效 webhook / 关键词不匹配）。**现状与对策**：企微对 markdown 消息同样强制关键词校验（不是 markdown 类型特有的问题，是所有消息类型都校验）；建议在配置页增加一个可选「关键词」字段，用户在机器人里配置了什么关键词就填什么，消息标题自动内嵌该关键词；不填则按未配置关键词处理。**需确认**：是否接受「加一个可选关键词字段」的方案，还是 P1 再处理（先用文案提示用户避免配置关键词）？
2. **推送失败通知方式**：每日定时推送失败时，除页面状态外，是否需要额外的失败通知？建议 P0 仅记录 + 页面展示；P1 可选「失败后立即重发一条失败告警消息到同一群」（若 webhook 本身可达但 AI 失败则此告警也能达）。是否接受？
3. **「当天热点」口径**：以入库时间 `fetched_at` 当日 00:00 起算（推荐，口径统一、避免空推送），还是以原文发布时间 `published_at` 当日 00:00 起算？后者可能导致部分来源（如 GitHub 每日更新）当日 0 点后无新条目而推送内容稀疏。
4. **时区**：`push_time` 按服务器本地时区解释（与现有 cron 一致），是否需要支持用户配置时区？本地单机部署建议不引入时区字段。
5. **AI 厂商**：AI 总结复用系统「AI 模型配置」当前选中的 provider（gemini/deepseek），还是固定某个厂商？建议复用当前 provider（用户已在系统配置页选好，无需额外配置）。
6. **webhook 敏感信息存储**：`webhook_url`/`webhook_secret` 明文存 SQLite（本地单用户部署可接受），是否需要脱敏/加密？建议明文 + 接口不回显 secret，够用。
