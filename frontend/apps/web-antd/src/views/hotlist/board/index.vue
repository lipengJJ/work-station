<script lang="ts" setup>
import type { HotlistApi } from '#/api/core/hotlist';

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';

import { Page } from '@vben/common-ui';

import { message, Modal, Popover, Select, Switch, Tooltip } from 'ant-design-vue';
import { FileText, Flame, Layers, LayoutGrid, RefreshCw, Search, Sparkles, Upload, X } from 'lucide-vue-next';
import MarkdownIt from 'markdown-it';

import ImportOpmlModal from '../sources/components/ImportOpmlModal.vue';
import SourceManagerDrawer from '../sources/components/SourceManagerDrawer.vue';

import {
  generateGroupSummaryApi,
  getEmbeddingStatusApi,
  getGroupSummaryApi,
  getHotlistItemDetailApi,
  listHotlistItemsApi,
  listHotlistSourcesApi,
  listSourceGroupsApi,
  crawlSourcesApi,
  triggerEmbeddingBackfillApi,
} from '#/api/core/hotlist';

const SORT_OPTIONS: { value: HotlistApi.SortField; label: string }[] = [
  { value: 'weight', label: '按权重' },
  { value: 'rank', label: '按榜位' },
  { value: 'time', label: '按最近出现' },
];

function formatDateTime(iso: null | string) {
  if (!iso) return '—';
  return iso.slice(0, 16).replace('T', ' ');
}

// summary 是 RSS 摘要原文（HTML）。DOMParser 解析出来的 document 不会插入真实 DOM、
// 不执行内嵌 <script>/事件处理器，取 textContent 拿纯文本是安全的做法，不能用 v-html
// 直接渲染——摘要来自外部不可信的 RSS 源，可能带恶意标签。
function stripHtml(html: string) {
  if (!html) return '';
  return new DOMParser().parseFromString(html, 'text/html').body.textContent?.trim() || '';
}

function rankBadgeClass(rank: number) {
  if (rank === 1) return 'bg-gradient-to-r from-primary to-primary/70 text-primary-foreground shadow-sm';
  if (rank <= 3) return 'bg-primary/15 text-primary';
  if (rank <= 10) return 'bg-muted text-foreground';
  return 'bg-transparent text-muted-foreground';
}

// -------------------------------------------------------------- 源列表 ----
const sources = ref<HotlistApi.Source[]>([]);
const groups = ref<HotlistApi.SourceGroup[]>([]);
async function fetchSources() {
  try {
    const [srcs, grps] = await Promise.all([
      listHotlistSourcesApi(),
      listSourceGroupsApi(),
    ]);
    sources.value = srcs;
    groups.value = grps;
  } catch {
    /* 榜单页对源加载失败静默降级，分组胶囊少几个而已 */
  }
}
function sourceName(sourceId: string) {
  return sources.value.find((s) => s.id === sourceId)?.name || sourceId;
}

// -------------------------------------------------------------- 语义索引进度 ----
// 低频补偿任务每 30 分钟补一批（每批 200 条），手动补算按钮后台一次性跑完存量。
// 这里轮询展示进度：补算运行中轮得快一点，否则按 pending 决定是否需要轮询。
const embeddingStatus = ref<HotlistApi.EmbeddingStatus>({
  total: 0,
  indexed: 0,
  pending: 0,
  failed: 0,
  running: false,
});
const embeddingBackfillTriggering = ref(false);
let embeddingPollTimer: ReturnType<typeof setInterval> | undefined;
let embeddingRequestSequence = 0;

function resetEmbeddingStatus() {
  embeddingStatus.value = {
    total: 0,
    indexed: 0,
    pending: 0,
    failed: 0,
    running: false,
  };
}

async function fetchEmbeddingStatus() {
  const requestSequence = ++embeddingRequestSequence;
  const requestedGroup = groupFilter.value;
  clearInterval(embeddingPollTimer);
  embeddingPollTimer = undefined;

  // 已选分组没有任何源时，索引数量必然为 0。不要请求后端，更不能沿用上个分组的数字。
  if (requestedGroup && selectedSourceIds.value.length === 0) {
    resetEmbeddingStatus();
    return;
  }
  try {
    const status = await getEmbeddingStatusApi(
      [...selectedSourceIds.value],
      requestedGroup,
    );
    // 切换分组时旧请求可能比新请求晚返回；旧结果不能覆盖当前分组的数字。
    if (
      requestSequence !== embeddingRequestSequence ||
      requestedGroup !== groupFilter.value
    ) return;
    embeddingStatus.value = status;
  } catch {
    // 请求失败时显示当前范围的空状态，禁止继续展示上一个分组的统计。
    if (
      requestSequence === embeddingRequestSequence &&
      requestedGroup === groupFilter.value
    ) resetEmbeddingStatus();
  } finally {
    if (
      requestSequence !== embeddingRequestSequence ||
      requestedGroup !== groupFilter.value
    ) return;
    if (embeddingStatus.value.running) {
      embeddingPollTimer = setInterval(fetchEmbeddingStatus, 5_000);
    } else if (embeddingStatus.value.pending > 0) {
      embeddingPollTimer = setInterval(fetchEmbeddingStatus, 30_000);
    }
  }
}

async function triggerEmbeddingBackfill() {
  embeddingBackfillTriggering.value = true;
  try {
    const result = await triggerEmbeddingBackfillApi(
      [...selectedSourceIds.value],
      groupFilter.value,
    );
    message.success(result.message);
    fetchEmbeddingStatus();
  } catch (e: any) {
    if (e?.response?.status === 429) {
      message.warning(e.response?.data?.detail || '已有索引补算任务在执行，请稍后再试');
    } else {
      message.error(`触发失败：${e.message}`);
    }
  } finally {
    embeddingBackfillTriggering.value = false;
  }
}

// -------------------------------------------------------------- 搜索 ----
const searchQuery = ref('');
const debouncedSearchQuery = ref('');
let searchDebounceTimer: ReturnType<typeof setTimeout> | undefined;

watch(searchQuery, (v) => {
  clearTimeout(searchDebounceTimer);
  searchDebounceTimer = setTimeout(() => {
    debouncedSearchQuery.value = v.trim();
  }, 300);
});

function commitSearchNow() {
  clearTimeout(searchDebounceTimer);
  debouncedSearchQuery.value = searchQuery.value.trim();
}

function clearSearch() {
  searchQuery.value = '';
  commitSearchNow();
}

// -------------------------------------------------------------- 源管理弹窗 ----
const importOpmlOpen = ref(false);
const sourceManagerOpen = ref(false);

// -------------------------------------------------------------- 条目列表 ----
const groupFilter = ref<string>('');

interface GroupPill {
  value: string;
  label: string;
  count: number;
  /** 分组自定义颜色（分组管理里选的那个点）；全部/未分组没有自定义色，给个中性灰 */
  color: string;
}

const UNGROUPED_COLOR = '#8c8c8c';

// 数据源分组胶囊：全部 → 按 sort_order 排的用户分组 → 未分组。数量按当前 sources
// 现算，不依赖可能滞后的 group.source_count。每个分组胶囊前面带一个小色点，
// 对应分组管理里给这个分组选的颜色，一眼区分不同分组，不用逐个读文字。
const groupPills = computed<GroupPill[]>(() => {
  const visibleGroups = [...groups.value].sort((a, b) => a.sort_order - b.sort_order);
  const pills: GroupPill[] = [
    { value: '', label: '全部', count: sources.value.length, color: UNGROUPED_COLOR },
  ];
  for (const g of visibleGroups) {
    pills.push({
      value: String(g.id),
      label: g.name,
      count: sources.value.filter((s) => s.group_id === g.id).length,
      color: g.color || UNGROUPED_COLOR,
    });
  }
  pills.push({
    value: 'ungrouped',
    label: '未分组',
    count: sources.value.filter((s) => s.group_id === null || s.group_id === undefined).length,
    color: UNGROUPED_COLOR,
  });
  return pills;
});

const selectedSources = computed(() =>
  sources.value
    .filter((source) => {
      if (!groupFilter.value) return true;
      if (groupFilter.value === 'ungrouped') return source.group_id == null;
      return String(source.group_id) === groupFilter.value;
    }),
);
const selectedSourceIds = computed(() => selectedSources.value.map((source) => source.id));
const selectedEnabledSourceIds = computed(() =>
  selectedSources.value.filter((source) => source.enabled).map((source) => source.id),
);

// 分组被删除（分组管理里操作）后，若当前筛选还指向它，回退到「全部」
watch(groups, () => {
  if (
    groupFilter.value &&
    groupFilter.value !== 'ungrouped' &&
    !groups.value.some((g) => String(g.id) === groupFilter.value)
  ) {
    groupFilter.value = '';
  }
});
watch(groupFilter, () => {
  // 立即移除上一分组数字/总结，随后再用当前分组响应回填，避免闪一下上一分组的旧数据。
  resetEmbeddingStatus();
  fetchEmbeddingStatus();
  groupSummary.value = null;
  fetchGroupSummary();
});

// -------------------------------------------------------------- AI 总结 ----
// 非对话：固定指令、一键生成。切分组时只回看该分组上次生成的结果（不自动重新生成），
// 用户觉得过时了自己点「重新生成」。
const groupSummary = ref<HotlistApi.GroupSummary | null>(null);
const groupSummaryGenerating = ref(false);
const groupSummaryVisible = ref(false);

async function fetchGroupSummary() {
  const requestedGroup = groupFilter.value;
  try {
    const result = await getGroupSummaryApi(requestedGroup);
    if (requestedGroup !== groupFilter.value) return; // 切分组时旧请求晚回来，丢弃
    groupSummary.value = result;
    // 这个分组之前生成过，切回来自动展示上次结果；没有就保持收起，等用户点「AI 总结」
    if (result) groupSummaryVisible.value = true;
  } catch {
    // 静默失败：只是回看历史，不影响主流程
  }
}

async function generateGroupSummary() {
  if (groupSummaryGenerating.value) return;
  groupSummaryGenerating.value = true;
  groupSummaryVisible.value = true;
  const requestedGroup = groupFilter.value;
  try {
    const result = await generateGroupSummaryApi(requestedGroup);
    if (requestedGroup !== groupFilter.value) return;
    groupSummary.value = result;
  } catch (e: any) {
    message.error(`生成总结失败：${e.response?.data?.detail || e.message}`);
  } finally {
    groupSummaryGenerating.value = false;
  }
}

/** 总结正文里的 #12 引用标记点出去，直接打开对应条目详情（复用 openDetail，只用得到 id）。 */
function openDetailById(id: number) {
  openDetail({ id } as HotlistApi.Item);
}

// 总结正文是 Markdown（group_summary_service.SYSTEM_INSTRUCTION 要求 "- " 列表 + 加粗），
// 跟条目详情页（items/detail.vue）同一种用法：markdown-it 默认 html:false，裸 HTML 会被
// 转义，内容来自本站 AI 调用结果，v-html 是安全的。
const summaryMd = new MarkdownIt({ breaks: true });

/** 把渲染后 HTML 里的 "#891" 引用标记包一层 <span data-item-id>，配合 onSummaryClick
 * 做事件委托——v-html 注入的内容不能直接写 @click，只能在容器上委托。 */
function groupSummaryHtml(content: string): string {
  const rendered = summaryMd.render(content);
  return rendered.replace(/(?<![\w#])#(\d+)\b/g, (match, id) => {
    return `<span class="ref-link cursor-pointer font-mono text-primary hover:underline" data-item-id="${id}">${match}</span>`;
  });
}

function onSummaryClick(e: MouseEvent) {
  const target = (e.target as HTMLElement).closest('[data-item-id]');
  const id = Number(target?.getAttribute('data-item-id'));
  if (id) openDetailById(id);
}

const sortField = ref<HotlistApi.SortField>('weight');
const hitOnly = ref(false);
const page = ref(1);
const pageSize = 20;
const total = ref(0);
const items = ref<HotlistApi.Item[]>([]);
const itemsLoading = ref(false);

async function fetchItems() {
  itemsLoading.value = true;
  try {
    const result = await listHotlistItemsApi({
      q: debouncedSearchQuery.value || undefined,
      group: groupFilter.value || undefined,
      sort: sortField.value,
      hit_only: hitOnly.value || undefined,
      page: page.value,
      page_size: pageSize,
    });
    items.value = result.items;
    total.value = result.total;
  } catch (e: any) {
    message.error(`加载失败：${e.message}`);
  } finally {
    itemsLoading.value = false;
  }
}

watch([debouncedSearchQuery, groupFilter, sortField, hitOnly], () => {
  page.value = 1;
  fetchItems();
});
watch(page, fetchItems);

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));
function goPage(p: number) {
  if (p < 1 || p > totalPages.value) return;
  page.value = p;
}

// -------------------------------------------------------------- 手动刷新 ----
const refreshing = ref(false);
const cooldownRemaining = ref(0);
let cooldownTimer: ReturnType<typeof setInterval> | undefined;

function startCooldown(seconds: number) {
  cooldownRemaining.value = seconds;
  clearInterval(cooldownTimer);
  cooldownTimer = setInterval(() => {
    cooldownRemaining.value = Math.max(0, cooldownRemaining.value - 1);
    if (cooldownRemaining.value === 0) clearInterval(cooldownTimer);
  }, 1000);
}

async function manualRefresh() {
  const sourceIds = selectedEnabledSourceIds.value;
  if (sourceIds.length === 0) {
    message.warning('当前分组没有已启用的数据源');
    return;
  }
  refreshing.value = true;
  try {
    const result = await crawlSourcesApi(sourceIds);
    const scope = groupFilter.value ? '当前分组' : '全部分组';
    message.success(`已开始刷新${scope}（${result.count} 个源）`);
    startCooldown(600);
    // 后端异步抓取，给个宽松延迟后自动刷新一次列表 + 源状态
    setTimeout(() => {
      fetchItems();
      fetchSources();
      fetchEmbeddingStatus();
    }, 15_000);
  } catch (e: any) {
    if (e?.response?.status === 429) {
      message.warning(e.response?.data?.detail || '刷新过于频繁，请稍后再试');
    } else {
      message.error(`触发失败：${e.message}`);
    }
  } finally {
    refreshing.value = false;
  }
}

onMounted(() => {
  fetchSources();
  fetchItems();
  fetchEmbeddingStatus();
  fetchGroupSummary();
});
onBeforeUnmount(() => {
  clearInterval(cooldownTimer);
  clearInterval(embeddingPollTimer);
  clearTimeout(searchDebounceTimer);
});

// -------------------------------------------------------------- 条目详情（榜位曲线）----
const detailModalOpen = ref(false);
const detailLoading = ref(false);
const detailItem = ref<HotlistApi.ItemDetail | null>(null);

async function openDetail(item: HotlistApi.Item) {
  detailModalOpen.value = true;
  detailLoading.value = true;
  detailItem.value = null;
  try {
    detailItem.value = await getHotlistItemDetailApi(item.id);
  } catch (e: any) {
    message.error(`加载详情失败：${e.message}`);
  } finally {
    detailLoading.value = false;
  }
}

const CHART_WIDTH = 560;
const CHART_HEIGHT = 190;
const PADDING_X = 12;
const NORMAL_BAND_TOP = 8;
const NORMAL_BAND_HEIGHT = 130;
const OFFLIST_DIVIDER_Y = NORMAL_BAND_HEIGHT + 20;
const OFFLIST_POINT_Y = OFFLIST_DIVIDER_Y + 22;

interface CurvePoint {
  x: number;
  y: number;
  rank: number;
  time: string;
}

const curvePoints = computed<CurvePoint[]>(() => {
  const history = detailItem.value?.history ?? [];
  if (history.length === 0) return [];
  const positiveRanks = history.filter((h) => h.rank > 0).map((h) => h.rank);
  const maxRank = Math.max(10, ...positiveRanks, detailItem.value?.item.best_rank ?? 1);
  const stepX = history.length > 1 ? (CHART_WIDTH - PADDING_X * 2) / (history.length - 1) : 0;
  return history.map((point, idx) => {
    const x = PADDING_X + idx * stepX;
    const y =
      point.rank > 0
        ? NORMAL_BAND_TOP + ((point.rank - 1) / Math.max(maxRank - 1, 1)) * (NORMAL_BAND_HEIGHT - NORMAL_BAND_TOP)
        : OFFLIST_POINT_Y;
    return { x, y, rank: point.rank, time: point.crawl_time };
  });
});

// 相邻两点只要有一个脱榜（rank=0），这一段线就用「脱榜」样式（虚线 + 玫红色）画出来，
// 一眼能看出「从哪个点开始掉出榜单」。
const curveSegments = computed(() => {
  const points = curvePoints.value;
  const segments: { d: string; offlist: boolean }[] = [];
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1]!;
    const b = points[i]!;
    segments.push({ d: `M ${a.x} ${a.y} L ${b.x} ${b.y}`, offlist: a.rank === 0 || b.rank === 0 });
  }
  return segments;
});
</script>

<template>
  <Page :auto-content-height="true" content-class="!p-0">
    <div class="custom-scrollbar flex h-full flex-1 flex-col overflow-y-auto bg-background-deep p-6 lg:p-8 select-none">
      <!-- 页头（开放式，标题直接落在页面背景上） -->
      <div class="fade-up mb-5 flex shrink-0 items-start gap-3">
        <div
          class="flex size-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-primary/50 text-primary-foreground shadow-sm"
        >
          <Flame class="size-5" />
        </div>
        <div>
          <p class="text-[10px] font-bold uppercase tracking-[0.25em] text-primary">Trends · Aggregation</p>
          <h1 class="display-font mt-1 text-3xl font-black tracking-tight text-foreground sm:text-4xl">
            热点聚合
          </h1>
          <p class="mt-1.5 text-sm text-muted-foreground">
            中文热榜 + 技术源统一排名，按权重（榜位 + 频次 + 高位次数）实时聚合
          </p>
        </div>
      </div>

      <!-- 搜索行：长搜索框 + 源管理高频入口 -->
      <div class="fade-up mb-6 flex shrink-0 flex-col gap-3 lg:flex-row lg:items-stretch" style="animation-delay: 60ms">
        <div class="relative min-w-[280px] flex-1 lg:min-w-[360px]">
          <Search class="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            v-model="searchQuery"
            type="text"
            placeholder="搜索榜单标题、摘要或来源…"
            class="h-12 w-full rounded-2xl border border-border bg-card pl-11 pr-10 text-sm text-foreground shadow-sm outline-none placeholder:text-muted-foreground focus:border-primary"
            @keyup.enter="commitSearchNow"
          />
          <button
            v-if="searchQuery"
            class="absolute right-3.5 top-1/2 -translate-y-1/2 text-muted-foreground transition-colors hover:text-foreground"
            @click="clearSearch"
          >
            <X class="size-4" />
          </button>
        </div>
        <div class="flex flex-wrap items-center gap-2 lg:shrink-0">
          <button
            class="flex h-12 items-center gap-1.5 rounded-2xl border border-border bg-card px-4 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
            @click="importOpmlOpen = true"
          >
            <Upload class="size-3.5" />
            批量导入 OPML
          </button>
          <button
            class="flex h-12 items-center gap-1.5 rounded-2xl border border-border bg-card px-4 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
            @click="sourceManagerOpen = true"
          >
            <Layers class="size-3.5" />
            分组管理
          </button>
        </div>
      </div>

      <!-- 数据源分组：标题行 + 胶囊 -->
      <div class="fade-up mb-3 flex shrink-0 flex-wrap items-center gap-2" style="animation-delay: 120ms">
        <div class="flex items-center gap-1.5 text-xs font-semibold text-foreground">
          <LayoutGrid class="size-3.5 text-primary" />
          数据源分组
        </div>
      </div>
      <div class="fade-up mb-7 flex shrink-0 flex-wrap items-center gap-2" style="animation-delay: 150ms">
        <Tooltip v-for="pill in groupPills" :key="pill.value" :title="pill.label">
          <button
            class="inline-flex items-center gap-1.5 rounded-full border px-3.5 py-2 text-xs font-medium transition-all"
            :class="
              groupFilter === pill.value
                ? 'border-primary bg-primary text-primary-foreground shadow-sm'
                : 'border-border bg-card text-muted-foreground hover:text-foreground'
            "
            @click="groupFilter = pill.value"
          >
            <span
              class="size-2 shrink-0 rounded-full ring-1 ring-inset"
              :class="groupFilter === pill.value ? 'ring-primary-foreground/50' : 'ring-black/10'"
              :style="{ backgroundColor: pill.color }"
            ></span>
            <span class="max-w-[220px] truncate">{{ pill.label }}</span>
            <span>{{ pill.count }}</span>
          </button>
        </Tooltip>
        <button
          v-if="groups.length === 0"
          class="rounded-full border border-dashed border-border px-3.5 py-2 text-xs text-primary transition-colors hover:bg-primary/5"
          @click="sourceManagerOpen = true"
        >
          + 创建分组
        </button>
      </div>

      <!-- 筛选工具栏 -->
      <div class="fade-up mb-4 flex shrink-0 flex-wrap items-center gap-2" style="animation-delay: 300ms">
        <Select v-model:value="sortField" class="w-32" :options="SORT_OPTIONS" />
        <label class="flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1.5 text-xs text-muted-foreground">
          <Switch size="small" v-model:checked="hitOnly" />
          只看命中
        </label>

        <div class="ml-auto flex flex-wrap items-center gap-2">
          <!-- 语义索引进度（紧凑，取代原 header 统计卡） -->
          <Tooltip
            :title="
              embeddingStatus.failed > 0
                ? `${embeddingStatus.failed} 篇索引失败，等待补偿任务重试`
                : '低频补偿任务每 30 分钟补一批，也可手动补算存量'
            "
          >
            <div class="flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1.5 text-[11px] text-muted-foreground">
              <Sparkles
                class="size-3.5"
                :class="[
                  embeddingStatus.pending > 0 ? 'text-warning' : 'text-success',
                  { 'animate-pulse': embeddingStatus.running },
                ]"
              />
              语义索引 {{ embeddingStatus.indexed }}/{{ embeddingStatus.total }}
              <span v-if="embeddingStatus.running" class="font-medium text-primary">· 补算中</span>
            </div>
          </Tooltip>
          <button
            v-if="embeddingStatus.pending > 0"
            :disabled="embeddingBackfillTriggering || embeddingStatus.running"
            class="rounded-full border border-primary/30 px-3 py-1.5 text-[11px] font-medium text-primary transition-colors hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-50"
            @click="triggerEmbeddingBackfill"
          >
            {{ embeddingStatus.running ? '补算中…' : '补算索引' }}
          </button>

          <button
            :disabled="groupSummaryGenerating"
            class="flex items-center gap-1.5 rounded-full border border-primary/30 bg-primary/5 px-3 py-1.5 text-[11px] font-medium text-primary transition-colors hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-50"
            title="总结当前分组下值得关注的条目，帮你快速定位"
            @click="generateGroupSummary"
          >
            <Sparkles class="size-3.5" :class="{ 'animate-pulse': groupSummaryGenerating }" />
            {{ groupSummaryGenerating ? '生成中…' : 'AI 总结' }}
          </button>

          <Tooltip :title="cooldownRemaining > 0 ? `冷却中，${cooldownRemaining}s 后可再次触发` : ''">
            <button
              :disabled="refreshing || cooldownRemaining > 0"
              class="flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1.5 text-[11px] font-medium text-muted-foreground transition-colors hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
              @click="manualRefresh"
            >
              <RefreshCw class="size-3.5" :class="{ 'animate-spin': refreshing }" />
              {{ cooldownRemaining > 0 ? `${cooldownRemaining}s` : '手动刷新' }}
            </button>
          </Tooltip>
        </div>
      </div>

      <!-- AI 总结结果（非对话，一键生成；点标记 [12] 可跳转到对应条目详情） -->
      <div
        v-if="groupSummaryVisible && (groupSummaryGenerating || groupSummary)"
        class="fade-up mb-4 shrink-0 rounded-2xl border border-primary/20 bg-primary/5 p-4"
        style="animation-delay: 300ms"
      >
        <div class="mb-2 flex items-center justify-between">
          <div class="flex items-center gap-1.5 text-xs font-semibold text-primary">
            <Sparkles class="size-3.5" />
            AI 总结
          </div>
          <div class="flex items-center gap-3 text-[11px] text-muted-foreground">
            <span v-if="groupSummary && !groupSummaryGenerating">
              {{ formatDateTime(groupSummary.created_at) }} · 基于 {{ groupSummary.item_count }} 条
            </span>
            <button
              v-if="!groupSummaryGenerating"
              class="text-primary transition-colors hover:text-primary/70"
              @click="generateGroupSummary"
            >
              重新生成
            </button>
            <button class="text-muted-foreground transition-colors hover:text-foreground" @click="groupSummaryVisible = false">
              <X class="size-3.5" />
            </button>
          </div>
        </div>
        <div v-if="groupSummaryGenerating" class="py-6 text-center text-xs text-muted-foreground">正在生成总结…</div>
        <div v-else-if="groupSummary?.status === 'failed'" class="text-xs text-destructive">
          {{ groupSummary.error || '生成失败' }}
        </div>
        <!-- eslint-disable-next-line vue/no-v-html -- 内容来自本站 AI 调用结果，markdown-it 默认 html:false 会转义裸 HTML，v-html 是安全的 -->
        <div
          v-else-if="groupSummary"
          class="prose prose-sm dark:prose-invert max-w-none text-xs leading-relaxed"
          v-html="groupSummaryHtml(groupSummary.content)"
          @click="onSummaryClick"
        ></div>
      </div>

      <!-- 榜单表格 -->
      <div class="fade-up shrink-0 overflow-hidden rounded-2xl border border-border bg-card shadow-sm" style="animation-delay: 360ms">
        <div
          v-if="!itemsLoading && items.length === 0"
          class="flex flex-col items-center justify-center gap-3 p-16 text-center"
        >
          <div class="flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
            <Flame class="size-5" />
          </div>
          <template v-if="debouncedSearchQuery">
            <p class="text-sm font-medium text-foreground">没有找到与"{{ debouncedSearchQuery }}"相关的榜单内容</p>
            <button class="text-xs text-primary hover:underline" @click="clearSearch">清空搜索</button>
          </template>
          <template v-else>
            <p class="text-sm font-medium text-foreground">暂无数据</p>
            <p class="text-xs text-muted-foreground">点击下方「手动刷新」触发一次抓取</p>
          </template>
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full text-left text-xs">
            <thead class="border-b border-border bg-muted/50 text-[11px] font-medium text-muted-foreground">
              <tr>
                <th class="px-4 py-3">榜位</th>
                <th class="px-4 py-3">标题</th>
                <th class="px-4 py-3">来源</th>
                <th class="px-4 py-3">出现次数</th>
                <th class="px-4 py-3">权重</th>
                <th class="px-4 py-3">首次出现</th>
                <th class="px-4 py-3">最近出现</th>
                <th class="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody class="divide-y divide-border">
              <tr v-for="item in items" :key="item.id" class="transition-colors hover:bg-accent/60">
                <td class="px-4 py-3">
                  <span
                    v-if="item.rank > 0"
                    class="inline-flex min-w-9 items-center justify-center rounded-full px-2 py-1 font-mono text-[11px] font-bold"
                    :class="rankBadgeClass(item.rank)"
                  >
                    #{{ item.rank }}
                  </span>
                  <span v-else class="font-mono text-[11px] text-muted-foreground">脱榜</span>
                </td>
                <td class="max-w-md px-4 py-3">
                  <a
                    v-if="item.url"
                    :href="item.url"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="line-clamp-2 font-medium text-foreground transition-colors hover:text-primary"
                  >
                    {{ item.title }}
                  </a>
                  <span v-else class="line-clamp-2 font-medium text-foreground">{{ item.title }}</span>
                  <div v-if="item.hit_rules.length" class="mt-1.5 flex flex-wrap gap-1">
                    <span
                      v-for="name in item.hit_rules"
                      :key="name"
                      class="rounded-full bg-warning/15 px-2 py-0.5 text-[10px] font-medium text-warning"
                    >
                      命中：{{ name }}
                    </span>
                  </div>
                </td>
                <td class="px-4 py-3 text-muted-foreground">{{ sourceName(item.source_id) }}</td>
                <td class="px-4 py-3 font-mono text-muted-foreground">{{ item.crawl_count }}</td>
                <td class="px-4 py-3 font-mono font-semibold text-foreground">{{ item.weight.toFixed(1) }}</td>
                <td class="px-4 py-3 text-muted-foreground">{{ formatDateTime(item.first_crawl_time) }}</td>
                <td class="px-4 py-3 text-muted-foreground">{{ formatDateTime(item.last_crawl_time) }}</td>
                <td class="px-4 py-3 text-right">
                  <Popover placement="left" trigger="click" :overlay-style="{ maxWidth: '360px' }">
                    <template #content>
                      <p class="max-h-60 overflow-y-auto whitespace-pre-wrap text-xs leading-relaxed text-foreground">
                        {{ stripHtml(item.summary) || '（无摘要）' }}
                      </p>
                    </template>
                    <button
                      class="mr-1 rounded-full p-1.5 text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary"
                    >
                      <FileText class="size-3.5" />
                    </button>
                  </Popover>
                  <button
                    class="rounded-full px-2.5 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary"
                    @click="openDetail(item)"
                  >
                    详情
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 分页 -->
      <div
        v-if="total > pageSize"
        class="fade-up mt-5 flex shrink-0 items-center justify-between text-xs text-muted-foreground"
        style="animation-delay: 420ms"
      >
        <span>共 {{ total }} 条</span>
        <div class="flex items-center gap-2">
          <button
            class="rounded-full border border-border bg-card px-3 py-1 transition-colors hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
            :disabled="page <= 1"
            @click="goPage(page - 1)"
          >
            上一页
          </button>
          <span class="font-mono">{{ page }} / {{ totalPages }}</span>
          <button
            class="rounded-full border border-border bg-card px-3 py-1 transition-colors hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
            :disabled="page >= totalPages"
            @click="goPage(page + 1)"
          >
            下一页
          </button>
        </div>
      </div>
    </div>

    <!-- 详情弹窗 -->
    <Modal v-model:open="detailModalOpen" :title="detailItem?.item.title || '条目详情'" :footer="null" width="620px">
      <div v-if="detailLoading" class="py-8 text-center text-xs text-muted-foreground">加载中…</div>
      <template v-else-if="detailItem">
        <div class="mb-4 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
          <div class="rounded-xl bg-muted/40 p-3">
            <div class="text-[10px] text-muted-foreground uppercase">来源</div>
            <div class="mt-1 font-medium text-foreground">{{ sourceName(detailItem.item.source_id) }}</div>
          </div>
          <div class="rounded-xl bg-muted/40 p-3">
            <div class="text-[10px] text-muted-foreground uppercase">当前榜位</div>
            <div class="mt-1 font-medium text-foreground">
              {{ detailItem.item.rank > 0 ? `#${detailItem.item.rank}` : '脱榜' }}
            </div>
          </div>
          <div class="rounded-xl bg-muted/40 p-3">
            <div class="text-[10px] text-muted-foreground uppercase">历史最佳</div>
            <div class="mt-1 font-medium text-foreground">#{{ detailItem.item.best_rank }}</div>
          </div>
          <div class="rounded-xl bg-muted/40 p-3">
            <div class="text-[10px] text-muted-foreground uppercase">权重</div>
            <div class="mt-1 font-medium text-foreground">{{ detailItem.item.weight.toFixed(1) }}</div>
          </div>
        </div>

        <div v-if="detailItem.item.hit_rules.length" class="mb-4 flex flex-wrap gap-1">
          <span
            v-for="name in detailItem.item.hit_rules"
            :key="name"
            class="rounded-full bg-warning/15 px-2 py-0.5 text-[10px] font-medium text-warning"
          >
            命中：{{ name }}
          </span>
        </div>

        <div class="mb-2 text-[11px] font-medium text-muted-foreground">榜位曲线（含脱榜段）</div>
        <div
          v-if="curvePoints.length === 0"
          class="rounded-xl border border-border bg-muted/40 p-6 text-center text-xs text-muted-foreground"
        >
          暂无历史数据
        </div>
        <svg
          v-else
          :width="CHART_WIDTH"
          :height="CHART_HEIGHT"
          :viewBox="`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`"
          class="w-full rounded-xl border border-border bg-card"
        >
          <line
            :x1="PADDING_X"
            :y1="OFFLIST_DIVIDER_Y"
            :x2="CHART_WIDTH - PADDING_X"
            :y2="OFFLIST_DIVIDER_Y"
            stroke="hsl(var(--border))"
            stroke-width="1"
            stroke-dasharray="3,3"
          />
          <text :x="PADDING_X" :y="OFFLIST_DIVIDER_Y + 14" class="fill-current text-[9px]" style="fill: hsl(var(--muted-foreground))">
            脱榜
          </text>
          <path
            v-for="(seg, idx) in curveSegments"
            :key="idx"
            :d="seg.d"
            fill="none"
            :stroke="seg.offlist ? 'hsl(var(--destructive))' : 'hsl(var(--primary))'"
            stroke-width="2"
            :stroke-dasharray="seg.offlist ? '4,3' : undefined"
            stroke-linecap="round"
          />
          <circle
            v-for="(p, idx) in curvePoints"
            :key="idx"
            :cx="p.x"
            :cy="p.y"
            r="3.5"
            :fill="p.rank === 0 ? 'hsl(var(--destructive))' : 'hsl(var(--primary))'"
            stroke="hsl(var(--card))"
            stroke-width="1.5"
          >
            <title>{{ p.time.slice(0, 16).replace('T', ' ') }} · {{ p.rank > 0 ? `第 ${p.rank} 位` : '脱榜' }}</title>
          </circle>
        </svg>
      </template>
    </Modal>

    <!-- 源管理弹窗：与源管理页共用同一份组件 -->
    <ImportOpmlModal v-model:open="importOpmlOpen" :groups="groups" @changed="fetchSources" />
    <SourceManagerDrawer
      v-model:open="sourceManagerOpen"
      :initial-group="groupFilter"
      @changed="fetchSources"
    />
  </Page>
</template>

<style scoped>
.display-font {
  font-family:
    'SF Pro Display', 'PingFang SC', 'Hiragino Sans GB', 'Noto Sans SC',
    'Microsoft YaHei', system-ui, sans-serif;
}
.fade-up {
  animation: fade-up 0.5s cubic-bezier(0.16, 1, 0.3, 1) both;
}
@keyframes fade-up {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
