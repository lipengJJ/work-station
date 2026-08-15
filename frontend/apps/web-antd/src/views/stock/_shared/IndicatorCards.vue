<script lang="ts" setup>
import type { CandlestickData } from './types';

import { computed, ref, watch } from 'vue';

import { Loader2 } from 'lucide-vue-next';

import { getStockKlineApi } from '#/api/core/stock';

/**
 * 技术指标卡（真实数据驱动）：接收股票代码，从日K接口拉数据实时计算
 * RSI(14) / MACD / MA5-MA20 均线系统 / 近20根波动率 四张指标卡。
 * 技术指标页和 K线查看全屏层共用。
 */
const props = defineProps<{ symbol: string }>();

const loading = ref(false);
const error = ref('');
const klines = ref<CandlestickData[]>([]);
const last = computed(() => klines.value.at(-1) ?? null);
const recent20 = computed(() => klines.value.slice(-20));

async function loadIndicators() {
  if (!props.symbol) return;
  loading.value = true;
  error.value = '';
  try {
    klines.value = await getStockKlineApi(props.symbol, '1d');
  } catch (e: any) {
    error.value = e.message || '获取K线数据失败';
    klines.value = [];
  } finally {
    loading.value = false;
  }
}

watch(() => props.symbol, loadIndicators, { immediate: true });

function fmt(v: number | null | undefined, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return '--';
  return v.toFixed(digits);
}

const rsiInfo = computed(() => {
  const v = last.value?.rsi;
  if (v === null || v === undefined || Number.isNaN(v)) {
    return { value: '--', status: '暂无数据', desc: '当前K线数据不足，无法计算 RSI(14)' };
  }
  let status = '中性区间';
  let desc = `RSI(14) = ${v.toFixed(2)}，位于 30-70 中性区间，方向性不强`;
  if (v >= 70) {
    status = '超买';
    desc = `RSI(14) = ${v.toFixed(2)}，进入 70+ 超买区，短线追高风险加大`;
  } else if (v >= 60) {
    status = '多头偏强';
    desc = `RSI(14) = ${v.toFixed(2)}，位于 60-70 强势区间，多头占优但未超买`;
  } else if (v <= 30) {
    status = '超卖';
    desc = `RSI(14) = ${v.toFixed(2)}，进入 30- 超卖区，或有技术性反弹需求`;
  } else if (v <= 40) {
    status = '空头偏弱';
    desc = `RSI(14) = ${v.toFixed(2)}，位于 30-40 弱势区间，空头占优`;
  }
  return { value: v.toFixed(2), status, desc };
});

const macdInfo = computed(() => {
  const dif = last.value?.macdDif;
  const dea = last.value?.macdDea;
  const hist = last.value?.macdHist;
  if (dif === null || dif === undefined || dea === null || dea === undefined) {
    return { value: '--', status: '暂无数据', desc: '当前K线数据不足，无法计算 MACD' };
  }
  const bullish = dif > dea;
  const prev = klines.value.at(-2);
  const prevBullish = prev ? (prev.macdDif ?? 0) > (prev.macdDea ?? 0) : bullish;
  let status = bullish ? '金叉多头' : '死叉空头';
  let desc = `DIF ${fmt(dif)} ${bullish ? '>' : '<'} DEA ${fmt(dea)}，${bullish ? '多头' : '空头'}排列`;
  if (bullish && !prevBullish) desc = `DIF 上穿 DEA 形成金叉，柱状图转正扩张（Hist ${fmt(hist)}）`;
  else if (!bullish && prevBullish) desc = `DIF 下穿 DEA 形成死叉，柱状图转负收敛（Hist ${fmt(hist)}）`;
  return { value: bullish ? 'Bullish Cross' : 'Bearish Cross', status, desc };
});

const maInfo = computed(() => {
  const ma5 = last.value?.ma5;
  const ma20 = last.value?.ma20;
  const close = last.value?.close;
  if (ma5 === null || ma5 === undefined || ma20 === null || ma20 === undefined || close === null || close === undefined) {
    return { value: '--', status: '暂无数据', desc: '当前K线数据不足，无法计算均线系统' };
  }
  const bullish = ma5 > ma20;
  return {
    value: bullish ? '多头排列' : '空头排列',
    status: close > ma20 ? '支撑有效' : '跌破均线',
    desc: `MA5 ${fmt(ma5)} ${bullish ? '>' : '<'} MA20 ${fmt(ma20)}，收盘价 ${close >= ma20 ? '站上' : '跌破'} MA20`,
  };
});

const volatilityInfo = computed(() => {
  if (recent20.value.length < 5) {
    return { value: '--', status: '暂无数据', desc: 'K线数据不足' };
  }
  const highs = recent20.value.map((c) => c.high);
  const lows = recent20.value.map((c) => c.low);
  const closes = recent20.value.map((c) => c.close);
  const high = Math.max(...highs);
  const low = Math.min(...lows);
  const mid = closes.reduce((a, b) => a + b, 0) / closes.length || 1;
  const range = ((high - low) / mid) * 100;
  const lastClose = closes[closes.length - 1]!;
  const prevClose = closes[closes.length - 2];
  const daily = prevClose ? Math.abs(((lastClose - prevClose) / prevClose) * 100) : 0;
  const status = range >= 15 ? '波动放大' : range >= 8 ? '波动中等' : '波动收敛';
  return {
    value: `${range.toFixed(2)}%`,
    status,
    desc: `近20根K线振幅 ${range.toFixed(2)}%，最新单日波动 ${daily.toFixed(2)}%（高-低振幅/均价衡量）`,
  };
});

const indicators = computed(() => [
  { name: 'RSI(14) 相对强弱指标', ...rsiInfo.value },
  { name: 'MACD (12, 26, 9)', ...macdInfo.value },
  { name: 'MA5 / MA20 均线系统', ...maInfo.value },
  { name: '近20根波动率', ...volatilityInfo.value },
]);
</script>

<template>
  <div>
    <div v-if="loading" class="flex flex-col items-center justify-center gap-2 py-14 text-xs text-[hsl(var(--muted-foreground))]">
      <Loader2 class="h-5 w-5 animate-spin text-indigo-400" />
      正在拉取 {{ symbol }} 日K数据并计算指标…
    </div>
    <div v-else-if="error" class="rounded-xl border border-rose-500/30 bg-rose-500/10 p-8 text-center text-xs text-rose-300">
      {{ error }}
    </div>
    <div v-else class="grid grid-cols-1 gap-3 md:grid-cols-2">
      <div v-for="ind in indicators" :key="ind.name" class="space-y-2 rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-4">
        <div class="flex items-center justify-between border-b border-[hsl(var(--border))] pb-2">
          <span class="text-xs font-bold text-[hsl(var(--foreground))]">{{ ind.name }}</span>
          <span
            class="rounded border px-2 py-0.5 font-mono text-xs font-bold"
            :class="
              ind.status.includes('超买') || ind.status.includes('空头') || ind.status.includes('跌破')
                ? 'border-rose-500/30 bg-rose-500/10 text-rose-400'
                : ind.status.includes('超卖') || ind.status.includes('多头') || ind.status.includes('支撑')
                  ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
                  : 'border-amber-500/30 bg-amber-500/10 text-amber-400'
            "
          >
            {{ ind.status }}
          </span>
        </div>
        <div class="font-mono text-xl font-extrabold text-[hsl(var(--foreground))]">{{ ind.value }}</div>
        <p class="text-xs leading-relaxed text-[hsl(var(--muted-foreground))]">{{ ind.desc }}</p>
      </div>
    </div>
  </div>
</template>
