<script lang="ts" setup>
import type { EchartsUIType } from '@vben/plugins/echarts';

import type { MarketOverviewApi } from '#/api/core/market-overview';

import { computed, onMounted, ref, watch } from 'vue';

import { Page } from '@vben/common-ui';

import { chartColor } from '../_shared/chart-theme';
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
  Star,
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
  if (v === null || v === undefined) return 'text-[hsl(var(--muted-foreground))]';
  return v >= 0 ? 'text-destructive' : 'text-success';
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
  if (price === null || price === undefined) return { label: '暂无数据', color: 'text-[hsl(var(--muted-foreground))]' };
  if (price < 15) return { label: '低波动 · 市场情绪平稳', color: 'text-success' };
  if (price < 25) return { label: '中等波动 · 正常区间', color: 'text-warning' };
  return { label: '高波动 · 避险情绪升温', color: 'text-destructive' };
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
        lineStyle: { width: 2, color: CHART_LINE_COLORS[symbol] || chartColor('--muted-foreground') },
        data: allDates.map((d) => {
          const close = byDate.get(d);
          return close !== undefined && base ? Math.round(((close / base - 1) * 100 + Number.EPSILON) * 100) / 100 : null;
        }),
      };
    });

    renderEcharts({
      backgroundColor: 'transparent',
      grid: { left: 50, right: 20, top: 40, bottom: 30 },
      legend: { top: 0, textStyle: { color: chartColor('--muted-foreground'), fontSize: 11 } },
      tooltip: {
        trigger: 'axis',
        backgroundColor: chartColor('--card'),
        borderColor: chartColor('--border'),
        textStyle: { color: chartColor('--foreground'), fontSize: 11 },
        valueFormatter: (v: any) => (v === null ? '--' : `${v >= 0 ? '+' : ''}${v}%`),
      },
      xAxis: { type: 'category', data: allDates, axisLine: { lineStyle: { color: chartColor('--border') } }, axisLabel: { color: chartColor('--muted-foreground'), fontSize: 10 } },
      yAxis: {
        type: 'value',
        axisLabel: { color: chartColor('--muted-foreground'), fontSize: 10, formatter: '{value}%' },
        splitLine: { lineStyle: { color: chartColor('--border'), type: 'dashed' } },
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
const watchlistCount = ref(0);

async function loadEvents() {
  eventsLoading.value = true;
  try {
    const res = await getMarketEventsApi();
    events.value = res.events;
    eventsNote.value = res.reference_note;
    watchlistCount.value = res.watchlist_count ?? 0;
  } catch {
    events.value = [];
  } finally {
    eventsLoading.value = false;
  }
}

const EVENT_TYPE_META: Record<string, { bg: string; dot: string; label: string; text: string; }> = {
  fomc: { label: 'FOMC', dot: 'bg-primary', text: 'text-primary', bg: 'bg-primary/15 border-primary/30' },
  cpi: { label: 'CPI', dot: 'bg-warning', text: 'text-warning', bg: 'bg-warning/15 border-warning/30' },
  earnings: { label: '财报', dot: 'bg-success', text: 'text-success', bg: 'bg-success/15 border-success/30' },
  watchlist: { label: '关注股财报', dot: 'bg-primary', text: 'text-primary', bg: 'bg-primary/15 border-primary/30' },
};

// 事件在日历上用什么圆点颜色 / 在列表里用什么主色：关注股（自选股）优先
function eventDotClass(e: MarketOverviewApi.MarketEvent | undefined) {
  if (!e) return 'bg-slate-500';
  return e.group === 'watchlist' ? 'bg-primary' : EVENT_TYPE_META[e.type]?.dot || 'bg-slate-500';
}
function eventGroupMeta(e: MarketOverviewApi.MarketEvent) {
  if (e.group === 'watchlist') return EVENT_TYPE_META.watchlist!;
  return EVENT_TYPE_META[e.type]!;
}

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
    <div class="custom-scrollbar flex h-full flex-1 flex-col overflow-y-auto bg-[hsl(var(--background-deep))] p-4 select-none">
      <!-- Header -->
      <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 class="flex items-center gap-2 text-lg font-extrabold text-[hsl(var(--foreground))]">
            <Gauge class="h-5 w-5 text-primary" />
            <span>大盘行情</span>
          </h1>
          <p class="mt-0.5 text-[11px] text-[hsl(var(--muted-foreground))]">美股指数、相对表现走势、自选股财报与宏观事件日历</p>
        </div>
        <div class="flex items-center gap-3 text-xs text-[hsl(var(--muted-foreground))]">
          <span v-if="lastUpdated">更新于 {{ lastUpdated }}</span>
          <button
            class="flex items-center gap-1.5 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-1.5 font-bold text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
            :disabled="refreshing"
            @click="refreshAll"
          >
            <RefreshCw class="h-3.5 w-3.5" :class="refreshing ? 'animate-spin' : ''" />
            刷新
          </button>
        </div>
      </div>

      <div v-if="indicesError" class="mb-4 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-2 text-xs text-destructive">
        指数行情获取失败：{{ indicesError }}
      </div>

      <!-- 指数卡片 -->
      <div class="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
        <div v-for="idx in broadIndices" :key="idx.symbol" class="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] px-3 py-2.5">
          <div class="mb-0.5 flex items-center justify-between">
            <span class="text-[10px] font-semibold text-[hsl(var(--muted-foreground))]">{{ idx.name_cn }}</span>
            <component :is="(idx.change ?? 0) >= 0 ? TrendingUp : TrendingDown" class="h-3 w-3" :class="changeColorClass(idx.change)" />
          </div>
          <div v-if="!idx.available" class="py-1 text-[11px] text-[hsl(var(--muted-foreground))]">暂无数据</div>
          <template v-else>
            <div class="font-mono text-base font-black text-[hsl(var(--foreground))]">{{ formatPrice(idx.price) }}</div>
            <div class="font-mono text-[10px] font-bold" :class="changeColorClass(idx.change)">
              {{ formatSigned(idx.change) }} ({{ formatSigned(idx.change_percent) }}%)
            </div>
          </template>
        </div>

        <!-- VIX 单独一张卡片，不同的语义/配色（不是"涨跌"而是"情绪"） -->
        <div class="rounded-xl border border-warning/20 bg-gradient-to-br from-warning/5 to-[hsl(var(--card))] px-3 py-2.5">
          <div class="mb-0.5 flex items-center justify-between">
            <span class="text-[10px] font-semibold text-[hsl(var(--muted-foreground))]">{{ vixIndex?.name_cn || 'VIX' }}</span>
            <AlertTriangle class="h-3 w-3 text-warning" />
          </div>
          <template v-if="vixIndex?.available">
            <div class="font-mono text-base font-black text-[hsl(var(--foreground))]">{{ formatPrice(vixIndex.price) }}</div>
            <div class="text-[9px] font-bold" :class="vixSentiment(vixIndex.price).color">
              {{ vixSentiment(vixIndex.price).label }}
            </div>
          </template>
          <div v-else class="py-1 text-[11px] text-[hsl(var(--muted-foreground))]">暂无数据</div>
        </div>
      </div>

      <!-- 相对表现走势图 + 七姐妹财报 -->
      <div class="flex flex-col gap-3">
        <div class="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-3">
          <div class="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 class="text-xs font-bold text-[hsl(var(--muted-foreground))]">主要指数相对表现（涨跌幅归一化对比，不含 VIX）</h3>
              <p class="mt-0.5 text-[10px] text-[hsl(var(--muted-foreground))]">以周期起点为基准 0%，直接对比谁涨得多、谁跌得多</p>
            </div>
            <div class="flex items-center gap-1 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-1 text-[11px] font-semibold">
              <button
                v-for="p in PERIODS" :key="p"
                class="rounded px-2.5 py-1" :class="selectedPeriod === p ? 'bg-primary text-white' : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'"
                @click="selectedPeriod = p"
              >
                {{ p }}
              </button>
            </div>
          </div>
          <div v-if="chartError" class="flex h-[240px] items-center justify-center text-xs text-destructive">{{ chartError }}</div>
          <div v-else class="h-[240px]">
            <EchartsUI ref="chartRef" height="100%" width="100%" />
          </div>
        </div>

        <!-- 七姐妹财报速览 -->
        <div class="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-3">
          <div class="mb-2 flex items-center gap-2 text-xs font-bold text-[hsl(var(--muted-foreground))]">
            <Users class="h-3.5 w-3.5 text-primary" />
            <span>"七姐妹"财报速览</span>
          </div>
          <div class="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
            <div v-for="c in mag7" :key="c.symbol" class="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-2 text-center">
              <div class="font-mono text-[11px] font-extrabold text-[hsl(var(--foreground))]">{{ c.symbol }}</div>
              <div class="mb-0.5 text-[9px] text-[hsl(var(--muted-foreground))]">{{ c.name_cn }}</div>
              <template v-if="c.next_earnings_date">
                <div class="text-[10px] font-semibold text-primary">{{ c.next_earnings_date }}</div>
                <div class="text-[9px] text-[hsl(var(--muted-foreground))]">
                  {{ daysUntil(c.next_earnings_date)! >= 0 ? `${daysUntil(c.next_earnings_date)}天后` : '已发布' }}
                </div>
                <div v-if="c.eps_estimate" class="mt-0.5 font-mono text-[9px] text-[hsl(var(--muted-foreground))]">EPS预期 {{ c.eps_estimate.toFixed(2) }}</div>
              </template>
              <div v-else class="text-[10px] text-[hsl(var(--muted-foreground))]">暂无日期</div>
            </div>
          </div>
        </div>

        <!-- 近期重大事件：日历 + 当日详情 -->
        <div class="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3">
          <div class="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div class="flex items-center gap-2 text-xs font-bold text-[hsl(var(--foreground))]">
              <Calendar class="h-3.5 w-3.5 text-primary" />
              <span>事件日历</span>
              <span v-if="eventsNote" class="text-[10px] font-normal text-[hsl(var(--muted-foreground))]">· 已合并 {{ watchlistCount }} 只自选股财报</span>
            </div>
            <div class="flex items-center gap-3 text-[10px] font-semibold text-[hsl(var(--muted-foreground))]">
              <span class="flex items-center gap-1">
                <span class="h-2 w-2 rounded-full" :class="EVENT_TYPE_META.watchlist!.dot"></span>{{ EVENT_TYPE_META.watchlist!.label }}
              </span>
              <template v-for="(meta, type) in EVENT_TYPE_META" :key="type">
                <span v-if="type !== 'watchlist'" class="flex items-center gap-1">
                  <span class="h-2 w-2 rounded-full" :class="meta.dot"></span>{{ meta.label }}
                </span>
              </template>
            </div>
          </div>

          <div v-if="eventsLoading" class="py-10 text-center text-xs text-[hsl(var(--muted-foreground))]">加载中…</div>
          <div v-else class="flex flex-col gap-3 lg:flex-row">
            <!-- 月历 -->
            <div class="w-full shrink-0 lg:w-[340px]">
              <div class="mb-2 flex items-center justify-between">
                <button class="rounded-lg p-1.5 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--muted))] hover:text-[hsl(var(--foreground))]" @click="prevMonth">
                  <ChevronLeft class="h-4 w-4" />
                </button>
                <div class="flex items-center gap-2">
                  <span class="text-sm font-bold text-[hsl(var(--foreground))]">{{ calendarMonth.format('YYYY年M月') }}</span>
                  <button class="rounded border border-[hsl(var(--border))] px-1.5 py-0.5 text-[10px] font-semibold text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]" @click="jumpToToday">
                    今天
                  </button>
                </div>
                <button class="rounded-lg p-1.5 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--muted))] hover:text-[hsl(var(--foreground))]" @click="nextMonth">
                  <ChevronRight class="h-4 w-4" />
                </button>
              </div>
              <p v-if="!monthHasAnyEvent" class="mb-2 text-[10px] text-[hsl(var(--muted-foreground))]">本月窗口内暂无收录的事件</p>

              <div class="grid grid-cols-7 gap-1 text-center text-[10px] font-semibold text-[hsl(var(--muted-foreground))]">
                <div v-for="w in WEEKDAY_LABELS" :key="w" class="py-1">{{ w }}</div>
              </div>
              <div class="grid grid-cols-7 gap-1">
                <button
                  v-for="cell in calendarCells" :key="cell.date"
                  class="relative flex aspect-square flex-col items-center justify-center rounded-lg text-xs transition-all"
                  :class="[
                    !cell.isCurrentMonth ? 'text-slate-700' : cell.isWeekend ? 'text-[hsl(var(--muted-foreground))]' : 'text-[hsl(var(--muted-foreground))]',
                    selectedDate === cell.date ? 'bg-primary font-extrabold text-white' : cell.isToday ? 'border border-primary/60 font-bold' : 'hover:bg-[hsl(var(--muted))]',
                  ]"
                  @click="selectDay(cell)"
                >
                  <span>{{ cell.day }}</span>
                  <span v-if="cell.events.length > 0" class="mt-0.5 flex gap-0.5">
                    <span
                      v-for="t in [...new Set(cell.events.map((e) => (e.group === 'watchlist' ? 'watchlist' : e.type)))].slice(0, 3)"
                      :key="t"
                      class="h-1 w-1 rounded-full"
                      :class="selectedDate === cell.date ? 'bg-white' : eventDotClass(cell.events.find((e) => (e.group === 'watchlist' ? 'watchlist' : e.type) === t))"
                    ></span>
                  </span>
                </button>
              </div>
            </div>

            <!-- 当日详情 -->
            <div class="custom-scrollbar min-h-[240px] flex-1 overflow-y-auto">
              <div class="mb-2 text-[11px] font-bold text-[hsl(var(--muted-foreground))]">
                {{ dayjs(selectedDate).format('YYYY年M月D日') }}
                <span class="ml-1 text-[hsl(var(--muted-foreground))]">{{ eventTimeLabel(selectedDate) }}</span>
              </div>

              <div v-if="selectedDayEvents.length === 0" class="flex h-36 flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-[hsl(var(--border))] text-center">
                <Calendar class="h-6 w-6 text-[hsl(var(--muted-foreground))]" />
                <p class="text-xs text-[hsl(var(--muted-foreground))]">这天没有收录的事件</p>
              </div>

              <div v-else class="space-y-2">
                <div
                  v-for="(e, i) in selectedDayEvents" :key="`${e.type}-${e.symbol || ''}-${i}`"
                  class="rounded-xl border p-3"
                  :class="e.group === 'watchlist' ? 'border-primary/40 bg-primary/5' : 'border-[hsl(var(--border))] bg-[hsl(var(--background-deep))]'"
                >
                  <div class="flex items-center justify-between gap-2">
                    <span class="rounded border px-1.5 py-0.5 text-[10px] font-bold" :class="[eventGroupMeta(e).bg, eventGroupMeta(e).text]">
                      {{ eventGroupMeta(e).label }}
                    </span>
                    <div class="flex items-center gap-2">
                      <span v-if="e.group === 'watchlist'" class="flex items-center gap-0.5 text-[10px] font-bold text-primary">
                        <Star class="h-3 w-3 fill-primary text-primary" />
                        持仓关注
                      </span>
                      <span v-if="!e.confirmed" class="text-[10px] text-warning">日期待官方确认</span>
                    </div>
                  </div>
                  <div class="mt-1.5 text-xs font-bold text-[hsl(var(--foreground))]">{{ e.title }}</div>
                  <div class="mt-0.5 text-[11px] text-[hsl(var(--muted-foreground))]">{{ e.detail }}</div>
                  <div class="mt-1.5 flex items-center justify-between text-[10px] text-[hsl(var(--muted-foreground))]">
                    <span>{{ e.date_range }}</span>
                    <a v-if="e.source_url" :href="e.source_url" target="_blank" rel="noopener noreferrer" class="flex items-center gap-0.5 text-primary underline">
                      官方日程 <ExternalLink class="h-2.5 w-2.5" />
                    </a>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <p v-if="eventsNote" class="mt-4 border-t border-[hsl(var(--border))] pt-3 text-[10px] leading-relaxed text-[hsl(var(--muted-foreground))]">
            {{ eventsNote }}
          </p>
        </div>
      </div>
    </div>
  </Page>
</template>
