<script lang="ts" setup>
import type { EchartsUIType } from '@vben/plugins/echarts';

import type { MarketOverviewApi } from '#/api/core/market-overview';

import { computed, onMounted, ref, watch } from 'vue';

import { Page } from '@vben/common-ui';
import { EchartsUI, useEcharts } from '@vben/plugins/echarts';

import dayjs, { type Dayjs } from 'dayjs';
import {
  AlertTriangle,
  Calendar,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Gauge,
  RefreshCw,
  TrendingDown,
  TrendingUp,
  Users,
} from 'lucide-vue-next';

import {
  getMag7EarningsApi,
  getMarketEventsApi,
  getMarketIndexHistoryApi,
  getMarketIndicesApi,
} from '#/api/core/market-overview';

// 固定红涨绿跌，和自选股/K线页面同一套配色，保证整个"股票分析"模块视觉统一
function changeColorClass(v: null | number | undefined) {
  if (v === null || v === undefined) return 'text-slate-500';
  return v >= 0 ? 'text-rose-500' : 'text-emerald-400';
}
function formatSigned(v: null | number | undefined, digits = 2) {
  if (v === null || v === undefined) return '--';
  return `${v >= 0 ? '+' : ''}${v.toFixed(digits)}`;
}
function formatPrice(v: null | number | undefined) {
  if (v === null || v === undefined) return '--';
  return v >= 1000 ? v.toLocaleString('en-US', { maximumFractionDigits: 2 }) : v.toFixed(2);
}

// ----------------------------------------------------------------- 指数卡片 ----

const indices = ref<MarketOverviewApi.IndexQuote[]>([]);
const indicesError = ref('');
const lastUpdated = ref('');

async function loadIndices() {
  indicesError.value = '';
  try {
    const res = await getMarketIndicesApi();
    indices.value = res.indices;
    lastUpdated.value = new Date().toLocaleTimeString('zh-CN', { hour12: false });
  } catch (e: any) {
    indicesError.value = e.message || '加载失败';
  }
}

const vixIndex = computed(() => indices.value.find((i) => i.symbol === '^VIX'));
const broadIndices = computed(() => indices.value.filter((i) => i.symbol !== '^VIX'));

function vixSentiment(price: null | number | undefined) {
  if (price === null || price === undefined) return { label: '暂无数据', color: 'text-slate-400' };
  if (price < 15) return { label: '低波动 · 市场情绪平稳', color: 'text-emerald-400' };
  if (price < 25) return { label: '中等波动 · 正常区间', color: 'text-amber-400' };
  return { label: '高波动 · 避险情绪升温', color: 'text-rose-400' };
}

// --------------------------------------------------------- 相对表现走势图 ----

const PERIODS: MarketOverviewApi.HistoryPeriod[] = ['1M', '3M', '6M', 'YTD', '1Y'];
const selectedPeriod = ref<MarketOverviewApi.HistoryPeriod>('6M');
const chartError = ref('');
const chartRef = ref<EchartsUIType>();
const { renderEcharts } = useEcharts(chartRef);

// VIX 不参与相对表现对比图：VIX 的波动幅度经常是几十上百的百分比，混进去会把其它指数
// 个位数的涨跌幅压成一条直线，看不出相对强弱
const CHART_LINE_COLORS: Record<string, string> = {
  '^GSPC': '#38bdf8',
  '^IXIC': '#a855f7',
  '^NDX': '#f59e0b',
  '^DJI': '#34d399',
  '^RUT': '#ec4899',
};
// 走势图用的标的和名称是固定的（和后端 _INDEX_DEFINITIONS 排除 VIX 后一致），不依赖
// indices（指数卡片行情）加载完成——之前从 broadIndices.value 取 symbols 会在页面刚打开、
// loadIndices() 还没返回时拿到空数组，图表悄悄渲染成空的，只有等用户切换周期、重新触发
// loadChart 时 indices 早已加载完才会显示出来
const CHART_SYMBOLS: Array<{ name_cn: string; symbol: string; }> = [
  { symbol: '^GSPC', name_cn: '标普500' },
  { symbol: '^IXIC', name_cn: '纳斯达克综合指数' },
  { symbol: '^NDX', name_cn: '纳斯达克100' },
  { symbol: '^DJI', name_cn: '道琼斯工业指数' },
  { symbol: '^RUT', name_cn: '罗素2000' },
];

async function loadChart() {
  chartError.value = '';
  try {
    const symbols = CHART_SYMBOLS.map((i) => i.symbol);
    const results = await Promise.all(
      symbols.map((s) => getMarketIndexHistoryApi(s, selectedPeriod.value)),
    );

    const allDates = [...new Set(results.flatMap((r) => r.map((p) => p.date)))].sort();
    const series = symbols.map((symbol, idx) => {
      const points = results[idx]!;
      const base = points[0]?.close;
      const byDate = new Map(points.map((p) => [p.date, p.close]));
      const name = CHART_SYMBOLS.find((i) => i.symbol === symbol)?.name_cn || symbol;
      return {
        name,
        type: 'line' as const,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2, color: CHART_LINE_COLORS[symbol] || '#94a3b8' },
        data: allDates.map((d) => {
          const close = byDate.get(d);
          return close !== undefined && base ? Math.round(((close / base - 1) * 100 + Number.EPSILON) * 100) / 100 : null;
        }),
      };
    });

    renderEcharts({
      backgroundColor: 'transparent',
      grid: { left: 50, right: 20, top: 40, bottom: 30 },
      legend: { top: 0, textStyle: { color: '#94a3b8', fontSize: 11 } },
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(15,19,28,0.95)',
        borderColor: '#232B3E',
        textStyle: { color: '#e2e8f0', fontSize: 11 },
        valueFormatter: (v: any) => (v === null ? '--' : `${v >= 0 ? '+' : ''}${v}%`),
      },
      xAxis: { type: 'category', data: allDates, axisLine: { lineStyle: { color: '#1E2433' } }, axisLabel: { color: '#64748b', fontSize: 10 } },
      yAxis: {
        type: 'value',
        axisLabel: { color: '#64748b', fontSize: 10, formatter: '{value}%' },
        splitLine: { lineStyle: { color: '#1A2030', type: 'dashed' } },
      },
      series,
    } as any);
  } catch (e: any) {
    chartError.value = e.message || '加载走势失败';
  }
}

watch(selectedPeriod, loadChart);

// -------------------------------------------------------------- 七姐妹财报 ----

const mag7 = ref<MarketOverviewApi.Mag7Company[]>([]);

async function loadMag7() {
  try {
    const res = await getMag7EarningsApi();
    mag7.value = res.companies;
  } catch {
    mag7.value = [];
  }
}

function daysUntil(dateStr: null | string) {
  if (!dateStr) return null;
  return dayjs(dateStr).startOf('day').diff(dayjs().startOf('day'), 'day');
}

// ------------------------------------------------------------ 近期重大事件 ----

const events = ref<MarketOverviewApi.MarketEvent[]>([]);
const eventsLoading = ref(false);
const eventsNote = ref('');

async function loadEvents() {
  eventsLoading.value = true;
  try {
    const res = await getMarketEventsApi();
    events.value = res.events;
    eventsNote.value = res.reference_note;
  } catch {
    events.value = [];
  } finally {
    eventsLoading.value = false;
  }
}

const EVENT_TYPE_META: Record<string, { bg: string; dot: string; label: string; text: string; }> = {
  fomc: { label: 'FOMC', dot: 'bg-indigo-400', text: 'text-indigo-300', bg: 'bg-indigo-500/15 border-indigo-500/30' },
  cpi: { label: 'CPI', dot: 'bg-amber-400', text: 'text-amber-300', bg: 'bg-amber-500/15 border-amber-500/30' },
  earnings: { label: '财报', dot: 'bg-emerald-400', text: 'text-emerald-300', bg: 'bg-emerald-500/15 border-emerald-500/30' },
};

function eventTimeLabel(dateStr: string) {
  const days = daysUntil(dateStr)!;
  if (days === 0) return '今天';
  if (days === 1) return '明天';
  if (days > 1) return `${days}天后`;
  if (days === -1) return '昨天';
  return `${Math.abs(days)}天前`;
}

// -------------------------------------------------------------- 日历视图 ----

const calendarMonth = ref<Dayjs>(dayjs());
const selectedDate = ref<string>(dayjs().format('YYYY-MM-DD'));
const today = dayjs().format('YYYY-MM-DD');

const eventsByDate = computed(() => {
  const map = new Map<string, MarketOverviewApi.MarketEvent[]>();
  for (const e of events.value) {
    const list = map.get(e.date) ?? [];
    list.push(e);
    map.set(e.date, list);
  }
  return map;
});

interface CalendarCell {
  date: string;
  day: number;
  isCurrentMonth: boolean;
  isToday: boolean;
  isWeekend: boolean;
  events: MarketOverviewApi.MarketEvent[];
}

const WEEKDAY_LABELS = ['日', '一', '二', '三', '四', '五', '六'];

const calendarCells = computed<CalendarCell[]>(() => {
  const monthStart = calendarMonth.value.startOf('month');
  const gridStart = monthStart.subtract(monthStart.day(), 'day');
  const cells: CalendarCell[] = [];
  for (let i = 0; i < 42; i++) {
    const d = gridStart.add(i, 'day');
    const dateStr = d.format('YYYY-MM-DD');
    const weekday = d.day();
    cells.push({
      date: dateStr,
      day: d.date(),
      isCurrentMonth: d.month() === calendarMonth.value.month(),
      isToday: dateStr === today,
      isWeekend: weekday === 0 || weekday === 6,
      events: eventsByDate.value.get(dateStr) ?? [],
    });
  }
  return cells;
});

const selectedDayEvents = computed(() => eventsByDate.value.get(selectedDate.value) ?? []);
const monthHasAnyEvent = computed(() =>
  calendarCells.value.some((c) => c.isCurrentMonth && c.events.length > 0),
);

function selectDay(cell: CalendarCell) {
  selectedDate.value = cell.date;
  if (!cell.isCurrentMonth) calendarMonth.value = dayjs(cell.date);
}
function prevMonth() {
  calendarMonth.value = calendarMonth.value.subtract(1, 'month');
}
function nextMonth() {
  calendarMonth.value = calendarMonth.value.add(1, 'month');
}
function jumpToToday() {
  calendarMonth.value = dayjs();
  selectedDate.value = today;
}

// 事件数据回来后：默认选中"今天或之后最近一个有事件的日子"，日历翻到那个月——
// 避免默认停在当月却没有任何事件、右侧详情面板空空如也的情况
watch(events, (list) => {
  if (list.length === 0) return;
  const upcoming = list.find((e) => e.date >= today);
  const target = upcoming?.date ?? list.at(-1)?.date ?? today;
  selectedDate.value = target;
  calendarMonth.value = dayjs(target);
});

// -------------------------------------------------------------------- 刷新 ----

const refreshing = ref(false);
async function refreshAll() {
  refreshing.value = true;
  try {
    await Promise.all([loadIndices(), loadChart(), loadMag7(), loadEvents()]);
  } finally {
    refreshing.value = false;
  }
}

onMounted(() => {
  loadIndices();
  loadChart();
  loadMag7();
  loadEvents();
});
</script>

<template>
  <Page :auto-content-height="true" content-class="!p-0">
    <div class="custom-scrollbar flex h-full flex-1 flex-col overflow-y-auto bg-[#0B0E14] p-6 select-none">
      <!-- Header -->
      <div class="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 class="flex items-center gap-2 text-xl font-extrabold text-white">
            <Gauge class="h-5 w-5 text-indigo-400" />
            <span>大盘行情</span>
          </h1>
          <p class="mt-1 text-xs text-slate-400">主要美股指数、相对表现走势与近期重大事件一览</p>
        </div>
        <div class="flex items-center gap-3 text-xs text-slate-500">
          <span v-if="lastUpdated">更新于 {{ lastUpdated }}</span>
          <button
            class="flex items-center gap-1.5 rounded-lg border border-[#232B3E] bg-[#121622] px-3 py-1.5 font-bold text-slate-400 hover:text-slate-200"
            :disabled="refreshing"
            @click="refreshAll"
          >
            <RefreshCw class="h-3.5 w-3.5" :class="refreshing ? 'animate-spin' : ''" />
            刷新
          </button>
        </div>
      </div>

      <div v-if="indicesError" class="mb-4 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-2 text-xs text-rose-300">
        指数行情获取失败：{{ indicesError }}
      </div>

      <!-- 指数卡片 -->
      <div class="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        <div v-for="idx in broadIndices" :key="idx.symbol" class="rounded-2xl border border-[#1E2433] bg-[#0F131C] p-3.5">
          <div class="mb-1 flex items-center justify-between">
            <span class="text-[11px] font-semibold text-slate-400">{{ idx.name_cn }}</span>
            <component :is="(idx.change ?? 0) >= 0 ? TrendingUp : TrendingDown" class="h-3.5 w-3.5" :class="changeColorClass(idx.change)" />
          </div>
          <div v-if="!idx.available" class="py-1.5 text-xs text-slate-500">暂无数据</div>
          <template v-else>
            <div class="font-mono text-lg font-black text-white">{{ formatPrice(idx.price) }}</div>
            <div class="font-mono text-[11px] font-bold" :class="changeColorClass(idx.change)">
              {{ formatSigned(idx.change) }} ({{ formatSigned(idx.change_percent) }}%)
            </div>
          </template>
        </div>

        <!-- VIX 单独一张卡片，不同的语义/配色（不是"涨跌"而是"情绪"） -->
        <div class="rounded-2xl border border-amber-500/20 bg-gradient-to-br from-amber-500/5 to-[#0F131C] p-3.5">
          <div class="mb-1 flex items-center justify-between">
            <span class="text-[11px] font-semibold text-slate-400">{{ vixIndex?.name_cn || 'VIX' }}</span>
            <AlertTriangle class="h-3.5 w-3.5 text-amber-400" />
          </div>
          <template v-if="vixIndex?.available">
            <div class="font-mono text-lg font-black text-white">{{ formatPrice(vixIndex.price) }}</div>
            <div class="text-[10px] font-bold" :class="vixSentiment(vixIndex.price).color">
              {{ vixSentiment(vixIndex.price).label }}
            </div>
          </template>
          <div v-else class="py-1.5 text-xs text-slate-500">暂无数据</div>
        </div>
      </div>

      <!-- 相对表现走势图 + 七姐妹财报 -->
      <div class="flex flex-col gap-4">
        <div class="rounded-2xl border border-[#1E2433] bg-[#0F131C] p-4 shadow-inner">
          <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 class="text-xs font-bold text-slate-300">主要指数相对表现（涨跌幅归一化对比，不含 VIX）</h3>
              <p class="mt-0.5 text-[10px] text-slate-500">以周期起点为基准 0%，直接对比谁涨得多、谁跌得多</p>
            </div>
            <div class="flex items-center gap-1 rounded-lg border border-[#232B3E] bg-[#121622] p-1 text-[11px] font-semibold">
              <button
                v-for="p in PERIODS" :key="p"
                class="rounded px-2.5 py-1" :class="selectedPeriod === p ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-slate-200'"
                @click="selectedPeriod = p"
              >
                {{ p }}
              </button>
            </div>
          </div>
          <div v-if="chartError" class="flex h-[320px] items-center justify-center text-xs text-rose-400">{{ chartError }}</div>
          <div v-else class="h-[320px]">
            <EchartsUI ref="chartRef" height="100%" width="100%" />
          </div>
        </div>

        <!-- 七姐妹财报速览 -->
        <div class="rounded-2xl border border-[#1E2433] bg-[#0F131C] p-4">
          <div class="mb-3 flex items-center gap-2 text-xs font-bold text-slate-300">
            <Users class="h-4 w-4 text-indigo-400" />
            <span>"七姐妹"财报速览</span>
          </div>
          <div class="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
            <div v-for="c in mag7" :key="c.symbol" class="rounded-xl border border-[#232B3E] bg-[#121622] p-2.5 text-center">
              <div class="font-mono text-xs font-extrabold text-white">{{ c.symbol }}</div>
              <div class="mb-1 text-[10px] text-slate-500">{{ c.name_cn }}</div>
              <template v-if="c.next_earnings_date">
                <div class="text-[10px] font-semibold text-indigo-300">{{ c.next_earnings_date }}</div>
                <div class="text-[9px] text-slate-500">
                  {{ daysUntil(c.next_earnings_date)! >= 0 ? `${daysUntil(c.next_earnings_date)}天后` : '已发布' }}
                </div>
                <div v-if="c.eps_estimate" class="mt-1 font-mono text-[10px] text-slate-400">EPS预期 {{ c.eps_estimate.toFixed(2) }}</div>
              </template>
              <div v-else class="text-[10px] text-slate-500">暂无日期</div>
            </div>
          </div>
        </div>

        <!-- 近期重大事件：日历 + 当日详情 -->
        <div class="rounded-2xl border border-[#232B3E] bg-[#121622] p-4">
          <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div class="flex items-center gap-2 text-xs font-bold text-white">
              <Calendar class="h-4 w-4 text-indigo-400" />
              <span>近期重大事件</span>
            </div>
            <div class="flex items-center gap-3 text-[10px] font-semibold text-slate-400">
              <span v-for="(meta, type) in EVENT_TYPE_META" :key="type" class="flex items-center gap-1">
                <span class="h-2 w-2 rounded-full" :class="meta.dot"></span>{{ meta.label }}
              </span>
            </div>
          </div>

          <div v-if="eventsLoading" class="py-10 text-center text-xs text-slate-500">加载中…</div>
          <div v-else class="flex flex-col gap-4 lg:flex-row">
            <!-- 月历 -->
            <div class="w-full shrink-0 lg:w-[380px]">
              <div class="mb-2 flex items-center justify-between">
                <button class="rounded-lg p-1.5 text-slate-400 hover:bg-[#1E2538] hover:text-white" @click="prevMonth">
                  <ChevronLeft class="h-4 w-4" />
                </button>
                <div class="flex items-center gap-2">
                  <span class="text-sm font-bold text-white">{{ calendarMonth.format('YYYY年M月') }}</span>
                  <button class="rounded border border-[#232B3E] px-1.5 py-0.5 text-[10px] font-semibold text-slate-400 hover:text-white" @click="jumpToToday">
                    今天
                  </button>
                </div>
                <button class="rounded-lg p-1.5 text-slate-400 hover:bg-[#1E2538] hover:text-white" @click="nextMonth">
                  <ChevronRight class="h-4 w-4" />
                </button>
              </div>
              <p v-if="!monthHasAnyEvent" class="mb-2 text-[10px] text-slate-500">本月窗口内暂无收录的重大事件</p>

              <div class="grid grid-cols-7 gap-1 text-center text-[10px] font-semibold text-slate-500">
                <div v-for="w in WEEKDAY_LABELS" :key="w" class="py-1">{{ w }}</div>
              </div>
              <div class="grid grid-cols-7 gap-1">
                <button
                  v-for="cell in calendarCells" :key="cell.date"
                  class="relative flex aspect-square flex-col items-center justify-center rounded-lg text-xs transition-all"
                  :class="[
                    !cell.isCurrentMonth ? 'text-slate-700' : cell.isWeekend ? 'text-slate-500' : 'text-slate-300',
                    selectedDate === cell.date ? 'bg-indigo-600 font-extrabold text-white' : cell.isToday ? 'border border-indigo-500/60 font-bold' : 'hover:bg-[#1E2538]',
                  ]"
                  @click="selectDay(cell)"
                >
                  <span>{{ cell.day }}</span>
                  <span v-if="cell.events.length > 0" class="mt-0.5 flex gap-0.5">
                    <span
                      v-for="t in [...new Set(cell.events.map((e) => e.type))].slice(0, 3)" :key="t"
                      class="h-1 w-1 rounded-full" :class="selectedDate === cell.date ? 'bg-white' : EVENT_TYPE_META[t]?.dot"
                    ></span>
                  </span>
                </button>
              </div>
            </div>

            <!-- 当日详情 -->
            <div class="custom-scrollbar min-h-[280px] flex-1 overflow-y-auto">
              <div class="mb-2 text-[11px] font-bold text-slate-400">
                {{ dayjs(selectedDate).format('YYYY年M月D日') }}
                <span class="ml-1 text-slate-600">{{ eventTimeLabel(selectedDate) }}</span>
              </div>

              <div v-if="selectedDayEvents.length === 0" class="flex h-40 flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-[#232B3E] text-center">
                <Calendar class="h-6 w-6 text-slate-600" />
                <p class="text-xs text-slate-500">这天没有收录的重大事件</p>
              </div>

              <div v-else class="space-y-2">
                <div v-for="(e, i) in selectedDayEvents" :key="`${e.type}-${i}`" class="rounded-xl border border-[#232B3E] bg-[#0B0E14] p-3">
                  <div class="flex items-center justify-between gap-2">
                    <span class="rounded border px-1.5 py-0.5 text-[10px] font-bold" :class="[EVENT_TYPE_META[e.type]?.bg, EVENT_TYPE_META[e.type]?.text]">
                      {{ EVENT_TYPE_META[e.type]?.label }}
                    </span>
                    <span v-if="!e.confirmed" class="text-[10px] text-amber-400">日期待官方确认</span>
                  </div>
                  <div class="mt-1.5 text-xs font-bold text-white">{{ e.title }}</div>
                  <div class="mt-0.5 text-[11px] text-slate-400">{{ e.detail }}</div>
                  <div class="mt-1.5 flex items-center justify-between text-[10px] text-slate-500">
                    <span>{{ e.date_range }}</span>
                    <a v-if="e.source_url" :href="e.source_url" target="_blank" rel="noopener noreferrer" class="flex items-center gap-0.5 text-indigo-400 underline">
                      官方日程 <ExternalLink class="h-2.5 w-2.5" />
                    </a>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <p v-if="eventsNote" class="mt-4 border-t border-[#232B3E] pt-3 text-[10px] leading-relaxed text-slate-500">
            {{ eventsNote }}
          </p>
        </div>
      </div>
    </div>
  </Page>
</template>
