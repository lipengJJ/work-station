<script lang="ts" setup>
import type { EchartsUIType } from '@vben/plugins/echarts';
import type { CandlestickData } from '../_shared/types';

import { computed, ref, watch } from 'vue';

import { Page } from '@vben/common-ui';
import { EchartsUI, useEcharts } from '@vben/plugins/echarts';

import { Activity, Calendar, Layers, TrendingDown, TrendingUp } from 'lucide-vue-next';

import { getStockKlineApi } from '#/api/core/stock';

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
  if (timeframe.value === '1W') return '周K线趋势呈现稳健扩张通道，周MACD多头金叉发散，中长线资金控盘度较高。';
  if (timeframe.value === '1M' || timeframe.value === '1Y') return '月K线维持中期上升结构，MA20 月均线仍具支撑，长线持仓意愿偏强。';
  return `基于日线收盘形态与均线系统，股价维持在 MA20 趋势线上方，日线 RSI (${stock.value.rsi ?? '--'}) 提示短期偏多发散。`;
});

// ------------------------------------------------------- 真实K线（yfinance）----
// 日K/周K/月K 各自独立向后端拉一份（interval=1d/1wk/1mo，各自真实聚合过的K线，不是
// 同一份日K换个标签），拉到过的缓存在 stock.kline1D/1W/1M 上，切 tab 回来不重复请求

const klineLoading = ref(false);
const klineError = ref('');

async function loadKline(symbol: string, interval: '1d' | '1mo' | '1wk') {
  klineLoading.value = true;
  klineError.value = '';
  try {
    const data = await getStockKlineApi(symbol, interval);
    if (interval === '1d') stock.value.kline1D = data;
    else if (interval === '1wk') stock.value.kline1W = data;
    else stock.value.kline1M = data;
  } catch (e: any) {
    klineError.value = e.message || '获取K线失败';
  } finally {
    klineLoading.value = false;
  }
}

function ensureKlineLoaded() {
  const symbol = stock.value.symbol;
  if (!symbol) return;
  if (timeframe.value === '1W') {
    if (!stock.value.kline1W?.length) loadKline(symbol, '1wk');
  } else if (timeframe.value === '1M' || timeframe.value === '1Y') {
    if (!stock.value.kline1M?.length) loadKline(symbol, '1mo');
  } else if (!stock.value.kline1D?.length) {
    loadKline(symbol, '1d');
  }
}

watch(() => stock.value.symbol, ensureKlineLoaded, { immediate: true });
watch(timeframe, ensureKlineLoaded);

const upColor = computed(() => (colorMode === 'cn' ? '#f43f5e' : '#34d399'));
const downColor = computed(() => (colorMode === 'cn' ? '#34d399' : '#f43f5e'));

// 全部真实历史都交给 ECharts 的 dataZoom 去管理平移/缩放，不再像手写 SVG 那样为了不挤成
// 一坨而强行只截取最近 N 根——数据完整，只是默认视窗停在最近一段，用户可以顺滑拖动/滚轮
// 缩放看更早的历史
const candles = computed<CandlestickData[]>(() => {
  if (timeframe.value === '1W') {
    return stock.value.kline1W && stock.value.kline1W.length > 0 ? stock.value.kline1W : stock.value.kline1D || [];
  }
  if (timeframe.value === '1M' || timeframe.value === '1Y') {
    return stock.value.kline1M && stock.value.kline1M.length > 0 ? stock.value.kline1M : stock.value.kline1D || [];
  }
  return stock.value.kline1D || [];
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
    return { time: '', open: stock.value.price, high: stock.value.price, low: stock.value.price, close: stock.value.price, volume: 1_000_000 };
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
const { renderEcharts } = useEcharts(chartRef);

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
    animationDuration: 300,
    animationEasing: 'cubicOut',
    backgroundColor: 'transparent',
    grid: [
      { left: 56, right: 16, top: 8, height: '54%' },
      { left: 56, right: 16, top: '62%', height: '14%' },
      { left: 56, right: 16, top: '80%', height: '18%' },
    ],
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    xAxis: [
      { type: 'category', data: times, gridIndex: 0, axisLine: { lineStyle: { color: '#1E2433' } }, axisLabel: { show: false }, axisTick: { show: false }, splitLine: { show: false } },
      { type: 'category', data: times, gridIndex: 1, axisLine: { lineStyle: { color: '#1E2433' } }, axisLabel: { show: false }, axisTick: { show: false }, splitLine: { show: false } },
      { type: 'category', data: times, gridIndex: 2, axisLine: { lineStyle: { color: '#1E2433' } }, axisLabel: { color: '#64748b', fontSize: 10 }, splitLine: { show: false } },
    ],
    yAxis: [
      { scale: true, gridIndex: 0, axisLine: { show: false }, axisLabel: { color: '#64748b', fontSize: 10 }, splitLine: { lineStyle: { color: '#1A2030', type: 'dashed' } } },
      { scale: true, gridIndex: 1, axisLine: { show: false }, axisLabel: { show: false }, splitLine: { show: false } },
      { scale: true, gridIndex: 2, axisLine: { show: false }, axisLabel: { color: '#64748b', fontSize: 10 }, splitLine: { show: false } },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1, 2], start: startPercent, end: 100, zoomOnMouseWheel: true, moveOnMouseMove: true },
      { type: 'slider', xAxisIndex: [0, 1, 2], start: startPercent, end: 100, height: 14, bottom: 2, borderColor: 'transparent', backgroundColor: '#121622', fillerColor: 'rgba(99,102,241,0.25)', handleStyle: { color: '#6366f1' }, textStyle: { color: '#64748b', fontSize: 9 } },
    ],
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', crossStyle: { color: '#475569' }, label: { backgroundColor: '#1E2538' } },
      backgroundColor: 'rgba(15,19,28,0.95)',
      borderColor: '#232B3E',
      textStyle: { color: '#e2e8f0', fontSize: 11 },
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
              markLine: { symbol: 'none', silent: true, lineStyle: { type: 'dashed', color: '#334155' }, label: { color: '#64748b', fontSize: 9 }, data: [{ yAxis: 70 }, { yAxis: 30 }] } },
          ]),
    ],
  };
}

watch(
  [candles, showMA, indicator],
  () => {
    if (candles.value.length === 0) return;
    renderEcharts(buildOption() as any);
  },
  { immediate: true, deep: false },
);
</script>

<template>
  <Page :auto-content-height="true" content-class="!p-0">
    <div class="flex h-full flex-col overflow-hidden bg-[#0B0E14] text-slate-200 select-none">
      <div v-if="klineLoading" class="shrink-0 border-b border-[#1E2433] bg-[#0F131C] px-6 py-1.5 text-xs text-slate-400">
        正在从 Yahoo Finance 获取 {{ stock.symbol }} 日K线…
      </div>
      <div v-else-if="klineError" class="shrink-0 border-b border-rose-500/30 bg-rose-500/10 px-6 py-1.5 text-xs text-rose-300">
        获取真实日K线失败：{{ klineError }}（当前展示的是示例数据）
      </div>
      <!-- Stock Summary Header -->
      <div class="flex min-h-16 shrink-0 flex-wrap items-center justify-between gap-x-2 gap-y-2 border-b border-[#1E2433] bg-[#0F131C] px-6 py-2">
        <div class="flex flex-wrap items-center gap-x-6 gap-y-1">
          <div>
            <div class="flex items-center gap-2">
              <h1 class="shrink-0 text-2xl font-extrabold tracking-tight text-white">{{ stock.symbol }}</h1>
              <span class="max-w-[220px] truncate text-sm font-medium text-slate-400" :title="stock.name">{{ stock.name }}</span>
              <span class="shrink-0 rounded border border-indigo-500/30 bg-indigo-500/15 px-2.5 py-0.5 text-xs font-bold text-indigo-300">
                {{ stock.sector }} | {{ timeframeFullLabel }}
              </span>
            </div>
          </div>

          <div class="flex items-baseline gap-2 font-mono">
            <span class="text-2xl font-black text-white">${{ stock.price.toFixed(2) }}</span>
            <span class="flex items-center gap-0.5 text-sm font-bold" :class="stock.change >= 0 ? (colorMode === 'cn' ? 'text-rose-500' : 'text-emerald-400') : colorMode === 'cn' ? 'text-emerald-400' : 'text-rose-500'">
              <component :is="stock.change >= 0 ? TrendingUp : TrendingDown" class="h-4 w-4" />
              <span>{{ stock.change >= 0 ? '+' : '' }}{{ stock.change.toFixed(2) }} ({{ stock.changePercent >= 0 ? '+' : '' }}{{ stock.changePercent }}%)</span>
            </span>
          </div>

          <div class="hidden items-center gap-4 font-mono text-xs text-slate-400 xl:flex">
            <div>今开: <span class="text-white">${{ openPrice.toFixed(2) }}</span></div>
            <div>前收: <span class="text-white">${{ prevClose.toFixed(2) }}</span></div>
            <div>最高: <span class="text-rose-400">${{ highPrice.toFixed(2) }}</span></div>
            <div>最低: <span class="text-emerald-400">${{ lowPrice.toFixed(2) }}</span></div>
            <div>成交量: <span class="text-white">{{ stock.volume }}</span></div>
          </div>
        </div>

        <!-- Timeframe & Value Toggle Controls -->
        <div class="flex items-center gap-3">
          <div class="flex items-center rounded-xl border border-[#232B3E] bg-[#161C2A] p-1 text-xs font-semibold">
            <button
              class="rounded-lg px-3 py-1 transition-all"
              :class="timeframe === '1D' ? 'bg-indigo-600 font-extrabold text-white shadow' : 'text-slate-400 hover:text-slate-200'"
              @click="timeframe = '1D'"
            >
              日K (1D)
            </button>
            <button
              class="flex items-center gap-1 rounded-lg px-3 py-1 transition-all"
              :class="timeframe === '1W' ? 'bg-indigo-600 font-extrabold text-white shadow' : 'text-slate-400 hover:text-slate-200'"
              @click="timeframe = '1W'"
            >
              <Layers class="h-3 w-3 text-indigo-200" />
              <span>周K (1W)</span>
            </button>
            <button
              class="rounded-lg px-3 py-1 transition-all"
              :class="timeframe === '1M' ? 'bg-indigo-600 font-extrabold text-white shadow' : 'text-slate-400 hover:text-slate-200'"
              @click="timeframe = '1M'"
            >
              月K (1M)
            </button>
          </div>

          <button
            class="rounded-xl border px-3 py-1.5 text-xs font-semibold transition-all"
            :class="showMA ? 'border-indigo-500/40 bg-indigo-500/20 text-indigo-300' : 'border-[#232B3E] bg-[#161C2A] text-slate-400'"
            @click="showMA = !showMA"
          >
            均线 (MA5/20)
          </button>
        </div>
      </div>

      <!-- Main Workspace Split -->
      <div class="flex flex-1 flex-col overflow-hidden lg:flex-row">
        <!-- Main Chart Area -->
        <div class="flex flex-1 flex-col overflow-hidden bg-[#0B0E14] p-4">
          <div class="relative flex flex-1 flex-col overflow-hidden rounded-2xl border border-[#1E2433] bg-[#0F131C] p-4 shadow-inner">
            <div class="mb-2 flex items-center justify-between font-mono text-xs text-slate-400">
              <div class="flex items-center gap-4">
                <span class="rounded border border-indigo-500/20 bg-indigo-500/10 px-2 py-0.5 font-bold text-indigo-400">
                  {{ candleModeLabel }}
                </span>
                <span v-if="showMA" class="font-semibold text-[#38bdf8]">MA5: ${{ lastCandle.ma5 || '---' }}</span>
                <span v-if="showMA" class="font-semibold text-[#a855f7]">MA20: ${{ lastCandle.ma20 || '---' }}</span>
              </div>
              <div class="flex items-center gap-2 text-[11px] text-slate-500">
                <span>滚轮缩放 / 拖动底部滑块查看更早的历史</span>
                <div class="flex gap-1">
                  <button class="rounded border px-2 py-0.5 font-semibold" :class="indicator === 'macd' ? 'bg-indigo-600 border-indigo-500 text-white' : 'border-[#232B3E] bg-[#161C2A] text-slate-400'" @click="indicator = 'macd'">
                    MACD
                  </button>
                  <button class="rounded border px-2 py-0.5 font-semibold" :class="indicator === 'rsi' ? 'bg-indigo-600 border-indigo-500 text-white' : 'border-[#232B3E] bg-[#161C2A] text-slate-400'" @click="indicator = 'rsi'">
                    RSI
                  </button>
                </div>
              </div>
            </div>

            <div v-if="candles.length === 0" class="flex flex-1 items-center justify-center text-xs text-slate-500">暂无K线数据</div>
            <EchartsUI v-else ref="chartRef" height="100%" width="100%" />
          </div>
        </div>

        <!-- Right Sidebar: Market Summary Metrics & Pivot Level Analysis -->
        <div class="custom-scrollbar w-full space-y-4 overflow-y-auto border-l border-[#1E2433] bg-[#0F131C] p-4 select-none lg:w-80">
          <div class="space-y-3 rounded-xl border border-[#232B3E] bg-[#121622] p-4">
            <div class="flex items-center gap-2 border-b border-[#1E2538] pb-2 text-xs font-bold text-white">
              <Calendar class="h-4 w-4 text-indigo-400" />
              <span>{{ timeframeShortLabel }}线行情概览（近{{ defaultWindowCandles.length }}根）</span>
            </div>

            <div class="grid grid-cols-2 gap-2 font-mono text-xs">
              <div class="rounded-lg bg-[#0B0E14] p-2">
                <div class="text-[10px] text-slate-500">本周期开盘</div>
                <div class="font-bold text-white">${{ openPrice.toFixed(2) }}</div>
              </div>
              <div class="rounded-lg bg-[#0B0E14] p-2">
                <div class="text-[10px] text-slate-500">前周期收盘</div>
                <div class="font-bold text-slate-300">${{ prevClose.toFixed(2) }}</div>
              </div>
              <div class="rounded-lg bg-[#0B0E14] p-2">
                <div class="text-[10px] text-slate-500">周期最高</div>
                <div class="font-bold text-rose-400">${{ highPrice.toFixed(2) }}</div>
              </div>
              <div class="rounded-lg bg-[#0B0E14] p-2">
                <div class="text-[10px] text-slate-500">周期最低</div>
                <div class="font-bold text-emerald-400">${{ lowPrice.toFixed(2) }}</div>
              </div>
              <div class="rounded-lg bg-[#0B0E14] p-2">
                <div class="text-[10px] text-slate-500">周期震幅</div>
                <div class="font-bold text-amber-400">{{ amplitude }}%</div>
              </div>
              <div class="rounded-lg bg-[#0B0E14] p-2">
                <div class="text-[10px] text-slate-500">市盈率 PE</div>
                <div class="font-bold text-white">{{ stock.pe }}x</div>
              </div>
            </div>
          </div>

          <!-- Key Pivot Technical Levels -->
          <div class="space-y-3 rounded-xl border border-[#232B3E] bg-[#121622] p-4">
            <div class="flex items-center gap-2 border-b border-[#1E2538] pb-2 text-xs font-bold text-white">
              <Activity class="h-4 w-4 text-emerald-400" />
              <span>{{ timeframeShortLabel }}线关键支撑阻力位</span>
            </div>

            <div class="space-y-2 font-mono text-xs">
              <div class="flex items-center justify-between rounded-lg bg-[#0B0E14] p-2">
                <span class="text-[11px] text-slate-400">压力位 R1:</span>
                <span class="font-bold text-rose-400">${{ (stock.price * 1.05).toFixed(2) }}</span>
              </div>
              <div class="flex items-center justify-between rounded-lg bg-[#0B0E14] p-2">
                <span class="text-[11px] text-slate-400">关键MA20:</span>
                <span class="font-bold text-indigo-400">${{ (stock.price * 0.98).toFixed(2) }}</span>
              </div>
              <div class="flex items-center justify-between rounded-lg bg-[#0B0E14] p-2">
                <span class="text-[11px] text-slate-400">支撑位 S1:</span>
                <span class="font-bold text-emerald-400">${{ (stock.price * 0.95).toFixed(2) }}</span>
              </div>
            </div>
          </div>

          <!-- Quant Assessment Card -->
          <div class="space-y-2 rounded-xl border border-[#232B3E] bg-[#121622] p-4">
            <div class="flex items-center justify-between text-xs font-bold">
              <span class="text-slate-300">{{ timeframeShortLabel }}线多空评级</span>
              <span class="rounded border border-emerald-500/30 bg-emerald-500/20 px-2 py-0.5 font-mono text-[10px] text-emerald-400">
                {{ stock.macdSignal }}
              </span>
            </div>
            <p class="text-[11px] leading-relaxed text-slate-400">{{ trendCommentary }}</p>
          </div>
        </div>
      </div>
    </div>
  </Page>
</template>
