<script lang="ts" setup>
import type { HotlistApi } from '#/api/core/hotlist';

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';

import { Page } from '@vben/common-ui';

import { message, Modal, Select, Switch, Tooltip } from 'ant-design-vue';
import { Activity, Flame, LayoutGrid, Radio, RefreshCw, TriangleAlert } from 'lucide-vue-next';

import {
  getHotlistItemDetailApi,
  listHotlistItemsApi,
  listHotlistSourcesApi,
  listSourceGroupsApi,
  triggerHotlistCrawlApi,
} from '#/api/core/hotlist';

const KIND_TABS: { value: HotlistApi.SourceKind | ''; label: string }[] = [
  { value: '', label: '全部' },
  { value: 'hotlist', label: '中文热榜' },
  { value: 'tech', label: '技术源' },
];
const SORT_OPTIONS: { value: HotlistApi.SortField; label: string }[] = [
  { value: 'weight', label: '按权重' },
  { value: 'rank', label: '按榜位' },
  { value: 'time', label: '按最近出现' },
];

function formatDateTime(iso: null | string) {
  if (!iso) return '—';
  return iso.slice(0, 16).replace('T', ' ');
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
    /* 榜单页对源加载失败静默降级，筛选下拉少几个选项而已 */
  }
}
function sourceName(sourceId: string) {
  return sources.value.find((s) => s.id === sourceId)?.name || sourceId;
}

// 数据源分组下拉选项类型：value 约定 '' = 全部分组，'ungrouped' = 未分组，其余为分组 id 字符串。
interface GroupSelectOption {
  label: string;
  value: string;
}
const failingSourceCount = computed(
  () => sources.value.filter((s) => s.enabled && s.last_status === 'failed').length,
);

// -------------------------------------------------------------- 条目列表 ----
const kindFilter = ref<HotlistApi.SourceKind | ''>('');
const groupFilter = ref<string>('');
// 数据源分组下拉：与顶部「全部/中文热榜/技术源」类型 tab 联动。
// 选了某类型时，只显示包含该类型源的分组，保持筛选口径一致。
const groupOptions = computed<GroupSelectOption[]>(() => {
  const kind = kindFilter.value;
  const visibleGroups = groups.value.filter((g) => {
    if (!kind) return true;
    return sources.value.some((s) => s.group_id === g.id && s.source_kind === kind);
  });
  const opts: GroupSelectOption[] = [{ value: '', label: '全部分组' }];
  for (const g of visibleGroups) opts.push({ value: String(g.id), label: g.name });
  if (!kind || sources.value.some((s) => s.group_id == null && s.source_kind === kind)) {
    opts.push({ value: 'ungrouped', label: '未分组' });
  }
  return opts;
});
// 切换源类型后，若当前选中的分组不再属于该类型，重置为「全部分组」
watch(kindFilter, () => {
  groupFilter.value = '';
});
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
      source_kind: kindFilter.value || undefined,
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

watch([kindFilter, groupFilter, sortField, hitOnly], () => {
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
  refreshing.value = true;
  try {
    const result = await triggerHotlistCrawlApi();
    message.success(result.message);
    startCooldown(600);
    // 后端异步抓取，给个宽松延迟后自动刷新一次列表 + 源状态
    setTimeout(() => {
      fetchItems();
      fetchSources();
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
});
onBeforeUnmount(() => clearInterval(cooldownTimer));

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
      <div class="fade-up mb-6 flex shrink-0 flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div class="flex items-start gap-3">
          <div
            class="flex size-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-primary/50 text-primary-foreground shadow-sm"
          >
            <Flame class="size-5" />
          </div>
          <div>
            <p class="text-[10px] font-bold uppercase tracking-[0.25em] text-primary">Trends · Aggregation</p>
            <h1
              class="display-font mt-1 text-3xl font-black tracking-tight text-foreground sm:text-4xl"
            >
              热点聚合
            </h1>
            <p class="mt-1.5 text-sm text-muted-foreground">
              中文热榜 + 技术源统一排名，按权重（榜位 + 频次 + 高位次数）实时聚合
              <span v-if="failingSourceCount > 0" class="ml-1 font-medium text-warning">
                · {{ failingSourceCount }} 个源近期异常
              </span>
            </p>
          </div>
        </div>
        <Tooltip :title="cooldownRemaining > 0 ? `冷却中，${cooldownRemaining}s 后可再次触发` : ''">
          <button
            :disabled="refreshing || cooldownRemaining > 0"
            class="flex shrink-0 items-center gap-1.5 self-start rounded-full bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-md shadow-primary/20 transition-all hover:bg-primary/90 hover:shadow-lg hover:shadow-primary/30 disabled:cursor-not-allowed disabled:opacity-50 lg:self-auto"
            @click="manualRefresh"
          >
            <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': refreshing }" />
            {{ cooldownRemaining > 0 ? `${cooldownRemaining}s` : '手动刷新' }}
          </button>
        </Tooltip>
      </div>

      <!-- 统计信息（三个独立紧凑块） -->
      <div class="fade-up mb-6 flex shrink-0 flex-wrap gap-3" style="animation-delay: 60ms">
        <div class="flex items-center gap-3 rounded-2xl border border-border bg-card px-4 py-3 shadow-sm">
          <div class="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <Activity class="size-4" />
          </div>
          <div>
            <div class="text-[11px] text-muted-foreground">榜单条目</div>
            <div class="text-xl font-bold tracking-tight tabular-nums text-foreground">{{ total }}</div>
          </div>
        </div>
        <div class="flex items-center gap-3 rounded-2xl border border-border bg-card px-4 py-3 shadow-sm">
          <div class="flex size-9 shrink-0 items-center justify-center rounded-xl bg-success/10 text-success">
            <Radio class="size-4" />
          </div>
          <div>
            <div class="text-[11px] text-muted-foreground">数据源</div>
            <div class="text-xl font-bold tracking-tight tabular-nums text-foreground">{{ sources.length }}</div>
          </div>
        </div>
        <div class="flex items-center gap-3 rounded-2xl border border-border bg-card px-4 py-3 shadow-sm">
          <div
            class="flex size-9 shrink-0 items-center justify-center rounded-xl"
            :class="failingSourceCount > 0 ? 'bg-destructive/10 text-destructive' : 'bg-muted text-muted-foreground'"
          >
            <TriangleAlert class="size-4" />
          </div>
          <div>
            <div class="text-[11px] text-muted-foreground">异常源</div>
            <div
              class="text-xl font-bold tracking-tight tabular-nums"
              :class="failingSourceCount > 0 ? 'text-destructive' : 'text-foreground'"
            >
              {{ failingSourceCount }}
            </div>
          </div>
        </div>
      </div>

      <!-- 分类（带标题的胶囊区，可换行） -->
      <div class="fade-up mb-7 flex shrink-0 flex-col gap-2.5" style="animation-delay: 120ms">
        <div class="flex items-center gap-1.5 text-xs font-semibold text-foreground">
          <LayoutGrid class="size-3.5 text-primary" />
          分类
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <button
            v-for="tab in KIND_TABS"
            :key="tab.value"
            class="min-h-10 rounded-full border px-4 py-2 text-xs font-medium transition-all"
            :class="
              kindFilter === tab.value
                ? 'border-primary bg-primary text-primary-foreground shadow-sm'
                : 'border-border bg-card text-muted-foreground hover:text-foreground'
            "
            @click="kindFilter = tab.value"
          >
            {{ tab.label }}
          </button>
        </div>
      </div>

      <!-- 筛选工具栏 -->
      <div class="fade-up mb-4 flex shrink-0 flex-wrap items-center gap-2" style="animation-delay: 300ms">
        <Select
          v-model:value="groupFilter"
          allow-clear
          placeholder="全部分组"
          class="w-44"
          :options="groupOptions"
        />
        <Select v-model:value="sortField" class="w-32" :options="SORT_OPTIONS" />
        <label class="flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1.5 text-xs text-muted-foreground">
          <Switch size="small" v-model:checked="hitOnly" />
          只看命中
        </label>
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
          <p class="text-sm font-medium text-foreground">暂无数据</p>
          <p class="text-xs text-muted-foreground">点右上角「手动刷新」触发一次抓取</p>
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
