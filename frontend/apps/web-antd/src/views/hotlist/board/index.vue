<script lang="ts" setup>
import type { HotlistApi } from '#/api/core/hotlist';

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';

import { Page } from '@vben/common-ui';

import { message, Modal, Select, Switch, Tooltip } from 'ant-design-vue';
import { RefreshCw } from 'lucide-vue-next';

import {
  getHotlistItemDetailApi,
  listHotlistItemsApi,
  listHotlistSourcesApi,
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

// -------------------------------------------------------------- 源列表 ----
const sources = ref<HotlistApi.Source[]>([]);
async function fetchSources() {
  try {
    sources.value = await listHotlistSourcesApi();
  } catch {
    /* 榜单页对源加载失败静默降级，筛选下拉少几个选项而已 */
  }
}
function sourceName(sourceId: string) {
  return sources.value.find((s) => s.id === sourceId)?.name || sourceId;
}
const sourceOptions = computed(() =>
  sources.value
    .filter((s) => !kindFilter.value || s.source_kind === kindFilter.value)
    .map((s) => ({ value: s.id, label: s.name || s.id })),
);
const failingSourceCount = computed(
  () => sources.value.filter((s) => s.enabled && s.last_status === 'failed').length,
);

// -------------------------------------------------------------- 条目列表 ----
const kindFilter = ref<HotlistApi.SourceKind | ''>('');
const sourceFilter = ref<string>('');
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
      source_id: sourceFilter.value || undefined,
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

watch([kindFilter, sourceFilter, sortField, hitOnly], () => {
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
    <div class="custom-scrollbar flex h-full flex-1 flex-col overflow-y-auto bg-[hsl(var(--background-deep))] p-6 select-none">
      <div class="mb-6 shrink-0 flex items-start justify-between gap-3">
        <div>
          <h1 class="text-xl font-extrabold text-[hsl(var(--foreground))]">热点聚合 · 榜单</h1>
          <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">
            中文热榜 + 技术源统一排名，按权重（榜位 + 出现频次 + 高位次数）排序
            <span v-if="failingSourceCount > 0" class="ml-2 text-amber-400">
              {{ failingSourceCount }} 个源近期抓取失败，可在「源管理」查看详情
            </span>
          </p>
        </div>
        <Tooltip :title="cooldownRemaining > 0 ? `冷却中，${cooldownRemaining}s 后可再次触发` : ''">
          <button
            :disabled="refreshing || cooldownRemaining > 0"
            class="flex shrink-0 items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-indigo-600"
            @click="manualRefresh"
          >
            <RefreshCw class="h-3.5 w-3.5" :class="{ 'animate-spin': refreshing }" />
            {{ cooldownRemaining > 0 ? `${cooldownRemaining}s` : '手动刷新' }}
          </button>
        </Tooltip>
      </div>

      <!-- 源类型 Tab -->
      <div class="mb-4 shrink-0 flex items-center gap-1 border-b border-[hsl(var(--border))]">
        <button
          v-for="tab in KIND_TABS"
          :key="tab.value"
          class="border-b-2 px-3 py-2 text-xs font-semibold transition-colors"
          :class="
            kindFilter === tab.value
              ? 'border-indigo-500 text-[hsl(var(--foreground))]'
              : 'border-transparent text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'
          "
          @click="kindFilter = tab.value"
        >
          {{ tab.label }}
        </button>
      </div>

      <div class="mb-4 shrink-0 flex flex-wrap items-center gap-2">
        <Select
          v-model:value="sourceFilter"
          allow-clear
          placeholder="全部来源"
          class="w-44"
          :options="[{ value: '', label: '全部来源' }, ...sourceOptions]"
        />
        <Select v-model:value="sortField" class="w-32" :options="SORT_OPTIONS" />
        <label class="flex items-center gap-1.5 text-xs text-[hsl(var(--muted-foreground))]">
          <Switch size="small" v-model:checked="hitOnly" />
          只看命中
        </label>
        <span class="text-xs text-[hsl(var(--muted-foreground))]">共 {{ total }} 条</span>
      </div>

      <div class="shrink-0 overflow-hidden rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] shadow-xl">
        <div v-if="!itemsLoading && items.length === 0" class="flex flex-col items-center justify-center gap-2 p-12 text-center">
          <p class="text-sm font-semibold text-[hsl(var(--foreground))]">暂无数据</p>
          <p class="text-xs text-[hsl(var(--muted-foreground))]">点右上角「手动刷新」触发一次抓取</p>
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full text-left text-xs">
            <thead class="border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] font-mono text-[11px] text-[hsl(var(--muted-foreground))] uppercase">
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
            <tbody class="divide-y divide-[hsl(var(--border))]">
              <tr
                v-for="item in items"
                :key="item.id"
                class="transition-colors hover:bg-[hsl(var(--accent))]"
              >
                <td class="px-4 py-3 font-mono">
                  <span v-if="item.rank > 0">#{{ item.rank }}</span>
                  <span v-else class="text-[hsl(var(--muted-foreground))]">脱榜</span>
                </td>
                <td class="max-w-md px-4 py-3">
                  <a
                    v-if="item.url"
                    :href="item.url"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="line-clamp-2 font-semibold text-[hsl(var(--foreground))] hover:text-indigo-400"
                  >
                    {{ item.title }}
                  </a>
                  <span v-else class="line-clamp-2 font-semibold text-[hsl(var(--foreground))]">{{ item.title }}</span>
                  <div v-if="item.hit_rules.length" class="mt-1 flex flex-wrap gap-1">
                    <span
                      v-for="name in item.hit_rules"
                      :key="name"
                      class="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-amber-400"
                    >
                      命中：{{ name }}
                    </span>
                  </div>
                </td>
                <td class="px-4 py-3 text-[hsl(var(--muted-foreground))]">{{ sourceName(item.source_id) }}</td>
                <td class="px-4 py-3 font-mono text-[hsl(var(--muted-foreground))]">{{ item.crawl_count }}</td>
                <td class="px-4 py-3 font-mono text-[hsl(var(--muted-foreground))]">{{ item.weight.toFixed(1) }}</td>
                <td class="px-4 py-3 text-[hsl(var(--muted-foreground))]">{{ formatDateTime(item.first_crawl_time) }}</td>
                <td class="px-4 py-3 text-[hsl(var(--muted-foreground))]">{{ formatDateTime(item.last_crawl_time) }}</td>
                <td class="px-4 py-3 text-right">
                  <button class="text-[11px] text-[hsl(var(--muted-foreground))] hover:text-indigo-400" @click="openDetail(item)">详情</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div v-if="total > pageSize" class="mt-4 shrink-0 flex items-center justify-between text-xs text-[hsl(var(--muted-foreground))]">
        <span>共 {{ total }} 条</span>
        <div class="flex items-center gap-2">
          <button class="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-2 py-1 disabled:opacity-40" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
          <span>{{ page }} / {{ totalPages }}</span>
          <button class="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-2 py-1 disabled:opacity-40" :disabled="page >= totalPages" @click="goPage(page + 1)">下一页</button>
        </div>
      </div>
    </div>

    <Modal v-model:open="detailModalOpen" :title="detailItem?.item.title || '条目详情'" :footer="null" width="620px">
      <div v-if="detailLoading" class="py-8 text-center text-xs text-[hsl(var(--muted-foreground))]">加载中…</div>
      <template v-else-if="detailItem">
        <div class="mb-4 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
          <div>
            <div class="text-[10px] text-[hsl(var(--muted-foreground))] uppercase">来源</div>
            <div class="font-semibold text-[hsl(var(--foreground))]">{{ sourceName(detailItem.item.source_id) }}</div>
          </div>
          <div>
            <div class="text-[10px] text-[hsl(var(--muted-foreground))] uppercase">当前榜位</div>
            <div class="font-semibold text-[hsl(var(--foreground))]">{{ detailItem.item.rank > 0 ? `#${detailItem.item.rank}` : '脱榜' }}</div>
          </div>
          <div>
            <div class="text-[10px] text-[hsl(var(--muted-foreground))] uppercase">历史最佳</div>
            <div class="font-semibold text-[hsl(var(--foreground))]">#{{ detailItem.item.best_rank }}</div>
          </div>
          <div>
            <div class="text-[10px] text-[hsl(var(--muted-foreground))] uppercase">权重</div>
            <div class="font-semibold text-[hsl(var(--foreground))]">{{ detailItem.item.weight.toFixed(1) }}</div>
          </div>
        </div>

        <div v-if="detailItem.item.hit_rules.length" class="mb-4 flex flex-wrap gap-1">
          <span v-for="name in detailItem.item.hit_rules" :key="name" class="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-amber-400">
            命中：{{ name }}
          </span>
        </div>

        <div class="mb-2 text-[11px] font-semibold text-[hsl(var(--muted-foreground))]">榜位曲线（含脱榜段）</div>
        <div v-if="curvePoints.length === 0" class="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6 text-center text-xs text-[hsl(var(--muted-foreground))]">
          暂无历史数据
        </div>
        <svg v-else :width="CHART_WIDTH" :height="CHART_HEIGHT" :viewBox="`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`" class="w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
          <!-- 正常榜位区 / 脱榜区分隔线 -->
          <line :x1="PADDING_X" :y1="OFFLIST_DIVIDER_Y" :x2="CHART_WIDTH - PADDING_X" :y2="OFFLIST_DIVIDER_Y" stroke="hsl(var(--border))" stroke-width="1" stroke-dasharray="3,3" />
          <text :x="PADDING_X" :y="OFFLIST_DIVIDER_Y + 14" class="fill-current text-[9px]" style="fill: hsl(var(--muted-foreground))">脱榜</text>

          <!-- 折线（脱榜段用玫红虚线区分） -->
          <path
            v-for="(seg, idx) in curveSegments"
            :key="idx"
            :d="seg.d"
            fill="none"
            :stroke="seg.offlist ? '#f43f5e' : '#6366f1'"
            stroke-width="2"
            :stroke-dasharray="seg.offlist ? '4,3' : undefined"
            stroke-linecap="round"
          />

          <!-- 数据点 -->
          <circle
            v-for="(p, idx) in curvePoints"
            :key="idx"
            :cx="p.x"
            :cy="p.y"
            r="3.5"
            :fill="p.rank === 0 ? '#f43f5e' : '#6366f1'"
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
