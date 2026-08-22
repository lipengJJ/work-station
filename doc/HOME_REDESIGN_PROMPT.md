# 工作台首页视觉重构任务书（交付给 DeepSeek 执行）

> 目标文件：`frontend/apps/web-antd/src/views/home/index.vue`（现 524 行）
> 参考设计：Eclipse Dashboard（用户提供截图，见 §一 设计语言拆解）
> 技术栈：Vue3 + TypeScript + Tailwind + Ant Design Vue（Vben Admin）
>
> **本次只改视觉与布局，不改数据接口**。`getHomeApi()` / `getHomeStorageApi()`
> 返回结构保持不变，所有字段都要继续用上（见 §四 数据映射表）。

---

## 一、参考设计的语言拆解

必须先理解「为什么好看」，再动手，否则会做成"加了圆角的旧页面"。

### 1.1 三条核心规则（与现有代码正好相反，是本次改造的主要工作）

| # | 参考设计 | 现有代码 | 必须改 |
|---|---|---|---|
| 1 | **零边框、零阴影**，靠三层背景色差分层：页面底 → 卡片 → 卡片内元素 | 每个卡片都是 `border border-border ... shadow-sm` | 全部去掉 `border-*` 和 `shadow-*` |
| 2 | **单色相**：整页只有一个绿色相 + 中性灰，深浅变化承担全部区分职责 | KPI 用了蓝 `#3b82f6` / 黄 `#eab308` / 绿 `#22c55e` / 青 `#06b6d4` / 紫 `#8b5cf6` 五个色相 | 收敛到一个绿色相的深/中/浅三档 |
| 3 | **大圆角**：卡片 20–24px，内部元素 12–16px | 卡片 `rounded-2xl`(16px)，Hero `rounded-3xl` | 卡片统一提到 20–24px |

> 规则 1 是这套设计"高级感"的真正来源。边框 + 阴影会让界面显得碎；
> 纯色块分层显得整。**不要保留 hover 时的 `shadow-lg` 和 `-translate-y-1`**，
> 参考设计里没有任何位移动效，改成背景色轻微加深即可。

### 1.2 排版

- 页面主标题**超大 + 黑体 + 带句点**：`工作台.` —— 句点是这套设计的签名，保留
- 卡片标题：18–20px 粗体，比现在的 `text-sm font-bold`(14px) 明显大
- 数据数字：**深绿色 + 粗体 + tabular-nums**，是页面视觉重心
- 辅助标签：11–12px 中性灰，弱化

### 1.3 组件形态

- **指标块**：`圆角方形色块（内含图标）+ 右侧两行（小标签 / 大数字 + 涨幅）`，横向排布
- **柱状图**：双序列并排，柱顶圆角（`rx=4`），深绿 + 浅绿
- **环形图**：多层同心圆，中心一个大百分比数字
- **深色 CTA 卡片**：墨绿灰底 + 浅绿胶囊按钮，用来打破整页的浅色节奏
- **按钮**：胶囊形（`rounded-full`），不是圆角矩形

---

## 二、色板 Token（**必须走 CSS 变量，不要硬编码**）

⚠️ **关键约束**：工作台当前在用暗色主题（其他页面截图为深色背景），
而参考设计是浅色。**不能直接套用参考图的色号**，必须两套并存。

在 `views/home/index.vue` 的 `<style scoped>` 里定义局部作用域变量
（**不要改全局主题变量**，避免影响其他页面）：

```css
.home-eclipse {
  /* ---- 亮色（参考设计取样近似值）---- */
  --hm-page:        #E5E5E5;  /* 页面底 */
  --hm-card:        #EDECE7;  /* 卡片底（比页面底更浅且偏暖）*/
  --hm-inner:       #E3E2DC;  /* 卡片内元素底 */
  --hm-ink:         #2B3A45;  /* 标题文字：深蓝灰 */
  --hm-muted:       #8A8F8A;  /* 辅助文字 */

  --hm-accent:      #1A4D1A;  /* 主强调：深墨绿（数字、主序列柱）*/
  --hm-accent-mid:  #5C8A52;  /* 中绿：环形图中层 */
  --hm-accent-soft: #A9C89B;  /* 浅绿：次序列柱、按钮底、图标块底 */

  --hm-dark-card:   #3D453D;  /* 深色 CTA 卡片底 */
  --hm-dark-text:   #F0EFEA;  /* 深色卡片上的文字 */
}

/* ---- 暗色：保持同一套语义，换明度 ---- */
.dark .home-eclipse {
  --hm-page:        #141614;
  --hm-card:        #1E211E;
  --hm-inner:       #262A26;
  --hm-ink:         #E8EAE6;
  --hm-muted:       #8A928A;

  --hm-accent:      #7DB86A;  /* 暗色下深墨绿看不见，抬到中亮绿 */
  --hm-accent-mid:  #5C8A52;
  --hm-accent-soft: #35502E;  /* 浅绿在暗色下反过来变成深底 */

  --hm-dark-card:   #2A2E2A;
  --hm-dark-text:   #E8EAE6;
}
```

**暗色的关键调整**（照抄参考色号会瞎）：

- `--hm-accent` 从深墨绿 `#1A4D1A` 抬到 `#7DB86A`。深绿在深色底上对比度不足 2:1，数字会看不清。
- `--hm-accent-soft` 语义反转：亮色下它是"浅绿前景"，暗色下变成"深绿底色"。
  柱状图第二序列在暗色下应该用 `--hm-accent-mid` 而不是 soft。
- 校验：所有文字与其背景的对比度不低于 **4.5:1**，大号数字不低于 **3:1**。
  改完用浏览器 DevTools 的对比度检查器逐个过一遍关键文字。

---

## 三、布局重构

现在是**单列纵向堆叠**（Hero → KPI 行 → 存储面板 → 图表行 → 运行中任务）。
改成参考设计的**左 2/3 + 右 1/3 双列**：

```
┌──────────────────────────────────────────────────────────────┐
│  工作台.        [搜索框]  [时间范围]        [图标组] [用户]    │  ← 页头
├──────────────────────────────────┬───────────────────────────┤
│ ① 概览（横向 4 指标）             │ ③ 存储使用                 │
│                                  │   （柱状 + 底部数值）       │
├──────────────────┬───────────────┤                           │
│ ② 任务趋势        │ ② 成功率环形   ├───────────────────────────┤
│   （双序列柱状）   │  （大百分比）  │ ④ 运行中任务               │
│                  │               │   （纵向长列表，可滚动）    │
├──────────────────┴───────────────┤                           │
│ ⑤ 系统信息（深色 CTA 卡片）        │                           │
└──────────────────────────────────┴───────────────────────────┘
```

Tailwind 栅格：

```html
<div class="grid grid-cols-1 gap-5 xl:grid-cols-[1.9fr_1fr]">
  <div class="flex flex-col gap-5"><!-- 左列 ①②⑤ --></div>
  <div class="flex flex-col gap-5"><!-- 右列 ③④ --></div>
</div>
```

响应式：`xl` 以下退回单列，右列内容跟在左列后面。

### 3.1 页头

替换现有的 Hero（带两个 `blur-3xl` 光晕的那块）——参考设计没有光晕，**整块删掉**：

```html
<div class="mb-6 flex flex-wrap items-center justify-between gap-4">
  <h1 class="text-4xl font-black tracking-tight" style="color: var(--hm-ink)">
    工作台<span style="color: var(--hm-accent)">.</span>
  </h1>
  <div class="flex items-center gap-3">
    <!-- 时间范围选择器：胶囊形，日历图标 + 两行文字（标签 / 当前范围）-->
    <!-- 刷新按钮 + 当前日期 -->
  </div>
</div>
```

句点用强调色，是参考设计的签名细节。

---

## 四、数据映射（**所有现有字段都要继续用上，不许丢**）

| 参考设计的区块 | 改造后承载 | 数据来源 |
|---|---|---|
| Overview 四指标 | ① 概览 | `summary.total_tasks` / `running_count` / `today_new` / `today_done` |
| Visitors 双序列柱状图 | ② 任务趋势 | `trend[]` 的 `created` / `finished`（现有 `trendChart` 计算逻辑可复用） |
| Reviews 环形 85% | ② 成功率环形 | `summary.success_rate`，中心显示百分比，下方 `success_count / (success+failed)` |
| Server Status 柱状 | ③ 存储使用 | `storage.db_size` / `storage_size`，底部三个计数 `note_count` / `comment_count` / `task_count` |
| Messages 列表 | ④ 运行中任务 | `running_tasks[]`（现有卡片网格改成纵向列表） |
| Current Plan 深色卡片 | ⑤ 系统信息 | `storage.structured_count` / `report_count` + 快捷入口按钮 |

### 4.1 ① 概览（Overview 样式）

一张卡片内横向排 4 个指标，每个是「圆角方块图标 + 标签 + 大数字 + 涨幅」：

```html
<div class="rounded-[22px] p-6" style="background: var(--hm-card)">
  <div class="mb-5 text-lg font-bold" style="color: var(--hm-ink)">概览</div>
  <div class="grid grid-cols-2 gap-6 md:grid-cols-4">
    <div class="flex items-center gap-3.5">
      <div class="flex size-12 shrink-0 items-center justify-center rounded-2xl"
           style="background: var(--hm-accent-soft); color: var(--hm-accent)">
        <component :is="icon" class="size-6" />
      </div>
      <div class="min-w-0">
        <div class="text-xs" style="color: var(--hm-muted)">任务总数</div>
        <div class="text-3xl font-black tabular-nums" style="color: var(--hm-accent)">897</div>
        <div class="text-[11px]" style="color: var(--hm-muted)">全部模块累计</div>
      </div>
    </div>
    <!-- ×4 -->
  </div>
</div>
```

**四个图标块用同一个绿色底**，不要再给每个指标配不同颜色——这是 §1.1 规则 2。
区分靠图标本身（`Database` / `Activity` / `PlusCircle` / `CheckCircle2`），不靠颜色。

「成功率」从 KPI 行移出，独立成环形图（见 4.3），因为它是比率不是计数，
和其他四个放一起量纲不一致。

### 4.2 ② 任务趋势（Visitors 样式）

复用现有 `trendChart` 计算逻辑，只改绘制样式：

- 柱宽从 10 加到 **14–16**，柱顶圆角 `rx="4"`
- 双序列并排间距 3–4px
- 颜色：创建 = `var(--hm-accent)`，完成 = `var(--hm-accent-soft)`（暗色下用 `--hm-accent-mid`）
- **保留水平网格虚线**（参考图有），去掉纵向轴线
- Y 轴刻度标签放左侧，X 轴日期标签放底部，都用 `--hm-muted`
- 图例移到卡片右上角：两个小圆点 + 文字（"创建" / "完成"）
- 卡片标题 `任务趋势` 用 20px 粗体

### 4.3 ② 成功率环形（Reviews 样式）

**现有的状态分布多段环形改掉**——参考设计是"一个大百分比"的表达，信息密度更低但更有冲击力。
状态分布的四个数字改放在环形下方一行小字。

```
外层圆环：--hm-accent-mid，完整一圈（底）
进度弧：  --hm-accent，按 success_rate 绘制，stroke-linecap="round"
内层圆环：--hm-accent-soft，装饰性同心圆
中心：    大号百分比数字（36px+ 黑体，--hm-accent）
下方：    "成功率" 标签 + 一条进度条 + "N 成功 / M 完成"
```

参考图的环形是**三层同心圆**（外深绿细环 + 中浅绿粗环 + 内白圈），这个层次感要做出来，
不要只画一个单环。

### 4.4 ③ 存储使用（Server Status 样式）

参考图是「一排高矮不一的圆角柱 + 底部标签」。映射：

- 两根柱子：数据库 / 素材，高度按各自占合计的比例
- 柱内居中显示数值（`formatBytes` 结果），字号 14px 粗体
- 柱底下方一行：笔记 / 评论 / 任务 三个计数
- 柱子圆角 `rounded-2xl`，深绿 + 浅绿交替
- **删掉现有的存储趋势折线图**（`storageChart` 那块 SVG）——参考设计右列没有折线，
  且双列布局下右列宽度放不下折线图。趋势数据保留在接口里，以后要看可以做成 tooltip。

> 如果你觉得折线图有价值不想删，可以移到左列 ② 那一行作为第三张小卡片，
> 但**不要塞进右列**，宽度不够会挤成一团。

### 4.5 ④ 运行中任务（Messages 样式）

从「300px 宽的卡片网格」改成「纵向长列表」：

```html
<div class="rounded-[22px] p-6" style="background: var(--hm-card)">
  <div class="mb-4 text-lg font-bold" style="color: var(--hm-ink)">运行中任务</div>
  <div class="flex max-h-[520px] flex-col gap-4 overflow-y-auto">
    <div class="flex cursor-pointer items-start gap-3 rounded-2xl p-3 transition-colors hover:bg-[var(--hm-inner)]">
      <!-- 左：圆角方形类型标识（采集/补抓/追踪 三种图标，同色底）-->
      <div class="size-10 shrink-0 rounded-xl" style="background: var(--hm-accent-soft)">…</div>
      <div class="min-w-0 flex-1">
        <div class="truncate text-sm font-bold" style="color: var(--hm-accent)">{{ t.title }}</div>
        <div class="truncate text-xs" style="color: var(--hm-muted)">{{ phaseText(t) }}</div>
        <!-- 细进度条：高度 4px，圆角，--hm-accent 填充 -->
        <div class="mt-1.5 text-[11px]" style="color: var(--hm-muted)">14:22 开始 · 12/81</div>
      </div>
    </div>
  </div>
</div>
```

参考图的 Messages 是「头像 + 标题 + 两行摘要 + 时间」，这里对应
「类型图标 + 任务名 + 阶段文字 + 进度条 + 时间」。保留现有的
`Progress` 组件也可以，但要把 antd 默认蓝色改成 `--hm-accent`。

保留现有的 `pulse-dot` 呼吸动效（运行中状态点），这是有信息量的动效，不是装饰。

### 4.6 ⑤ 系统信息（Current Plan 深色卡片样式）

整页浅色需要一块深色来打破节奏，放左列底部：

```html
<div class="rounded-[22px] p-7" style="background: var(--hm-dark-card); color: var(--hm-dark-text)">
  <div class="flex items-center justify-between gap-6">
    <div>
      <div class="text-sm opacity-70">当前数据</div>
      <div class="text-4xl font-black">{{ formatBytes(总占用) }}</div>
      <div class="mt-1 text-xs opacity-60">数据库 + 素材合计</div>
      <ul class="mt-4 space-y-1.5 text-sm">
        <li>· 结构化笔记 {{ storage?.structured_count }} 篇</li>
        <li>· 分析报告 {{ storage?.report_count }} 份</li>
      </ul>
    </div>
    <div class="flex flex-col items-center gap-4">
      <!-- 装饰性图标（HardDrive 或勋章样式的圆形描边图标）-->
      <button class="rounded-full px-6 py-3 font-bold"
              style="background: var(--hm-accent-soft); color: var(--hm-accent)">
        进入任务中心 →
      </button>
    </div>
  </div>
</div>
```

---

## 五、必须删除的现有元素

| 元素 | 位置 | 原因 |
|---|---|---|
| Hero 区两个 `blur-3xl` 光晕 div | 页头 | 参考设计无光晕，且与扁平色块语言冲突 |
| 所有 `border border-border` | 全部卡片 | §1.1 规则 1 |
| 所有 `shadow-sm` / `hover:shadow-lg` | 全部卡片 | 同上 |
| `hover:-translate-y-1` / `hover:-translate-y-0.5` | KPI 卡、任务卡 | 参考设计无位移动效，改为 hover 背景加深 |
| KPI 卡底部的渐变色条 | KPI 卡 | 五色渐变与单色相冲突 |
| 存储趋势折线 SVG（`storageChart` 整块） | 存储面板 | 右列宽度不够，见 4.4 |
| 状态分布的四段环形 | 图表行 | 改为成功率单值环形，见 4.3 |

`storageChart` 的计算逻辑（`computed`）可以先注释保留，方便以后恢复；
但 `<template>` 里的 SVG 要删干净，不要留死代码。

---

## 六、验收标准

- [ ] 整页**看不到任何 border 和 box-shadow**，层次完全靠背景色差
- [ ] 整页只有**一个绿色相**（深/中/浅三档）+ 中性灰，无蓝/黄/青/紫
- [ ] 主标题是「工作台.」，句点为强调色
- [ ] 布局在 `xl` 及以上为左 2/3 + 右 1/3；`xl` 以下正确退回单列且不出现横向滚动
- [ ] **切换到暗色主题后可读**：所有文字对比度 ≥ 4.5:1，大号数字 ≥ 3:1，
      深绿色数字在暗色下不糊
- [ ] 所有原有数据字段仍在页面上有展示位置（对照 §四 映射表逐项确认）
- [ ] 5 秒轮询与 30 秒存储轮询逻辑不变，数据刷新时无闪烁
- [ ] 运行中任务为空时 `Empty` 占位仍正常
- [ ] `pnpm --filter @vben/web-antd run typecheck` 零错误
- [ ] 浏览器缩放到 1280px 宽和 1920px 宽各截一张图，布局都不塌

---

## 七、禁止事项

1. **不要改全局主题变量**（`--primary` 等）。色板定义在 `.home-eclipse` 局部作用域，
   避免波及股票、小红书、热点聚合等其他页面。
2. **不要硬编码参考图的十六进制色号到 template 里**，全部走 `var(--hm-*)`，
   否则暗色主题下必然出问题。
3. **不要改后端接口和 `api/core/workbench.ts`**。这是纯前端视觉改造。
4. **不要因为好看就丢数据**。§四 映射表里的每个字段都要有落点，
   删展示位置之前先在表里找到替代位置。
5. **不要引入新的图表库**（ECharts / Chart.js）。现有 SVG 手绘方案够用，
   引库会让首屏体积翻倍，且样式定制反而更麻烦。
6. **不要加自定义字体文件**。参考图用的是几何无衬线（Poppins 一类），
   但中文字形会不匹配，用现有的 `display-font` 栈即可。

---

## 八、建议的提交拆分

```
refactor(home): 首页色板 token 化，去边框去阴影，改为色块分层
refactor(home): 首页改双列布局，概览/趋势/成功率/存储/任务分区重排
feat(home): 成功率环形图与深色系统信息卡片
```
