<script lang="ts" setup>
import type { EchartsUIType } from '@vben/plugins/echarts';
import type { CandlestickData } from '../_shared/types';

import { computed, ref, watch } from 'vue';

import { Page } from '@vben/common-ui';
import { EchartsUI, useEcharts } from '@vben/plugins/echarts';

import { Activity, Calendar, Layers, Maximize2, RotateCcw, TrendingDown, TrendingUp, ZoomIn, ZoomOut } from 'lucide-vue-next';

import { getStockKlineApi } from '#/api/core/stock';
import { chartColor } from '../_shared/chart-theme';

import { selectedStock as stock } from '../_shared/stock-state';

// 固定红涨绿跌（参考项目原来的切换开关在被丢弃的顶部栏里，这次不做那个开关）
const colorMode = 'cn' as const;

const timeframe = ref<'1D' | '1M' | '1W' | '1Y'>('1D');
const showMA = ref(true);
const indicator = ref<'macd' | 'rsi'>('macd');

// 之前"周K/日K"这类文案在模板里到处手写 timeframe === '1W' ? 周 : 日 的二选一三元表达式，
// 选中月K (1M) 的时候永远被归到"日"那一支、显示成"日K线模式"——和当前选中的 tab 对不上。
// 统一收成这一个 computed，各处引用同一份，不会再有哪个角落漏改
const timeframeShortLabel = computed(() => {
  if (timeframe.value === '1W') return '周';
  if (timeframe.value === '1M' || timeframe.value === '1Y') return '月';
  return '日';
});
const timeframeFullLabel = computed(() => {
  if (timeframe.value === '1W') return '周K线 (Weekly)';
  if (timeframe.value === '1M') return '月K线';
  if (timeframe.value === '1Y') return '年K线';
  return '日K线';
});
const candleModeLabel = computed(() => {
  if (timeframe.value === '1W') return '周K线模式 (Weekly Candle)';
  if (timeframe.value === '1M') return '月K线模式 (Monthly Candle)';
  if (timeframe.value === '1Y') return '年K线模式 (Yearly Candle)';
  return '日K线模式 (Daily Candle)';
});
const trendCommentary = computed(() => {
  if (!stock.value) return '请先在自选股选择一只股票，再查看量化信号。';
  if (timeframe.value === '1W') return '周K线趋势呈现稳健扩张通道，周MACD多头金叉发散，中长线资金控盘度较高。';
  if (timeframe.value === '1M' || timeframe.value === '1Y') return '月K线维持中期上升结构，MA20 月均线仍具支撑，长线持仓意愿偏强。';
  return `基于日线收盘形态与均线系统，股价维持在 MA20 趋势线上方，日线 RSI (${stock.value.rsi ?? '--'}) 提示短期偏多发散。`;
});

// ------------------------------------------------------- 真实K线（yfinance）----
// 日K/周K/月K 各自独立向后端拉一份（interval=1d/1wk/1mo，各自真实聚合过的K线，不是
// 同一份日K换个标签），拉到过的缓存在 stock.kline1D/1W/1M 上，切 tab 回来不重复请求

const klineLoading = ref(false);
const klineError = ref('');
// 记录哪些 (symbol:interval) 已经加载过真实数据——自选股列表/其他页面带过来的
// kline1D/1W/1M 可能只是行情快照级数据，如果按"有没有数据"判断就会挡住真实K线请求。
// 真实加载成功后置 true，之后切回来不再重复请求。
const loadedKeys = ref<Record<string, boolean>>({});

async function loadKline(symbol: string, interval: '1d' | '1mo' | '1wk') {
  klineLoading.value = true;
  klineError.value = '';
  const key = `${symbol}:${interval}`;
  try {
    const data = await getStockKlineApi(symbol, interval);
    if (interval === '1d') stock.value!.kline1D = data;
    else if (interval === '1wk') stock.value!.kline1W = data;
    else stock.value!.kline1M = data;
    loadedKeys.value[key] = true;
  } catch (e: any) {
    klineError.value = e.message || '获取K线失败';
  } finally {
    klineLoading.value = false;
  }
}

function ensureKlineLoaded() {
  const symbol = stock.value?.symbol;
  if (!symbol) return;
  let interval: '1d' | '1wk' | '1mo';
  if (timeframe.value === '1W') interval = '1wk';
  else if (timeframe.value === '1M' || timeframe.value === '1Y') interval = '1mo';
  else interval = '1d';
  const key = `${symbol}:${interval}`;
  if (loadedKeys.value[key]) return;
  loadKline(symbol, interval);
}

watch(() => stock.value?.symbol, ensureKlineLoaded, { immediate: true });
watch(timeframe, ensureKlineLoaded);

const upColor = computed(() => (colorMode === 'cn' ? '#f43f5e' : '#34d399'));
const downColor = computed(() => (colorMode === 'cn' ? '#34d399' : '#f43f5e'));

// 全部真实历史都交给 ECharts 的 dataZoom 去管理平移/缩放，不再像手写 SVG 那样为了不挤成
// 一坨而强行只截取最近 N 根——数据完整，只是默认视窗停在最近一段，用户可以顺滑拖动/滚轮
// 缩放看更早的历史
const candles = computed<CandlestickData[]>(() => {
  if (timeframe.value === '1W') {
    return stock.value?.kline1W && stock.value.kline1W.length > 0 ? stock.value.kline1W : stock.value?.kline1D || [];
  }
  if (timeframe.value === '1M' || timeframe.value === '1Y') {
    return stock.value?.kline1M && stock.value.kline1M.length > 0 ? stock.value.kline1M : stock.value?.kline1D || [];
  }
  return stock.value?.kline1D || [];
});

const DEFAULT_VISIBLE_CANDLES = 60;
// 右侧"周期统计"卡片对应图表默认停留的那个视窗（最近约60根），不是全部历史——用户拖动缩放
// 看更早的数据时，这几张卡片本来就该继续显示"最近周期"的统计，不用跟着联动
const defaultWindowCandles = computed(() => {
  const all = candles.value;
  return all.length > DEFAULT_VISIBLE_CANDLES ? all.slice(-DEFAULT_VISIBLE_CANDLES) : all;
});

const lastCandle = computed<CandlestickData>(() => {
  const window_ = defaultWindowCandles.value;
  if (!window_.length) {
    const price = stock.value?.price ?? 0;
    return { time: '', open: price, high: price, low: price, close: price, volume: 1_000_000 };
  }
  return window_[window_.length - 1]!;
});
const prevCandle = computed(() => {
  const window_ = defaultWindowCandles.value;
  if (window_.length < 2) return lastCandle.value;
  return window_[window_.length - 2]!;
});

const openPrice = computed(() => lastCandle.value.open);
const prevClose = computed(() => prevCandle.value.close);
const highPrice = computed(() => Math.max(...defaultWindowCandles.value.map((c) => c.high)));
const lowPrice = computed(() => Math.min(...defaultWindowCandles.value.map((c) => c.low)));
const amplitude = computed(() => (((highPrice.value - lowPrice.value) / (prevClose.value || 1)) * 100).toFixed(2));

// --------------------------------------------------------------- ECharts ----

const chartRef = ref<EchartsUIType>();
const { renderEcharts, getChartInstance } = useEcharts(chartRef);

// ------------------------------------------------------- 视图控制（更友好的拖动/缩放交互）----
// 视图状态由 datazoom 事件实时同步，视图工具条用 dispatchAction 直接驱动图表——
// 不重渲染、不丢动画，拖动/缩放/复位全程丝滑。

const zoomState = ref({ startPct: 0, endPct: 100, startIndex: 0, endIndex: 0, total: 0 });
let chartEventsBound = false;

function applyZoom(startPct: number, endPct: number) {
  const chart = getChartInstance();
  if (!chart) return;
  const s = Math.max(0, Math.min(100, startPct));
  const e = Math.max(0, Math.min(100, endPct));
  if (e - s < 2) return; // 至少保留 2% 视窗，防止缩到一条线
  chart.dispatchAction({
    type: 'dataZoom',
    start: s,
    end: e,
    animation: { duration: 250, easing: 'cubicOut' } as any,
  });
}

function zoomIn() {
  const { startPct, endPct } = zoomState.value;
  const w = endPct - startPct;
  applyZoom(startPct + w * 0.12, endPct - w * 0.12);
}
function zoomOut() {
  const { startPct, endPct } = zoomState.value;
  const w = endPct - startPct;
  applyZoom(startPct - w * 0.12, endPct + w * 0.12);
}
function resetView() {
  const data = candles.value;
  const start = data.length > DEFAULT_VISIBLE_CANDLES
    ? ((data.length - DEFAULT_VISIBLE_CANDLES) / data.length) * 100
    : 0;
  applyZoom(start, 100);
}
function showAll() {
  applyZoom(0, 100);
}

/** 视窗定位到最近 N 根K线（日K下"近半年/近一年"快捷切换） */
function showRecent(count: number) {
  const total = candles.value.length;
  const n = Math.min(count, total);
  applyZoom(((total - n) / total) * 100, 100);
}

const visibleRangeLabel = computed(() => {
  const { startIndex, endIndex, total } = zoomState.value;
  if (!total) return '';
  const start = candles.value[startIndex];
  const end = candles.value[endIndex];
  const range = start && end && start !== end ? `${start.time} ~ ${end.time}` : '';
  return `视窗 ${endIndex - startIndex + 1}/${total} 根${range ? ` · ${range}` : ''}`;
});

function bindChartEvents(chart: any) {
  if (chartEventsBound) return;
  chartEventsBound = true;
  chart.on('datazoom', (params: any) => {
    const p = params.batch?.[0] ?? params;
    if (p.start === undefined || p.end === undefined) return;
    const data = candles.value;
    const total = data.length;
    const startPct = p.start;
    const endPct = p.end;
    // category 轴 dataZoom 的 startValue/endValue 就是数据索引
    const startIndex = p.startValue !== undefined ? Math.round(p.startValue) : Math.round((startPct / 100) * total);
    const endIndex = p.endValue !== undefined ? Math.round(p.endValue) : Math.round((endPct / 100) * total);
    zoomState.value = {
      startPct,
      endPct,
      startIndex: Math.max(0, Math.min(total - 1, startIndex)),
      endIndex: Math.max(0, Math.min(total - 1, endIndex)),
      total,
    };
  });
  chart.on('dblclick', () => resetView());
}

function buildOption() {
  const data = candles.value;
  const times = data.map((c) => c.time);

  const volumeData = data.map((c) => ({
    value: c.volume,
    itemStyle: { color: c.close >= c.open ? upColor.value : downColor.value },
  }));
  const macdHistData = data.map((c) => ({
    value: c.macdHist ?? null,
    itemStyle: { color: (c.macdHist ?? 0) >= 0 ? upColor.value : downColor.value },
  }));

  const startPercent = data.length > DEFAULT_VISIBLE_CANDLES ? ((data.length - DEFAULT_VISIBLE_CANDLES) / data.length) * 100 : 0;

  return {
    animation: true,
    animationDuration: 200,
    animationDurationUpdate: 350,
    animationEasing: 'cubicOut',
    animationEasingUpdate: 'cubicOut',
    animationThreshold: 1200,
    backgroundColor: 'transparent',
    grid: [
      { left: 56, right: 16, top: 8, height: '54%' },
      { left: 56, right: 16, top: '62%', height: '14%' },
      { left: 56, right: 16, top: '80%', height: '16%' },
    ],
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    xAxis: [
      { type: 'category', data: times, gridIndex: 0, axisLine: { lineStyle: { color: chartColor('--border') } }, axisLabel: { show: false }, axisTick: { show: false }, splitLine: { show: false } },
      { type: 'category', data: times, gridIndex: 1, axisLine: { lineStyle: { color: chartColor('--border') } }, axisLabel: { show: false }, axisTick: { show: false }, splitLine: { show: false } },
      { type: 'category', data: times, gridIndex: 2, axisLine: { lineStyle: { color: chartColor('--border') } }, axisLabel: { color: chartColor('--muted-foreground'), fontSize: 10 }, splitLine: { show: false } },
    ],
    yAxis: [
      { scale: true, gridIndex: 0, axisLine: { show: false }, axisLabel: { color: chartColor('--muted-foreground'), fontSize: 10 }, splitLine: { lineStyle: { color: chartColor('--border'), type: 'dashed' } } },
      { scale: true, gridIndex: 1, axisLine: { show: false }, axisLabel: { show: false }, splitLine: { show: false } },
      { scale: true, gridIndex: 2, axisLine: { show: false }, axisLabel: { color: chartColor('--muted-foreground'), fontSize: 10 }, splitLine: { show: false } },
    ],
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: [0, 1, 2],
        start: startPercent,
        end: 100,
        zoomOnMouseWheel: true,
        moveOnMouseMove: true,
        moveOnMouseWheel: false,
        preventDefaultMouseMove: true,
      },
      {
        type: 'slider',
        xAxisIndex: [0, 1, 2],
        start: startPercent,
        end: 100,
        height: 16,
        bottom: 4,
        realtime: true,
        showDetail: true,
        brushSelect: false,
        moveHandleSize: 20,
        handleSize: '100%',
        borderColor: 'transparent',
        backgroundColor: chartColor('--muted'),
        fillerColor: 'rgba(99,102,241,0.22)',
        handleStyle: { color: chartColor('--primary'), borderColor: chartColor('--primary'), borderWidth: 1, borderRadius: 2 },
        moveHandleStyle: { color: chartColor('--primary'), borderColor: chartColor('--primary') },
        dataBackground: {
          lineStyle: { color: '#2a3350', width: 1 },
          areaStyle: { color: 'rgba(99,102,241,0.06)' },
        },
        selectedDataBackground: {
          lineStyle: { color: chartColor('--primary'), width: 1 },
          areaStyle: { color: 'rgba(99,102,241,0.12)' },
        },
        textStyle: { color: chartColor('--muted-foreground'), fontSize: 9 },
        emphasis: { handleStyle: { color: chartColor('--primary') }, moveHandleStyle: { color: chartColor('--primary') } },
      },
    ],
    tooltip: {
      trigger: 'axis',
      triggerOn: 'mousemove|click',
      axisPointer: { type: 'cross', crossStyle: { color: '#475569' }, label: { backgroundColor: '#1E2538' } },
      backgroundColor: chartColor('--card'),
      borderColor: chartColor('--border'),
      textStyle: { color: chartColor('--foreground'), fontSize: 11 },
      formatter(params: any[]) {
        const candle = params.find((p) => p.seriesType === 'candlestick');
        const lines: string[] = [];
        if (candle) {
          const [open = 0, close = 0, low = 0, high = 0] = candle.data as number[];
          lines.push(`<b>${candle.axisValue}</b>`);
          lines.push(`开: $${open.toFixed(2)}  收: $${close.toFixed(2)}`);
          lines.push(`高: $${high.toFixed(2)}  低: $${low.toFixed(2)}`);
        }
        for (const p of params) {
          if (p.seriesType === 'candlestick' || p.seriesName === '成交量') continue;
          if (p.value === null || p.value === undefined) continue;
          const val = Array.isArray(p.value) ? p.value[1] : p.value;
          lines.push(`${p.marker}${p.seriesName}: ${Number(val).toFixed(2)}`);
        }
        return lines.join('<br/>');
      },
    },
    series: [
      {
        name: '价格',
        type: 'candlestick',
        data: data.map((c) => [c.open, c.close, c.low, c.high]),
        itemStyle: { color: upColor.value, color0: downColor.value, borderColor: upColor.value, borderColor0: downColor.value },
        xAxisIndex: 0,
        yAxisIndex: 0,
        markPoint: {
          symbolSize: 0,
          label: { fontSize: 10, fontWeight: 'bold' },
          data: [
            { type: 'max', valueDim: 'highest', name: '高', label: { color: upColor.value, formatter: (p: any) => `高 $${p.value}`, position: 'top' } },
            { type: 'min', valueDim: 'lowest', name: '低', label: { color: downColor.value, formatter: (p: any) => `低 $${p.value}`, position: 'bottom' } },
          ],
        },
      },
      ...(showMA.value
        ? [
            { name: 'MA5', type: 'line', data: data.map((c) => c.ma5 ?? null), xAxisIndex: 0, yAxisIndex: 0, smooth: true, showSymbol: false, lineStyle: { width: 1.5, color: '#38bdf8' } },
            { name: 'MA20', type: 'line', data: data.map((c) => c.ma20 ?? null), xAxisIndex: 0, yAxisIndex: 0, smooth: true, showSymbol: false, lineStyle: { width: 1.5, color: '#a855f7' } },
          ]
        : []),
      { name: '成交量', type: 'bar', data: volumeData, xAxisIndex: 1, yAxisIndex: 1, barMaxWidth: 12 },
      ...(indicator.value === 'macd'
        ? [
            { name: 'DIF', type: 'line', data: data.map((c) => c.macdDif ?? null), xAxisIndex: 2, yAxisIndex: 2, smooth: true, showSymbol: false, lineStyle: { width: 1.3, color: '#f59e0b' } },
            { name: 'DEA', type: 'line', data: data.map((c) => c.macdDea ?? null), xAxisIndex: 2, yAxisIndex: 2, smooth: true, showSymbol: false, lineStyle: { width: 1.3, color: '#06b6d4' } },
            { name: 'MACD', type: 'bar', data: macdHistData, xAxisIndex: 2, yAxisIndex: 2, barMaxWidth: 8 },
          ]
        : [
            { name: 'RSI', type: 'line', data: data.map((c) => c.rsi ?? null), xAxisIndex: 2, yAxisIndex: 2, smooth: true, showSymbol: false, lineStyle: { width: 1.5, color: '#ec4899' },
              markLine: { symbol: 'none', silent: true, lineStyle: { type: 'dashed', color: chartColor('--border') }, label: { color: chartColor('--muted-foreground'), fontSize: 9 }, data: [{ yAxis: 70 }, { yAxis: 30 }] } },
          ]),
    ],
  };
}

watch(
  [candles, showMA, indicator],
  async () => {
    if (candles.value.length === 0) return;
    const chart = await renderEcharts(buildOption() as any);
    bindChartEvents(chart);
    // 初始化视窗状态（最近 60 根）
    const total = candles.value.length;
    const startIndex = Math.max(0, total - DEFAULT_VISIBLE_CANDLES);
    zoomState.value = {
      startPct: total > DEFAULT_VISIBLE_CANDLES ? ((total - DEFAULT_VISIBLE_CANDLES) / total) * 100 : 0,
      endPct: 100,
      startIndex,
      endIndex: total - 1,
      total,
    };
  },
  { immediate: true, deep: false },
);
</script>

<template>
  <Page :auto-content-height="true" content-class="!p-0">
    <div class="flex h-full flex-col overflow-hidden bg-[hsl(var(--background-deep))] text-[hsl(var(--foreground))] select-none">
      <div v-if="klineLoading" class="shrink-0 border-b border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] px-6 py-1.5 text-xs text-[hsl(var(--muted-foreground))]">
        正在从 Yahoo Finance 获取 {{ stock?.symbol || '--' }} {{ timeframeShortLabel }}K线…
      </div>
      <div v-else-if="klineError" class="shrink-0 border-b border-destructive/30 bg-destructive/10 px-6 py-1.5 text-xs text-destructive">
        获取真实{{ timeframeShortLabel }}K线失败：{{ klineError }}
      </div>
      <!-- Stock Summary Header -->
      <template v-if="stock">
        <div class="flex min-h-16 shrink-0 flex-wrap items-center justify-between gap-x-2 gap-y-2 border-b border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] px-6 py-2">
        <div class="flex flex-wrap items-center gap-x-6 gap-y-1">
          <div>
            <div class="flex items-center gap-2">
              <h1 class="shrink-0 text-2xl font-extrabold tracking-tight text-[hsl(var(--foreground))]">{{ stock.symbol }}</h1>
              <span class="max-w-[220px] truncate text-sm font-medium text-[hsl(var(--muted-foreground))]" :title="stock.name">{{ stock.name }}</span>
              <span class="shrink-0 rounded border border-primary/30 bg-primary/15 px-2.5 py-0.5 text-xs font-bold text-primary">
                {{ stock.sector }} | {{ timeframeFullLabel }}
              </span>
            </div>
          </div>

          <div class="flex items-baseline gap-2 font-mono">
            <span class="text-2xl font-black text-[hsl(var(--foreground))]">${{ stock.price.toFixed(2) }}</span>
            <span class="flex items-center gap-0.5 text-sm font-bold" :class="stock.change >= 0 ? (colorMode === 'cn' ? 'text-destructive' : 'text-success') : colorMode === 'cn' ? 'text-success' : 'text-destructive'">
              <component :is="stock.change >= 0 ? TrendingUp : TrendingDown" class="h-4 w-4" />
              <span>{{ stock.change >= 0 ? '+' : '' }}{{ stock.change.toFixed(2) }} ({{ stock.changePercent >= 0 ? '+' : '' }}{{ stock.changePercent }}%)</span>
            </span>
          </div>

          <div class="hidden items-center gap-4 font-mono text-xs text-[hsl(var(--muted-foreground))] xl:flex">
            <div>今开: <span class="text-[hsl(var(--foreground))]">${{ openPrice.toFixed(2) }}</span></div>
            <div>前收: <span class="text-[hsl(var(--foreground))]">${{ prevClose.toFixed(2) }}</span></div>
            <div>最高: <span class="text-destructive">${{ highPrice.toFixed(2) }}</span></div>
            <div>最低: <span class="text-success">${{ lowPrice.toFixed(2) }}</span></div>
            <div>成交量: <span class="text-[hsl(var(--foreground))]">{{ stock.volume }}</span></div>
          </div>
        </div>

        <!-- Timeframe & Value Toggle Controls -->
        <div class="flex items-center gap-3">
          <div class="flex items-center rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--accent))] p-1 text-xs font-semibold">
            <button
              class="rounded-lg px-3 py-1 transition-all"
              :class="timeframe === '1D' ? 'bg-primary font-extrabold text-white shadow' : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'"
              @click="timeframe = '1D'"
            >
              日K (1D)
            </button>
            <button
              class="flex items-center gap-1 rounded-lg px-3 py-1 transition-all"
              :class="timeframe === '1W' ? 'bg-primary font-extrabold text-white shadow' : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'"
              @click="timeframe = '1W'"
            >
              <Layers class="h-3 w-3 text-primary" />
              <span>周K (1W)</span>
            </button>
            <button
              class="rounded-lg px-3 py-1 transition-all"
              :class="timeframe === '1M' ? 'bg-primary font-extrabold text-white shadow' : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'"
              @click="timeframe = '1M'"
            >
              月K (1M)
            </button>
          </div>

          <button
            class="rounded-xl border px-3 py-1.5 text-xs font-semibold transition-all"
            :class="showMA ? 'border-primary/40 bg-primary/20 text-primary' : 'border-[hsl(var(--border))] bg-[hsl(var(--accent))] text-[hsl(var(--muted-foreground))]'"
            @click="showMA = !showMA"
          >
            均线 (MA5/20)
          </button>
        </div>
        </div>
      </template>
      <div
        v-else
        class="flex min-h-16 shrink-0 items-center gap-2 border-b border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] px-6 text-xs text-[hsl(var(--muted-foreground))]"
      >
        <TrendingUp class="h-4 w-4 text-[hsl(var(--muted-foreground))]" />
        <span>未选择股票 — 请到「自选股」页选择一只股票，或点击自选股列表里的「查看K线」进入</span>
      </div>

      <!-- Main Workspace Split -->
      <div class="flex flex-1 flex-col overflow-hidden lg:flex-row">
        <!-- Main Chart Area -->
        <div class="flex flex-1 flex-col overflow-hidden bg-[hsl(var(--background-deep))] p-4">
          <div class="relative flex flex-1 flex-col overflow-hidden rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-4 shadow-inner">
            <div class="mb-2 flex items-center justify-between font-mono text-xs text-[hsl(var(--muted-foreground))]">
              <div class="flex items-center gap-4">
                <span class="rounded border border-primary/20 bg-primary/10 px-2 py-0.5 font-bold text-primary">
                  {{ candleModeLabel }}
                </span>
                <span v-if="showMA" class="font-semibold text-[#38bdf8]">MA5: ${{ lastCandle.ma5 || '---' }}</span>
                <span v-if="showMA" class="font-semibold text-[#a855f7]">MA20: ${{ lastCandle.ma20 || '---' }}</span>
              </div>
              <div class="flex items-center gap-2 text-[11px] text-[hsl(var(--muted-foreground))]">
                <span>滚轮缩放 / 拖动滑块 / 双击复位</span>
                <div class="flex gap-1">
                  <button class="rounded border px-2 py-0.5 font-semibold" :class="indicator === 'macd' ? 'bg-primary border-primary text-white' : 'border-[hsl(var(--border))] bg-[hsl(var(--accent))] text-[hsl(var(--muted-foreground))]'" @click="indicator = 'macd'">
                    MACD
                  </button>
                  <button class="rounded border px-2 py-0.5 font-semibold" :class="indicator === 'rsi' ? 'bg-primary border-primary text-white' : 'border-[hsl(var(--border))] bg-[hsl(var(--accent))] text-[hsl(var(--muted-foreground))]'" @click="indicator = 'rsi'">
                    RSI
                  </button>
                </div>
              </div>
            </div>

            <div v-if="candles.length === 0" class="flex flex-1 items-center justify-center text-xs text-[hsl(var(--muted-foreground))]">暂无K线数据</div>
            <div v-else class="relative flex-1">
              <EchartsUI ref="chartRef" height="100%" width="100%" />

              <!-- 悬浮视图控制条：范围快捷切换 + 放大/缩小/全部/复位 + 实时视窗 -->
              <div class="pointer-events-none absolute right-2 top-2 z-10 flex items-center gap-1 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))]/90 p-1 text-[10px] font-semibold shadow-lg backdrop-blur">
                <span class="pointer-events-auto hidden px-1.5 font-mono text-[hsl(var(--muted-foreground))] sm:inline">{{ visibleRangeLabel }}</span>
                <template v-if="timeframe === '1D'">
                  <button class="pointer-events-auto rounded px-1.5 py-0.5 text-[hsl(var(--muted-foreground))] transition-colors hover:bg-[hsl(var(--muted))] hover:text-[hsl(var(--foreground))]" title="显示最近半年（约126根日K）" @click="showRecent(126)">
                    6M
                  </button>
                  <button class="pointer-events-auto rounded px-1.5 py-0.5 text-[hsl(var(--muted-foreground))] transition-colors hover:bg-[hsl(var(--muted))] hover:text-[hsl(var(--foreground))]" title="显示最近一年" @click="showRecent(252)">
                    1Y
                  </button>
                </template>
                <button class="pointer-events-auto rounded p-1 text-[hsl(var(--muted-foreground))] transition-colors hover:bg-[hsl(var(--muted))] hover:text-[hsl(var(--foreground))]" title="放大视窗" @click="zoomIn">
                  <ZoomIn class="h-3.5 w-3.5" />
                </button>
                <button class="pointer-events-auto rounded p-1 text-[hsl(var(--muted-foreground))] transition-colors hover:bg-[hsl(var(--muted))] hover:text-[hsl(var(--foreground))]" title="缩小视窗" @click="zoomOut">
                  <ZoomOut class="h-3.5 w-3.5" />
                </button>
                <button class="pointer-events-auto rounded p-1 text-[hsl(var(--muted-foreground))] transition-colors hover:bg-[hsl(var(--muted))] hover:text-[hsl(var(--foreground))]" title="显示全部历史" @click="showAll">
                  <Maximize2 class="h-3.5 w-3.5" />
                </button>
                <button class="pointer-events-auto rounded p-1 text-[hsl(var(--muted-foreground))] transition-colors hover:bg-[hsl(var(--muted))] hover:text-[hsl(var(--foreground))]" title="复位到最近{{ DEFAULT_VISIBLE_CANDLES }}根" @click="resetView">
                  <RotateCcw class="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Right Sidebar: Market Summary Metrics & Pivot Level Analysis -->
        <div v-if="stock" class="custom-scrollbar w-full space-y-4 overflow-y-auto border-l border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-4 select-none lg:w-80">
          <div class="space-y-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
            <div class="flex items-center gap-2 border-b border-[hsl(var(--border))] pb-2 text-xs font-bold text-[hsl(var(--foreground))]">
              <Calendar class="h-4 w-4 text-primary" />
              <span>{{ timeframeShortLabel }}线行情概览（近{{ defaultWindowCandles.length }}根）</span>
            </div>

            <div class="grid grid-cols-2 gap-2 font-mono text-xs">
              <div class="rounded-lg bg-[hsl(var(--background-deep))] p-2">
                <div class="text-[10px] text-[hsl(var(--muted-foreground))]">本周期开盘</div>
                <div class="font-bold text-[hsl(var(--foreground))]">${{ openPrice.toFixed(2) }}</div>
              </div>
              <div class="rounded-lg bg-[hsl(var(--background-deep))] p-2">
                <div class="text-[10px] text-[hsl(var(--muted-foreground))]">前周期收盘</div>
                <div class="font-bold text-[hsl(var(--muted-foreground))]">${{ prevClose.toFixed(2) }}</div>
              </div>
              <div class="rounded-lg bg-[hsl(var(--background-deep))] p-2">
                <div class="text-[10px] text-[hsl(var(--muted-foreground))]">周期最高</div>
                <div class="font-bold text-destructive">${{ highPrice.toFixed(2) }}</div>
              </div>
              <div class="rounded-lg bg-[hsl(var(--background-deep))] p-2">
                <div class="text-[10px] text-[hsl(var(--muted-foreground))]">周期最低</div>
                <div class="font-bold text-success">${{ lowPrice.toFixed(2) }}</div>
              </div>
              <div class="rounded-lg bg-[hsl(var(--background-deep))] p-2">
                <div class="text-[10px] text-[hsl(var(--muted-foreground))]">周期震幅</div>
                <div class="font-bold text-warning">{{ amplitude }}%</div>
              </div>
              <div class="rounded-lg bg-[hsl(var(--background-deep))] p-2">
                <div class="text-[10px] text-[hsl(var(--muted-foreground))]">市盈率 PE</div>
                <div class="font-bold text-[hsl(var(--foreground))]">{{ stock.pe }}x</div>
              </div>
            </div>
          </div>

          <!-- Key Pivot Technical Levels -->
          <div class="space-y-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
            <div class="flex items-center gap-2 border-b border-[hsl(var(--border))] pb-2 text-xs font-bold text-[hsl(var(--foreground))]">
              <Activity class="h-4 w-4 text-success" />
              <span>{{ timeframeShortLabel }}线关键支撑阻力位</span>
            </div>

            <div class="space-y-2 font-mono text-xs">
              <div class="flex items-center justify-between rounded-lg bg-[hsl(var(--background-deep))] p-2">
                <span class="text-[11px] text-[hsl(var(--muted-foreground))]">压力位 R1:</span>
                <span class="font-bold text-destructive">${{ (stock.price * 1.05).toFixed(2) }}</span>
              </div>
              <div class="flex items-center justify-between rounded-lg bg-[hsl(var(--background-deep))] p-2">
                <span class="text-[11px] text-[hsl(var(--muted-foreground))]">关键MA20:</span>
                <span class="font-bold text-primary">${{ (stock.price * 0.98).toFixed(2) }}</span>
              </div>
              <div class="flex items-center justify-between rounded-lg bg-[hsl(var(--background-deep))] p-2">
                <span class="text-[11px] text-[hsl(var(--muted-foreground))]">支撑位 S1:</span>
                <span class="font-bold text-success">${{ (stock.price * 0.95).toFixed(2) }}</span>
              </div>
            </div>
          </div>

          <!-- Quant Assessment Card -->
          <div class="space-y-2 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
            <div class="flex items-center justify-between text-xs font-bold">
              <span class="text-[hsl(var(--muted-foreground))]">{{ timeframeShortLabel }}线多空评级</span>
              <span class="rounded border border-success/30 bg-success/20 px-2 py-0.5 font-mono text-[10px] text-success">
                {{ stock.macdSignal }}
              </span>
            </div>
            <p class="text-[11px] leading-relaxed text-[hsl(var(--muted-foreground))]">{{ trendCommentary }}</p>
          </div>
        </div>
      </div>
    </div>
  </Page>
</template>
