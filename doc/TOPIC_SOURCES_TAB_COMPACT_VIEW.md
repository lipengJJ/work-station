# 主题：创建向导 + 数据源 Tab 紧凑视图

> 状态：方案草案，待实施
> 主文件：
> - `frontend/apps/web-antd/src/views/hotlist/topics/index.vue`（列表 + 新建入口）
> - `frontend/apps/web-antd/src/views/hotlist/topics/components/TopicDetailPanel.vue`（详情，1107 行）
> - `frontend/apps/web-antd/src/views/hotlist/topics/components/TopicSourcePickerModal.vue`（源选择器，138 行）
> 涉及接口：`POST /hotlist/topics`、`PUT /hotlist/topics/{id}`、`POST /hotlist/topics/{id}/sources/batch`、`GET /hotlist/topics/{id}/sources`、`GET /hotlist/sources?group_id=`、`GET /hotlist/source-groups`
> 已确认：`hot_topic.py` 已 import `Boolean`；`TopicUpdateIn` 已存在（`schemas/topic.py:159`）；前端 `listHotlistSourcesApi(groupId?: number)` 支持按分组拉源。
> 触发反馈：
> 1. 新建主题只有一个填名称的小弹窗，建完直接掉进一个 4 页签的详情面板，用户不知道"还差什么才算配好"。
> 2. 主题详情「数据源」tab 把关联到该主题的全部源（本例 81 个）逐行铺开，用户只想看"这个主题现在用了哪些源"。

---

## 0. 本文档合并了两件事，因为它们是同一个根因

| 改造 | 内容 | 章节 |
| --- | --- | --- |
| A | 新建主题拆成三步向导，走完才算创建完成 | §3 |
| B | 详情页「数据源」tab 默认只显示已启用源的紧凑清单 | §4 |

根因是同一个：**这套界面没有区分「配置态」和「运行态」**。

- 创建一个主题时，用户关心的是"我要什么"——选哪些源、想看什么内容、什么时候推给我。
- 主题跑起来之后，用户关心的是"它现在怎么样"——哪些源坏了、贡献了多少条、上一期报告在哪。

现在这两组信息糊在同一套 UI 里：新建完直接扔进带健康状态、近 7 天贡献、cron 表达式的 81 行运维表格。这些数据在创建阶段**不仅无用，而且误导**——`hit_count_7d` 统计的是该源在**全局**近 7 天的产出（`list_topic_sources` 按 `HotItem.source_id` 聚合，与主题无关），新建主题时看到"Jina AI 近 7 天 26 条"很容易被理解成"这个主题已经有 26 条了"，实际是 0。

所以贯穿本文档的原则只有一句：

> **创建 = 选择器（只问"要不要"），管理 = 管理台（才谈"怎么样"）。**

---

## 1. 现状

### 1.1 新建路径

`topics/index.vue` 的 `openCreate()` / `submitCreate()`（69~103 行）：

```text
[+ 新建主题]
   ↓
Modal：名称 / slug / 描述          ← 只有 3 个字段
   ↓ 提交
createTopicApi()  →  主题立刻 enabled=true 入库
   ↓
直接打开 width="90%" 的详情 Drawer，落在「数据源」tab
```

问题：

- 建完就是 `enabled=true`，但此时**没有任何源、没有关注需求**，是个空壳主题。它会立刻出现在列表里显示"运行中"，而 `pending_sources` 又因为没关联源不会抓任何东西——状态在骗人。
- 用户被扔进一个 4 页签的面板，没有任何"还差 2 步"的提示。四个页签里「报告历史」根本不是配置项，是运行结果。
- 详情面板顶部那条 `① 数据源 ② 分析配置 ③ 推送设置 ④ 报告历史` 的**编号步骤条在假装自己是向导**（带序号、带完成态勾），实际行为是 Tab：可以任意乱点、无顺序约束、每页各自即时保存、没有终点。要么向导要么 Tab，不能又是又不是。

### 1.2 数据源 Tab

`activeStep === 'sources'`（模板 561~680 行）目前是：

```text
[从分组关联] [导入 OPML] [全开] [全关] [一键关闭失效源 (0)]      启用 81 个源

手动添加 (81)
┌────────────────────────────────────────────────────────────────┐
│ 源 / ID          健康状态   近 7 天贡献   抓取频率    本主题启用 │
├────────────────────────────────────────────────────────────────┤
│ Jina AI(@JinaAI_) ● 正常     26 条        0 */4 * * *   ●───   │
│ AI SDK(@aisdk)    ● 正常     50 条        0 */4 * * *   ●───   │
│ ...（共 81 行，全部展开）                                       │
└────────────────────────────────────────────────────────────────┘
```

`fetchSources()`（137~149 行）调 `listTopicSourcesApi(topicId)` → 后端 `list_topic_sources()`（`topic_service.py:293`）：查 `HotTopicSource` 关联表里这个主题下**所有曾经关联过的源**（不管当前 `enabled` 是开是关），逐条拼健康状态、近 7 天贡献数、cron。返回的每条都带 `topic_enabled: boolean`。

`sourceGroups`（151~174 行）按 `imported_from`（`manual` / `builtin` / `opml:xxx`）分组做小标题，**不是**按板块页的数据源分组分的——"从分组关联"选完源写库时 `imported_from` 统一写死成 `'manual'`，关联关系里不保留"当初从哪个分组勾的"。所以实际效果是唯一一组「手动添加（81）」，等于没分组。

问题：

- 81 行表格逐行读没有信息量。用户想知道"这个主题用了哪些源／一共几个"，不是每条源的健康状态明细（那更适合在「热点聚合 → 榜单」页的"管理源"抽屉里看，那边才是源的原生管理入口）。
- 5 列里有 3 列的取值 81 行完全相同（健康状态全"正常"、抓取频率全 `0 */4 * * *`、本主题启用全开）。一列所有行都一样，信息量就是零，却吃掉近一半表宽。
- 每行 ~85px（ID 独占一行是主因），一屏只能放 10 行，看完要滚 8 屏。
- 表格铺满，把"从分组关联 / 导入 OPML"这些真正高频的操作挤到最上面一条很窄的按钮行里，视觉上不分主次。
- 未来关联源到 200+ 时更长。

---

## 2. 目标

### 2.1 创建（§3）

1. 新建拆成 **3 步向导**：基本设置 → 主题设置 → 通知设置，逐步完成，每步校验通过才能"下一步"，最后一步"完成创建"。
2. 向导里**只出现配置项，不出现任何运行态数据**——不显示健康状态、近 7 天贡献、cron、最近抓取时间。
3. 走完向导的主题才是"运行中"；没走完的是"草稿"，列表里能区分、能续配、能丢弃。
4. 创建完成后进详情页，四个 Tab **平级独立编辑**，取消伪装成向导的编号步骤条。

### 2.2 数据源 Tab（§4）

1. 默认视图：只显示当前 `topic_enabled === true` 的源，紧凑排列，不带管理型字段。
2. 曾关联但已停用的源（`topic_enabled === false`）默认收起，但留入口，不丢信息。
3. "从分组关联 / 导入 OPML / 全开 / 全关 / 一键关闭失效源"入口保留，但不为了露出它们就先铺开全量表。
4. 需要精细管理（挑单个源开关、看健康状态、看 cron）时，走一个明确的"管理源关联"次级入口。

---

## 3. 改造 A：新建主题三步向导

### 3.1 流程与状态机

```text
[+ 新建主题]
   ↓
① 基本设置
   ├─ 主题名称（必填）
   ├─ 描述
   └─ 关联数据源组（多选下拉，至少选一个）
   ↓ 【下一步】= POST /hotlist/topics  → 拿到 topic_id
   ↓            + POST /topics/{id}/sources/batch 关联组内全部源
   ↓            主题落库：enabled=false, setup_done=false   ← 草稿
   ↓
② 主题设置
   ├─ 关注需求 interest_query（必填，语义检索的输入）
   ├─ 分析 Skill skill_key（可空 = 内置默认 Prompt）
   ├─ 匹配范围 similarity_threshold（严格/均衡/宽松）
   └─ 裁剪策略 digest_strategy（funnel / two_stage / simple）
   ↓ 【下一步】= PUT /hotlist/topics/{id}
   ↓
③ 通知设置
   ├─ 报告周期 digest_period（周报 / 日报）
   ├─ 生成时刻 digest_cron（由周期推导出的友好选择器，不让用户手写 cron）
   ├─ 生成后推送 report_notify_enabled
   └─ 通知渠道 report_notify_channel_ids（开启推送时必选）
   ↓ 【完成创建】= PUT /hotlist/topics/{id}
   ↓              enabled=true, setup_done=true          ← 运行中
   ↓
详情页（Tab 独立编辑）
   基本设置 / 数据源 / 主题设置 / 通知设置 / 报告历史
```

**关键决定：不引入 `status = draft | active`，改用布尔 `setup_done`。**

理由：库里已经有 `enabled` 字段，再加一个三态 `status` 会和它打架——`status=active` 且 `enabled=false` 该怎么解释？但也不能只用 `enabled`，因为"从没配完的草稿"和"配好了手动停用"是两回事，列表里必须分得开。两个正交的布尔刚好覆盖三种真实状态：

| `setup_done` | `enabled` | 列表显示 | 说明 |
| --- | --- | --- | --- |
| `false` | `false` | **草稿** · 继续配置 | 向导没走完 |
| `true` | `false` | 已停用 | 配好了，用户手动关的 |
| `true` | `true` | 运行中 | 正常状态 |

附带好处：`topic_service.pending_sources()` 只跑"被至少一个**启用中**主题启用的源"，草稿期间 `enabled=false`，**天然不会触发抓取**，不需要在调度里额外加判断。

老数据迁移时 `setup_done` 默认 `true`（现有主题都视为已配置完成）。

### 3.2 步骤 ①：基本设置

| 字段 | 控件 | 绑定 | 校验 |
| --- | --- | --- | --- |
| 主题名称 | `Input`，maxlength 64 | `name` | 必填，去空格后非空 |
| 描述 | `Input.TextArea` rows=2 | `description` | 可空 |
| 关联数据源组 | `Select mode="multiple"` | 见下 | **至少选一个** |

**数据源组下拉**：选项来自 `listSourceGroupsApi()`，label 用 `${g.name}（${g.source_count}）`。选定后：

```ts
// 把选中分组展开成 source_ids，再一次性关联
const ids = (await Promise.all(
  selectedGroupIds.map((gid) => listHotlistSourcesApi(gid)),   // 签名是 (groupId?: number)
)).flat().map((s) => s.id);
await batchSetTopicSourcesApi(topicId, { mode: 'set', source_ids: ids });
```

下拉下方给一行只读回显：`已选 2 个分组 · 共 93 个源`。**不列出具体源、不显示任何源的健康状态或贡献数**——这一步只回答"从哪些池子里捞"。

> 为什么用分组下拉而不是复用 `TopicSourcePickerModal`：向导要快。逐个勾 81 个源不是创建阶段该干的事，进详情页的「数据源」Tab 再精调。`TopicSourcePickerModal` 保持原样，作为详情页的精调入口。

校验不过时"下一步"置灰，并在字段下方给出原因（"至少选择一个数据源组，否则主题抓不到任何内容"）。

### 3.3 步骤 ②：主题设置

从现有「分析配置」tab（模板 684~860 行）里**只挑 4 项**进向导，其余全部留给详情页：

| 字段 | 控件 | 绑定 | 校验 |
| --- | --- | --- | --- |
| 关注需求 | `Input.TextArea` rows=4，maxlength 4000 | `interest_query` | **必填** |
| 分析 Skill | `Select allow-clear` | `skill_key` | 可空 = 内置默认周报 Prompt |
| 匹配范围 | `Radio.Group`（严格 0.5 / 均衡 0.35 / 宽松 0.2） | `similarity_threshold` | 默认均衡 |
| 裁剪策略 | `Radio.Group`（funnel / two_stage / simple） | `digest_strategy` | 默认 funnel |

`interest_query` 必填不是设计洁癖：后端生成报告时本来就要求它非空，向导里不拦，用户会在第一次生成报告时才发现主题配不全。

**不进向导、只在详情页出现的字段**（保持默认值即可跑通）：
`template_key`、`extra_question`、`retrieval_size`、`max_items`、`shortlist_size`、`fulltext_size`、`compare_with_previous`、`publish_enabled`、`publish_formats`、以及「检索预览」整块。

> 检索预览（`previewSemanticApi`）刻意不放进向导：它要打一次语义检索，新建主题时源刚关联、还没抓过，预览必然空手而归，反而制造焦虑。放在详情页调参时用才有意义。

### 3.4 步骤 ③：通知设置

| 字段 | 控件 | 绑定 | 校验 |
| --- | --- | --- | --- |
| 报告周期 | `Radio.Group`（周报 / 日报） | `digest_period` | 默认 weekly |
| 生成时刻 | 见下（周期驱动的友好选择器） | `digest_cron` | 必填 |
| 生成后推送摘要 | `Switch` | `report_notify_enabled` | 默认关 |
| 通知渠道 | `Select mode="multiple"` | `report_notify_channel_ids` | 开启推送时**至少选一个** |

**生成时刻不让用户手写 cron。** 现在详情页是一个裸 `Input`，让人填 `0 8 * * 1`——这是给机器看的。向导里按周期渲染两个下拉，再拼成 cron：

```text
周报：[周一 ▾] [08:00 ▾]   →  digest_cron = "0 8 * * 1"
日报：[08:00 ▾]            →  digest_cron = "0 8 * * *"
```

下方给一行人话回显：`每周一 08:00 生成本期报告`。详情页保留裸 cron 输入框给进阶用户。

**不进向导**：`hit_notify_*` 整套（实时命中推送）、`report_notify_time_start/end`（静默时段）。实时命中推送是进阶功能，新建时开它容易被消息淹没；静默时段在没开推送之前也无意义。两者都在详情页「通知设置」Tab 里配。

最后一个按钮是 **【完成创建】**，同时写 `enabled=true, setup_done=true`。旁边给一个次级链接 **【稍后再配，先存为草稿】**，只写 `setup_done=false` 不启用——不强迫用户为了退出而乱填渠道。

### 3.5 草稿与中途退出

第 ① 步"下一步"就已经落库，所以必须处理半成品：

- 关闭向导 Drawer 时，若 `setup_done === false`，弹确认：**保留草稿** / **丢弃并删除**。
- 列表页（`topics/index.vue`）的状态列按 §3.1 的三态表渲染；草稿行的主操作是「继续配置」，点击直接打开向导并**跳到第一个未完成的步骤**。
- 草稿主题不参与抓取（`enabled=false`，见 §3.1），也不出现在任何"启用中主题"的统计里。

### 3.6 后端改动

1. **`backend/app/hotlist/models/hot_topic.py`** 新增：

   ```python
   setup_done: Mapped[bool] = mapped_column(Boolean, default=True, index=False)
   """创建向导是否走完。False = 草稿（向导中途退出），列表里单独标记。
   与 enabled 正交：enabled 表示"要不要跑"，setup_done 表示"配没配完"。
   老库迁移默认 True——存量主题都视为已配置完成。"""
   ```

2. **`backend/app/core/database.py`** 加一个幂等迁移函数，写法与 `_ensure_hotlist_source_health_schema()` 一致：

   ```python
   def _ensure_hotlist_topic_setup_schema() -> None:
       """hot_topics 补 setup_done 列（幂等，老库兼容，默认 1）。"""
   ```

   并在 `init_db()` 里调用。

3. **`backend/app/hotlist/schemas/topic.py`**：`TopicIn` / `TopicUpdateIn` / `TopicOut` 各加 `setup_done`。`TopicIn` 默认 `True`，向导创建时前端显式传 `False`。

4. 其余接口（`batchSetTopicSourcesApi`、`updateTopicApi`）**不用改**，向导复用的就是详情页那套写接口。

### 3.7 前端改动

1. **新增 `TopicCreateWizard.vue`**（放 `views/hotlist/topics/components/`）。不要往 `TopicDetailPanel.vue` 里塞——它已经 1107 行，再加向导会失控。
2. `topics/index.vue`：`openCreate()` 从"打开 3 字段 Modal"改成"打开向导 Drawer"；`submitCreate()` 的逻辑搬进向导第 ① 步。列表加草稿状态列与「继续配置」入口。
3. `TopicDetailPanel.vue`：把顶部编号步骤条改成**普通 Tab**（去掉 `①②③④` 序号和完成态勾），并把「基本设置」（名称 / 描述）从「分析配置」里拆出来独立成一个 Tab，与向导的分步保持同构：

   ```text
   基本设置 | 数据源 | 主题设置 | 通知设置 | 报告历史
   ```

   「报告历史」不再参与编号——它是运行结果，不是配置步骤。
4. 向导内的表单校验用 `computed` 出一个 `canNext`，控制"下一步"的 `:disabled`，不要靠提交时 `message.warning` 兜底。

---

## 4. 改造 B：数据源 Tab 紧凑视图

### 4.1 默认态（紧凑清单）

```text
[从分组关联] [导入 OPML] [管理源关联 →]

已启用 81 个源
[Jina AI] [AI SDK] [Blog AI Weirdness] [Recraft] [Lovable] [cohere]
[orange.ai] [Milvus] [PromptLayer] [NotebookLM] [LovartAI] ...
```

- 用胶囊（chip）铺陈已启用源的名称，`flex-wrap`，不用表格。每个 chip 只显示 `record.name`，hover 用 Tooltip 补充 `record.id`。
- 源数量多时（比如 > 30）默认只显示前 N 个 + "还有 X 个，展开全部"，避免 chip 墙铺满整页；具体阈值实现时再定。
- 顶部操作行只保留"从分组关联""导入 OPML"两个高频入口 + 一个"管理源关联 →"次级链接（点开才看到全开/全关/一键关闭失效源和完整表格）。
- `topic.enabled_source_count === 0` 时的空态 `Alert` 保留（609~616 行原样保留）。

### 4.2 管理态

点"管理源关联"后展示原来那套东西：

- 恢复"全开 / 全关 / 一键关闭失效源"按钮行。
- 恢复完整表格（源 / ID、健康状态、近 7 天贡献、抓取频率、本主题启用开关），包含已停用但仍关联的源。

推荐用 **Drawer**（复用 `SourceManagerDrawer.vue` 已验证过的宽抽屉模式），而不是在 tab 内维护 `viewMode` 两态：

- `activeStep === 'sources'` 本身已嵌在"主题详情"这个 `width="90%"` 的 Drawer 里，再叠一层略重，但比把两态显示逻辑和其余几个 Tab 混在一起要干净。
- 全开/全关/一键关闭失效源本来就是低频运维动作，收进明确"进入管理态"的次级页面，符合"默认给结论、按需给细节"。
- 内层管理 Drawer 用**固定像素宽**（`900`~`1040`），不要再用百分比，避免叠加出双重不可控的宽度换算。

如果实现时觉得 Drawer 太重，退而求其次用 tab 内 `viewMode: 'compact' | 'manage'` 两态切换，两种都满足目标，由工作量决定。

### 4.3 管理态表格本身的问题（可与本次一起做）

管理态那张表照搬现状的话，§1.2 列的密度问题还在。按收益排序：

1. **压行高**：ID 移出主行（收进 Tooltip 或复制按钮），`py-3` → `py-1.5`，行高 ~85px 降到 ~40px，一屏从 10 行到 22 行。副行位置换成排障真正要看的：上游 host + 最近抓取时间。
2. **删"抓取频率"列**，恒定值提到顶部摘要行（"81 个源 · 全部正常 · 每 4 小时 · 最近 08:00"）；正常态只留一个 6px 圆点不带文字，**异常才展开**成彩色 badge。cron 转人话，且只在与分组默认值不同时显示。
3. **"近 7 天贡献"列加排序 + 条形**，默认降序，0 条标红并标"7 天零产出"——这是整张表唯一有决策价值的数字。（先确认大量正好 50 条是不是 feed 单次返回上限造成的截断，否则排序会失真。）
4. **加搜索框 + 状态筛选 chips**（全部 / 有产出 / 零产出 / 异常 / 已关闭）。81 行没有搜索是硬伤。
5. **分组维度从 `imported_from` 换成上游 host**（`adapter_params.url` 的 hostname），组头写"`api.xgo.ing` · 62 个源 · 近 7 天 2,840 条"。62/81 集中在一个第三方上游是这套系统最大的单点风险，界面上应该看得见。
6. **破坏性操作降权**："全关"一键关掉 81 个源却和"导入 OPML"视觉平级且无二次确认；数量为 0 的"一键关闭失效源（0）"直接不渲染。

### 4.4 两处已经和后端对不上的地方（顺手修）

- `staleIds`（`TopicDetailPanel.vue:141`）还在用 `consecutive_failures >= 5`，后端失效判定已改成 `permanent_failures`（见 `topic_service.list_stale_source_ids`）——现在一次 DNS 抖动仍会让这里显示一堆"失效"。
- 健康状态列还在显示 `失败×N`，没用上新的 `last_error_label`（"地址失效 404"/"上游整体不可用"/"域名解析失败"）。
- 源管理页已有行内「立即抓取」，这里没有——排障要跳走一个页面。

### 4.5 分组色点（可选加分项）

想让 chip 墙更有信息量，可在每个 chip 上叠一个小色点，颜色取自该源**当前**在板块页的分组颜色（`HotSource.group_id` → 分组 `color`，实时查，不依赖 `imported_from`，因为那个字段关联后就写死成 `manual`，不可靠）。工作量和收益需权衡，可放第二阶段，不阻塞主目标。

---

## 5. 不需要动的部分

- 后端 `list_topic_sources`、`batchSetTopicSourcesApi`、`disableStaleSourcesApi`、OPML 导入接口都不用改，紧凑态/管理态/向导复用同一份数据和同一套写接口，只是展示形态变了。后端唯一改动是 §3.6 的 `setup_done` 字段 + 幂等迁移。
- `TopicSourcePickerModal.vue` 保持原样，继续作为详情页的精调入口。
- `pickerOpen`（从分组关联）、`opmlOpen`（导入 OPML）两个已有弹窗不用动，紧凑态和管理态都能触发；操作完照旧 `fetchSources()` + `fetchTopic()` + `emit('changed')`。
- 「热点聚合 → 榜单」页的"管理源"抽屉（`SourceManagerDrawer.vue`）是全局源管理入口，跟"某个主题关联了哪些源"是两回事，不要混在一起改。

---

## 6. 验收标准

### 6.1 创建向导

- [ ] 点「新建主题」进入三步向导，不再是 3 字段 Modal。
- [ ] 第 ① 步未填名称或未选数据源组时，「下一步」置灰并给出原因。
- [ ] 第 ① 步「下一步」后主题已落库且 `enabled=false, setup_done=false`，列表显示为「草稿」。
- [ ] 草稿主题不触发抓取（`pending_sources` 不含其源）。
- [ ] 第 ② 步 `interest_query` 为空时「下一步」置灰。
- [ ] 第 ③ 步开启推送但未选渠道时「完成创建」置灰。
- [ ] 「完成创建」后主题变为 `enabled=true, setup_done=true`，列表显示「运行中」，并跳转到详情页。
- [ ] 向导任意一步关闭 Drawer，提示「保留草稿 / 丢弃并删除」，两个选择都工作正常。
- [ ] 列表里草稿行的「继续配置」能重开向导并落在第一个未完成的步骤。
- [ ] 向导内**不出现**任何源的健康状态、近 7 天贡献、cron 表达式、最近抓取时间。
- [ ] 生成时刻用周期驱动的下拉，不要求用户手写 cron；回显是人话（"每周一 08:00 生成"）。
- [ ] 老库启动自动补 `setup_done` 列，存量主题全部为 `true`，不被误判成草稿。

### 6.2 详情页

- [ ] 顶部改为平级 Tab，去掉 `①②③④` 序号；「基本设置」独立成 Tab。
- [ ] 打开「数据源」tab，默认看到已启用源的紧凑清单，不是 81 行开关表格。
- [ ] 已停用但仍关联的源不在默认视图占地方，通过「管理源关联」能看到。
- [ ] 「从分组关联」「导入 OPML」在默认视图就能点到，不用先进管理态。
- [ ] 「管理源关联」进入的视图与现在功能完全等价：全开/全关/一键关闭失效源 + 完整表格 + 逐条开关。
- [ ] `topic.enabled_source_count === 0` 时的空态提示保留且触发正确。
- [ ] 关联/取消关联源后，紧凑清单和 tab 上的「N 个源」角标都能正确刷新。
- [ ] 源数量 > 100 时紧凑清单不造成卡顿或过长单屏滚动。
- [ ] 管理态表格：行高 ≤ 45px、贡献列可排序、有搜索框、失效判定用 `permanent_failures`、失败原因显示 `last_error_label`。

---

## 7. 推荐实施顺序

分两条独立的线，互不阻塞，可并行也可先后：

**线 A · 创建向导**

1. 后端加 `setup_done` 字段 + 幂等迁移 + schema 透出（改动最小，先落地）。
2. 新建 `TopicCreateWizard.vue`，先把三步骨架和步骤间跳转做出来，每步先只接 `updateTopicApi`。
3. 接第 ① 步的分组下拉 → 展开 source_ids → `batchSetTopicSourcesApi`。
4. `topics/index.vue` 换入口、加草稿状态列与「继续配置」。
5. 中途退出的「保留草稿 / 丢弃」确认。
6. `TopicDetailPanel.vue` 步骤条改平级 Tab，「基本设置」拆出来。

**线 B · 数据源 Tab**

1. 加 `enabledSources` 计算属性，先把默认态的 chip 清单做出来（不动管理态代码，只是加一层简洁视图盖在上面）。
2. 把现有完整表格 + 批量操作按钮行整体挪到「管理源关联」入口之后（先用最简单的 `v-if` 验证交互，观感 OK 再决定要不要升级成独立 Drawer）。
3. 管理态表格按 §4.3 的 1、2 两条压密度（收益最大、改动最小），再做 3~6。
4. 顺手修 §4.4 的三处对不上。
5. 回归：从分组关联、导入 OPML、全开/全关、一键关闭失效源、单条开关，确认紧凑态与管理态数据联动刷新。
6. 视觉走查：chip 墙在源数量很少（1~2 个）和很多（80+）两种极端下都要过一遍。
