<script lang="ts" setup>
import type { EchartsUIType } from '@vben/plugins/echarts';
import type { CandlestickData, StockItem } from '../../_shared/types';

import { onBeforeUnmount, ref, watch } from 'vue';

import { EchartsUI, useEcharts } from '@vben/plugins/echarts';
import { ArrowLeft, Loader2, TrendingDown, TrendingUp } from 'lucide-vue-next';

import { getStockKlineApi } from '#/api/core/stock';
import { chartColor } from '../../_shared/chart-theme';

import FundamentalsTabs from '../../_shared/FundamentalsTabs.vue';
import IndicatorCards from '../../_shared/IndicatorCards.vue';

/**
 * 自选股「查看K线」的全屏覆盖层：点击后覆盖当前页面（fixed inset-0），
 * 不再跳转独立页面、也不用侧边抽屉，K线图占满整个可视区。
 * 支持日/周/月K、均线开关、近半年/近一年快捷视窗、滑块拖动 + 滚轮缩放 + 双击复位；
 * 右上角可切换「技术指标」「基本面」视图（与对应页面共用数据组件）。
 * K线数据缓存进 stock.kline1D/1W/1M，与 quotes 页共享，不重复请求。
 */
const props = defineProps<{ open: boolean; stock: StockItem | null }>();
const emit = defineEmits<{ 'update:open': [v: boolean] }>();

// 视图切换：kline=K线图 / indicators=技术指标 / fundamentals=基本面
const view = ref<'kline' | 'indicators' | 'fundamentals'>('kline');
const VIEW_TABS = [
  { key: 'kline', label: 'K线' },
  { key: 'indicators', label: '技术指标' },
  { key: 'fundamentals', label: '基本面' },
] as const;

const timeframe = ref<'1D' | '1W' | '1M'>('1D');
const showMA = ref(true);

const chartRef = ref<EchartsUIType>();
const { renderEcharts, getChartInstance } = useEcharts(chartRef);

const candles = ref<CandlestickData[]>([]);
const loading = ref(false);
const error = ref('');
const loadedKeys = ref<Record<string, boolean>>({});

const DEFAULT_VISIBLE = 60;
// 固定红涨绿跌，和股票模块其他页面一致
const upColor = '#f43f5e';
const downColor = '#34d399';

const TIMEFRAME_LABEL: Record<string, string> = { '1D': '日K', '1W': '周K', '1M': '月K' };

function intervalOf(tf: string): '1d' | '1wk' | '1mo' {
  if (tf === '1W') return '1wk';
  if (tf === '1M') return '1mo';
  return '1d';
}
function cacheKeyOf(tf: string) {
  if (tf === '1W') return 'kline1W';
  if (tf === '1M') return 'kline1M';
  return 'kline1D';
}

/** 把当前周期对应的缓存数据同步到 candles（加载成功后必须调用，否则图表不更新） */
function syncCandles() {
  const s = props.stock;
  candles.value = s ? ((s[cacheKeyOf(timeframe.value)] as CandlestickData[] | undefined)?.slice() ?? []) : [];
}

async function loadKline(symbol: string, interval: '1d' | '1wk' | '1mo') {
  const key = `${symbol}:${interval}`;
  if (loadedKeys.value[key]) return;
  loading.value = true;
  error.value = '';
  try {
    const data = await getStockKlineApi(symbol, interval);
    if (props.stock) {
      props.stock[cacheKeyOf(interval)] = data;
    }
    loadedKeys.value[key] = true;
    // 拉到的正是当前周期 → 立即同步到图表（之前漏了这步导致"查不到数据"）
    if (intervalOf(timeframe.value) === interval) {
      syncCandles();
    }
  } catch (e: any) {
    error.value = e.message || '获取K线失败';
  } finally {
    loading.value = false;
  }
}

function ensureLoaded() {
  if (!props.stock) return;
  loadKline(props.stock.symbol, intervalOf(timeframe.value));
}

// 打开覆盖层 / 切换股票：重置到日K视图并加载
watch(
  () => [props.open, props.stock?.symbol] as const,
  () => {
    if (props.open && props.stock) {
      view.value = 'kline';
      timeframe.value = '1D';
      error.value = '';
      syncCandles();
      ensureLoaded();
    }
  },
  { immediate: true },
);

// 切换周期：同步缓存数据 + 按需加载
watch(timeframe, () => {
  syncCandles();
  ensureLoaded();
});

// ESC 关闭覆盖层
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && props.open) emit('update:open', false);
}
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown));
watch(
  () => props.open,
  (v) => {
    if (v) window.addEventListener('keydown', onKeydown);
    else window.removeEventListener('keydown', onKeydown);
  },
);

function buildOption() {
  const data = candles.value;
  const times = data.map((c) => c.time);
  const startPercent = data.length > DEFAULT_VISIBLE ? ((data.length - DEFAULT_VISIBLE) / data.length) * 100 : 0;

  return {
    animation: true,
    animationDuration: 200,
    animationDurationUpdate: 300,
    animationEasing: 'cubicOut',
    animationEasingUpdate: 'cubicOut',
    backgroundColor: 'transparent',
    grid: [
      { left: 64, right: 20, top: 10, height: '62%' },
      { left: 64, right: 20, top: '76%', height: '16%' },
    ],
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    xAxis: [
      { type: 'category', data: times, gridIndex: 0, axisLine: { lineStyle: { color: chartColor('--border') } }, axisLabel: { show: false }, axisTick: { show: false }, splitLine: { show: false } },
      { type: 'category', data: times, gridIndex: 1, axisLine: { lineStyle: { color: chartColor('--border') } }, axisLabel: { color: chartColor('--muted-foreground'), fontSize: 11 }, splitLine: { show: false } },
    ],
    yAxis: [
      { scale: true, gridIndex: 0, axisLine: { show: false }, axisLabel: { color: chartColor('--muted-foreground'), fontSize: 11 }, splitLine: { lineStyle: { color: chartColor('--border'), type: 'dashed' } } },
      { scale: true, gridIndex: 1, axisLine: { show: false }, axisLabel: { color: chartColor('--muted-foreground'), fontSize: 11 }, splitLine: { show: false } },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: startPercent, end: 100, zoomOnMouseWheel: true, moveOnMouseMove: true },
      { type: 'slider', xAxisIndex: [0, 1], start: startPercent, end: 100, height: 18, bottom: 6, realtime: true, showDetail: true, brushSelect: false, moveHandleSize: 18, handleSize: '100%', borderColor: 'transparent', backgroundColor: chartColor('--muted'), fillerColor: 'rgba(99,102,241,0.22)', handleStyle: { color: chartColor('--primary'), borderColor: chartColor('--primary') }, moveHandleStyle: { color: chartColor('--primary'), borderColor: chartColor('--primary') }, textStyle: { color: chartColor('--muted-foreground'), fontSize: 10 } },
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
          lines.push(`${p.marker}${p.seriesName}: ${Number(p.value).toFixed(2)}`);
        }
        return lines.join('<br/>');
      },
    },
    series: [
      {
        name: '价格',
        type: 'candlestick',
        data: data.map((c) => [c.open, c.close, c.low, c.high]),
        itemStyle: { color: upColor, color0: downColor, borderColor: upColor, borderColor0: downColor },
        xAxisIndex: 0,
        yAxisIndex: 0,
      },
      ...(showMA.value
        ? [
            { name: 'MA5', type: 'line', data: data.map((c) => c.ma5 ?? null), xAxisIndex: 0, yAxisIndex: 0, smooth: true, showSymbol: false, lineStyle: { width: 1.3, color: '#38bdf8' } },
            { name: 'MA20', type: 'line', data: data.map((c) => c.ma20 ?? null), xAxisIndex: 0, yAxisIndex: 0, smooth: true, showSymbol: false, lineStyle: { width: 1.3, color: '#a855f7' } },
          ]
        : []),
      {
        name: '成交量',
        type: 'bar',
        data: data.map((c) => ({
          value: c.volume,
          itemStyle: { color: c.close >= c.open ? upColor : downColor },
        })),
        xAxisIndex: 1,
        yAxisIndex: 1,
        barMaxWidth: 14,
      },
    ],
  };
}

watch(
  [candles, showMA],
  () => {
    if (candles.value.length === 0) return;
    renderEcharts(buildOption() as any);
  },
  { deep: false },
);

// 从其他视图切回K线时，图表 DOM 重新挂载（v-if），需要重新渲染一次
watch(view, (v) => {
  if (v === 'kline' && candles.value.length > 0) {
    renderEcharts(buildOption() as any);
  }
});

// 视图快捷切换（日K下：近半年 / 近一年；全部）
function showRecent(count: number) {
  const total = candles.value.length;
  if (!total) return;
  const n = Math.min(count, total);
  const chart = getChartInstance();
  if (!chart) return;
  chart.dispatchAction({
    type: 'dataZoom',
    start: ((total - n) / total) * 100,
    end: 100,
    animation: { duration: 250, easing: 'cubicOut' } as any,
  });
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open && stock"
      class="fixed inset-0 z-[1000] flex flex-col bg-[hsl(var(--background-deep))] select-none"
    >
      <!-- 顶栏：返回 + 股票信息 + 控制 -->
      <div class="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] px-4">
        <div class="flex min-w-0 items-center gap-3">
          <button
            class="flex items-center gap-1.5 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-1.5 text-xs font-bold text-[hsl(var(--muted-foreground))] hover:border-primary/50 hover:text-[hsl(var(--foreground))]"
            @click="emit('update:open', false)"
          >
            <ArrowLeft class="h-3.5 w-3.5" />
            返回
          </button>
          <div class="flex min-w-0 items-center gap-2">
            <span class="text-lg font-extrabold text-[hsl(var(--foreground))]">{{ stock.symbol }}</span>
            <span class="max-w-[200px] truncate text-xs text-[hsl(var(--muted-foreground))]">{{ stock.name }}</span>
            <span
              class="flex items-center gap-1 text-xs font-bold"
              :class="(stock.change ?? 0) >= 0 ? 'text-destructive' : 'text-success'"
            >
              <component :is="(stock.change ?? 0) >= 0 ? TrendingUp : TrendingDown" class="h-3.5 w-3.5" />
              {{ (stock.change ?? 0) >= 0 ? '+' : '' }}{{ stock.change?.toFixed(2) ?? '--' }}
              ({{ (stock.changePercent ?? 0) >= 0 ? '+' : '' }}{{ stock.changePercent ?? 0 }}%)
            </span>
          </div>
        </div>

        <div class="flex items-center gap-2">
          <!-- 视图切换：K线 / 技术指标 / 基本面 -->
          <div class="flex items-center rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-0.5 text-[11px] font-semibold">
            <button
              v-for="t in VIEW_TABS"
              :key="t.key"
              class="rounded-md px-2.5 py-1"
              :class="view === t.key ? 'bg-primary text-white' : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'"
              @click="view = t.key"
            >
              {{ t.label }}
            </button>
          </div>

          <!-- 周期切换（仅K线视图） -->
          <div v-if="view === 'kline'" class="flex items-center rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-0.5 text-[11px] font-semibold">
            <button
              v-for="tf in (['1D', '1W', '1M'] as const)"
              :key="tf"
              class="rounded-md px-3 py-1"
              :class="timeframe === tf ? 'bg-primary text-white' : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'"
              @click="timeframe = tf"
            >
              {{ TIMEFRAME_LABEL[tf] }}
            </button>
          </div>
          <!-- 均线开关 -->
          <button
            v-if="view === 'kline'"
            class="rounded-lg border px-2.5 py-1.5 text-[11px] font-bold transition-all"
            :class="showMA ? 'border-primary/40 bg-primary/20 text-primary' : 'border-[hsl(var(--border))] bg-[hsl(var(--card))] text-[hsl(var(--muted-foreground))]'"
            @click="showMA = !showMA"
          >
            均线
          </button>
          <!-- 快捷视窗（日K有一年数据，其他周期数据窗口本身足够） -->
          <template v-if="view === 'kline' && timeframe === '1D'">
            <button
              class="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-2 py-1.5 text-[11px] font-bold text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
              @click="showRecent(126)"
            >
              近半年
            </button>
            <button
              class="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-2 py-1.5 text-[11px] font-bold text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
              @click="showRecent(9999)"
            >
              近一年
            </button>
          </template>
        </div>
      </div>

      <!-- K线视图：图例 -->
      <div v-if="view === 'kline'" class="flex shrink-0 items-center gap-4 px-4 py-1.5 font-mono text-[10px] text-[hsl(var(--muted-foreground))]">
        <span class="flex items-center gap-1"><i class="h-2 w-2 rounded-sm bg-destructive"></i> 上涨</span>
        <span class="flex items-center gap-1"><i class="h-2 w-2 rounded-sm bg-success"></i> 下跌</span>
        <span v-if="showMA" class="text-[#38bdf8]">MA5</span>
        <span v-if="showMA" class="text-[#a855f7]">MA20</span>
        <span class="ml-auto">滚轮缩放 / 拖动滑块 / 双击复位 / ESC 关闭</span>
      </div>

      <!-- 内容区：占满剩余空间 -->
      <div class="min-h-0 flex-1 px-4 pb-3">
        <!-- K线图表 -->
        <div v-if="view === 'kline'" class="h-full rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-3">
          <div v-if="loading" class="flex h-full flex-col items-center justify-center gap-2 text-xs text-[hsl(var(--muted-foreground))]">
            <Loader2 class="h-5 w-5 animate-spin text-primary" />
            正在获取 {{ stock.symbol }} {{ TIMEFRAME_LABEL[timeframe] }}…
          </div>
          <div v-else-if="error" class="flex h-full items-center justify-center px-6 text-center text-xs text-destructive">
            {{ error }}
          </div>
          <div v-else-if="candles.length === 0" class="flex h-full items-center justify-center text-xs text-[hsl(var(--muted-foreground))]">
            暂无K线数据
          </div>
          <EchartsUI v-else ref="chartRef" height="100%" width="100%" />
        </div>

        <!-- 技术指标视图 -->
        <div v-else-if="view === 'indicators'" class="custom-scrollbar h-full overflow-y-auto rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-4">
          <IndicatorCards :symbol="stock.symbol" />
        </div>

        <!-- 基本面视图：与「股票分析 > 基本面」页共用完整面板（含财报/估值/收益等全部 tab） -->
        <div v-else class="custom-scrollbar h-full overflow-y-auto rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-4">
          <FundamentalsTabs :symbol="stock.symbol" />
        </div>
      </div>
    </div>
  </Teleport>
</template>
