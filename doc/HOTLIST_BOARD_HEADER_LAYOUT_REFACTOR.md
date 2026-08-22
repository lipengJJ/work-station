# 热点聚合榜单页：源管理能力融合优化方案

> 状态：方案修订版，待实施  
> 主页面：`frontend/apps/web-antd/src/views/hotlist/board/index.vue`  
> 能力来源：`frontend/apps/web-antd/src/views/hotlist/sources/index.vue`  
> 原则：颜色沿用现有主题；布局参考需求图片；下方新闻展示保持不变

## 1. 最终目标

榜单页上半区不再展示“榜单条目 / 数据源 / 异常源”统计，也不再保留原 Hero 卡片。改为一个可直接搜索榜单、管理及筛选数据源的工作区：

1. 顶部保留“热点聚合”标题与说明。
2. 标题下方左侧是一条大搜索框，右侧复用源管理页的三个操作：批量导入 OPML、分组管理、新建 RSS 源。
3. 搜索/操作行下方展示用户创建的数据源分组，如“AI 工具链”等。
4. 点击分组直接过滤下方榜单新闻，不在上半区展开源列表。
5. 下方排序、“只看命中”、新闻表格、分页和详情保持不变。

这不是把源管理页的整张源表复制到榜单页，而是把高频入口和分组导航融合到榜单页。源级启停、立即抓取、批量移动、删除等重操作继续由源管理明细承载。

## 2. 目标布局

```text
热点聚合
中文热榜 + 技术源统一排名，按权重实时聚合

[ 🔍 搜索榜单标题、摘要或来源……            ] [批量导入 OPML] [分组管理] [＋ 新建 RSS 源]

▦ 数据源分组
[全部] [AI 工具链 12] [国内热榜 8] [科技媒体 15] [未分组 3] ...

[按权重] [只看命中]                                        ← 保持原筛选能力
[新闻榜单表格……]                                           ← 保持原状
```

桌面端搜索框占主要宽度，三个操作按钮按内容宽度排列。不要再出现统计卡、统计长条或悬浮在页面最右侧的“手动刷新”。

## 3. 需求图片与现有功能映射

| 参考布局 | 榜单页实现 |
|---|---|
| 顶部大标题与说明 | “热点聚合”及现有说明文案 |
| 长搜索框 | 搜索榜单条目的标题、摘要和来源名称 |
| 搜索框右侧操作 | OPML 导入、分组管理、新建 RSS 源 |
| 分类胶囊 | 用户创建的数据源分组 + 全部 + 未分组 |
| 分类下方内容 | 当前榜单工具栏和新闻表格 |

颜色不复制参考图的黑色/深蓝色，继续使用项目的 `primary` 绿色与主题 token。

## 4. 当前代码结论

### 4.1 已具备的分组过滤

榜单页已经调用 `listHotlistSourcesApi()` 和 `listSourceGroupsApi()`，因此已有 `sources`、`groups`、`groupOptions` 和 `groupFilter`。

后端 `GET /api/hotlist/items` 也已支持：

```text
group=""            全部
group="ungrouped"   未分组
group="<id>"        指定用户分组
```

所以分组点击筛选不需要新增后端接口，只需把现有分组下拉改成可视化胶囊。

### 4.2 缺少完整搜索

当前榜单接口没有关键词参数。前端若只用 `items.filter()`，只能搜索当前分页的 20 条，结果不完整。因此搜索必须在后端完成。

### 4.3 源管理逻辑需要抽取

创建 RSS、导入 OPML、分组管理及表单状态目前集中在近千行的 `sources/index.vue`。直接复制会形成两套弹窗、校验和接口处理。应先抽成公共组件，再由两个页面复用。

## 5. 交互设计

### 5.1 页头

- 移除方形火焰图标卡、背景光晕、所有统计卡和页头右侧“手动刷新”。
- 保留 `Trends · Aggregation` 眉题、“热点聚合”主标题和副标题。
- 标题、搜索行、分组标题、新闻列表使用统一左边线。

### 5.2 搜索框

- placeholder：`搜索榜单标题、摘要或来源…`
- 搜索范围：`HotItem.title`、`HotItem.summary`、关联的 `HotSource.name`。
- 输入采用 300ms 防抖；Enter 立即搜索；清空立即恢复全部结果。
- 搜索词变化时将 `page` 重置为 1。
- 搜索可与数据源分组、源类型、排序和“只看命中”组合使用。
- 搜索过程中复用表格 loading，不增加全屏遮罩。
- 无结果时显示：`没有找到与“{关键词}”相关的榜单内容`，并提供“清空搜索”。

### 5.3 搜索框右侧操作

按钮顺序和层级与源管理页一致：

1. `批量导入 OPML`：次级描边按钮，`Upload` 图标。
2. `分组管理`：次级描边按钮，`Layers` 图标。
3. `新建 RSS 源`：绿色主按钮，`Plus` 图标。

操作成功后统一关闭弹窗，重新请求源和分组，并更新胶囊名称与数量。保留当前搜索词、排序和命中过滤；若当前分组被删除，自动切回“全部”并刷新榜单。

“手动刷新”不再占用 header。如仍需保留全量抓取入口，放到新闻列表工具栏右侧，使用小号次级按钮，避免和“新建 RSS 源”竞争。

### 5.4 数据源分组

分组区数据来自 `groups` 和 `sources`，展示顺序：全部 → 按 `sort_order` 排序的分组 → 未分组。

每个胶囊显示名称和源数量，例如 `AI 工具链 12`。数量建议按当前 `sources` 计算，避免依赖可能滞后的 `source_count`。

- 点击胶囊设置现有 `groupFilter` 并刷新新闻列表。
- 选中态：`bg-primary text-primary-foreground`。
- 默认态：`bg-card border-border text-muted-foreground`。
- 分组多时使用 `flex-wrap`，不隐藏在下拉中。
- 名称过长时最大宽度约 220px，省略显示，Tooltip 展示完整名称。
- 没有用户分组时仍显示“全部”和“未分组”，并提供轻量“创建分组”入口。

现有“全部分组”下拉应删除，避免同一筛选出现两套控件。

### 5.5 源类型筛选

“全部 / 中文热榜 / 技术源”与用户数据源分组是两个不同维度，应保留但降级为分组标题右侧的小型二级筛选：

```text
▦ 数据源分组                         类型：[全部] [中文热榜] [技术源]
[全部] [AI 工具链] [国内热榜] ...
```

不要把类型混入用户分组胶囊，否则用户会误以为它们也是可编辑分组。

## 6. 前端组件重构

### 6.1 抽取公共弹窗

建议形成：

```text
frontend/apps/web-antd/src/views/hotlist/sources/components/
├── CreateRssSourceModal.vue
├── ImportOpmlModal.vue
└── GroupManagerModal.vue          # 已存在，继续复用
```

`CreateRssSourceModal.vue` 负责 RSS 表单、校验、调用 `createHotlistSourceApi()`，成功后 emit `changed`。

`ImportOpmlModal.vue` 负责文件读取、OPML URL、目标分组、调用 `importSourcesOpmlApi()`，成功后 emit `changed`。

源管理页和榜单页只维护三个 `open` 状态，不再各自维护表单字段和提交函数。

### 6.2 榜单页状态

新增：

```ts
const searchQuery = ref('');
const debouncedSearchQuery = ref('');
const createSourceOpen = ref(false);
const importOpmlOpen = ref(false);
const groupManagerOpen = ref(false);
```

`fetchItems()` 增加搜索参数：

```ts
listHotlistItemsApi({
  q: debouncedSearchQuery.value || undefined,
  source_kind: kindFilter.value || undefined,
  group: groupFilter.value || undefined,
  sort: sortField.value,
  hit_only: hitOnly.value || undefined,
  page: page.value,
  page_size: pageSize,
});
```

监听搜索、分组、类型、排序、命中过滤时统一重置分页并请求。应合并现有 watch，避免一次状态变化重复请求。

## 7. 后端与 API 调整

### 7.1 榜单接口增加 `q`

文件：`backend/app/hotlist/controllers/hotlist.py`

```python
def list_items(
    q: str = Query("", max_length=100),
    group: str = Query("", max_length=64),
    ...,
):
```

有关键词时关联 `HotSource`，匹配标题、摘要和来源名称。实现时必须转义 `%`、`_` 和反斜杠，避免用户输入被当作 LIKE 通配符。

当前 SQLite 数据量下 `LIKE` 足够；若数据增长后搜索变慢，再升级 FTS，不在本次提前引入。

### 7.2 前端类型

文件：`frontend/apps/web-antd/src/api/core/hotlist.ts`

在 `HotlistApi.ListItemsParams` 增加：

```ts
q?: string;
```

现有 request client 会按 query 参数发送，不需要新 endpoint。

## 8. 源管理页面后续定位

本次不要立即删除 `/hotlist/sources`，建议分两步。

第一阶段：榜单页承载搜索、分组筛选和三个新增/管理入口；源管理页继续承载源卡片、源表格、健康状态、启停、抓取、批量移动和删除；两个页面复用公共弹窗。

第二阶段：稳定后再决定保留“源管理”作为高级管理页，或把源明细改为榜单页抽屉/子路由后从侧边栏隐藏。不要一次性把近千行源管理页面完整塞进榜单页，以免“看榜单”的主任务被管理表格淹没。

## 9. 响应式规格

- 桌面端（≥1200px）：搜索框使用 `minmax(360px, 1fr)`；三个按钮保持一行，高度与搜索框一致，建议 48～52px。
- 平板端（768～1199px）：搜索框独占第一行；三个操作按钮位于第二行并左对齐；分组和类型筛选分别成行。
- 移动端（<768px）：搜索框占满宽度；按钮允许两列或纵向排列；“新建 RSS 源”优先占满宽度；分组胶囊自然换行或横向滚动。

## 10. 验收标准

- [ ] Header 不再显示榜单条目、数据源、异常源统计。
- [ ] Header 中存在与参考图比例接近的大搜索框。
- [ ] 搜索框右侧依次显示“批量导入 OPML / 分组管理 / 新建 RSS 源”。
- [ ] 三个操作与源管理页使用相同公共组件，没有复制两套表单逻辑。
- [ ] 搜索覆盖所有分页中的标题、摘要和来源，而非只过滤当前页。
- [ ] 搜索可与分组、类型、排序、“只看命中”组合。
- [ ] 搜索框下展示数据库中的动态分组，包括用户创建的“AI 工具链”等。
- [ ] 分组数量正确，新增、导入、编辑或删除后立即刷新。
- [ ] 点击分组会过滤下方新闻榜单。
- [ ] 原“全部分组”下拉已移除，不存在重复筛选入口。
- [ ] 下方新闻表格、分页和详情弹窗保持不变。
- [ ] 源管理页的源级启停、抓取、批量操作和删除能力没有回归。
- [ ] 1440px、1024px、768px、375px 宽度下无重叠或页面级横向滚动。

## 11. 推荐实施顺序

1. 从源管理页抽取创建 RSS 和 OPML 导入公共弹窗。
2. 为榜单接口和前端类型增加 `q`。
3. 改造榜单页 header、搜索行和动态分组胶囊。
4. 删除榜单页统计区和重复的分组下拉。
5. 回归源管理页公共弹窗及榜单组合筛选。
6. 执行前端 lint/typecheck 与后端 hotlist 测试。
