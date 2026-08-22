<script lang="ts" setup>
import { chartColor } from '../../_shared/chart-theme';
import type { EchartsUIType } from '@vben/plugins/echarts';
import type { FundamentalsApi } from '#/api/core/fundamentals';

import { computed, ref, watch } from 'vue';

import { EchartsUI, useEcharts } from '@vben/plugins/echarts';

import { getFundamentalsValuationApi } from '#/api/core/fundamentals';

import { formatMultiple, formatPercent, formatUsdPerShare, NO_DATA_TEXT } from '../_shared/format';

const props = defineProps<{ symbol: string; refreshTick: number }>();

const loading = ref(false);
const errorMsg = ref('');
const data = ref<FundamentalsApi.ValuationData | null>(null);

async function load() {
  loading.value = true;
  errorMsg.value = '';
  try {
    const envelope = await getFundamentalsValuationApi(props.symbol);
    data.value = envelope.data;
  } catch (e: any) {
    errorMsg.value = e.message || '加载失败';
  } finally {
    loading.value = false;
  }
}
watch(() => [props.symbol, props.refreshTick], load, { immediate: true });

const CURRENT_CARDS: { key: keyof FundamentalsApi.OverviewData; label: string }[] = [
  { key: 'pe_ttm', label: 'TTM PE' },
  { key: 'pe_forward', label: 'Forward PE' },
  { key: 'peg_ratio', label: 'PEG' },
  { key: 'ps_ttm', label: 'P/S' },
  { key: 'pb', label: 'P/B' },
  { key: 'ev_ebitda', label: 'EV/EBITDA' },
  { key: 'ev_revenue', label: 'EV/Sales' },
  { key: 'fcf_yield', label: 'FCF Yield' },
  { key: 'earnings_yield', label: 'Earnings Yield' },
];
function isYieldField(key: string) {
  return key === 'fcf_yield' || key === 'earnings_yield';
}

const windowYears = ref<1 | 3 | 5>(5);
type MultipleKey = 'pb' | 'pe' | 'ps';
const selectedMultiple = ref<MultipleKey>('pe');

function windowedSummary(summary: FundamentalsApi.MultipleSummary | undefined): FundamentalsApi.MultipleSummary {
  const empty: FundamentalsApi.MultipleSummary = { series: [], current: null, median: null, percentile: null, min: null, max: null };
  if (!summary || summary.series.length === 0) return empty;
  const cutoff = new Date();
  cutoff.setFullYear(cutoff.getFullYear() - windowYears.value);
  const cutoffStr = cutoff.toISOString().slice(0, 10);
  const series = summary.series.filter((p) => p.end >= cutoffStr);
  if (series.length === 0) return empty;
  const values = series.map((p) => p.val as number).sort((a, b) => a - b);
  const current = series.at(-1)!.val as number;
  const median = values[Math.floor(values.length / 2)]!;
  const below = values.filter((v) => v <= current).length;
  return {
    series, current, median: Math.round(median * 100) / 100,
    percentile: Math.round((below / values.length) * 1000) / 10,
    min: Math.round(Math.min(...values) * 100) / 100,
    max: Math.round(Math.max(...values) * 100) / 100,
  };
}

const activeSummary = computed(() => windowedSummary(data.value?.historical?.[selectedMultiple.value]));

const chartRef = ref<EchartsUIType>();
const { renderEcharts } = useEcharts(chartRef);
watch([activeSummary], () => {
  const series = activeSummary.value.series;
  renderEcharts({
    grid: { left: 50, right: 20, top: 30, bottom: 40 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: series.map((p) => p.end), axisLabel: { color: chartColor('--muted-foreground') } },
    yAxis: { type: 'value', axisLabel: { color: chartColor('--muted-foreground') } },
    series: [
      { name: selectedMultiple.value.toUpperCase(), type: 'line', smooth: true, data: series.map((p) => p.val) },
      { name: '历史中位数', type: 'line', data: series.map(() => activeSummary.value.median), lineStyle: { type: 'dashed', color: '#f59e0b' }, symbol: 'none' },
    ],
  });
});
</script>

<template>
  <div v-if="loading" class="py-12 text-center text-xs text-[hsl(var(--muted-foreground))]">正在加载估值数据…</div>
  <div v-else-if="errorMsg" class="py-12 text-center text-xs text-destructive">{{ errorMsg }}</div>
  <div v-else-if="!data" class="py-12 text-center text-xs text-[hsl(var(--muted-foreground))]">{{ NO_DATA_TEXT }}</div>
  <div v-else class="space-y-4">
    <!-- 当前估值 -->
    <div>
      <h3 class="mb-2 text-xs font-bold text-[hsl(var(--muted-foreground))]">当前估值</h3>
      <div class="grid grid-cols-3 gap-3 sm:grid-cols-5">
        <div v-for="c in CURRENT_CARDS" :key="c.key" class="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-3">
          <div class="text-[10px] text-[hsl(var(--muted-foreground))]">{{ c.label }}</div>
          <div class="font-mono text-base font-black text-[hsl(var(--foreground))]">
            {{ isYieldField(c.key) ? formatPercent(data.current[c.key] as number) : formatMultiple(data.current[c.key] as number) }}
          </div>
        </div>
      </div>
    </div>

    <!-- 历史估值 -->
    <div class="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-4">
      <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 class="text-xs font-bold text-[hsl(var(--muted-foreground))]">历史估值区间（用季度 TTM 财务数据 × 披露后股价推导，避免未来数据泄漏）</h3>
        <div class="flex items-center gap-2">
          <div class="flex items-center gap-1 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-1 text-[11px] font-semibold">
            <button v-for="k in (['pe', 'ps', 'pb'] as MultipleKey[])" :key="k" class="rounded px-2 py-1" :class="selectedMultiple === k ? 'bg-primary text-white' : 'text-[hsl(var(--muted-foreground))]'" @click="selectedMultiple = k">
              {{ k.toUpperCase() }}
            </button>
          </div>
          <div class="flex items-center gap-1 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-1 text-[11px] font-semibold">
            <button v-for="y in [1, 3, 5]" :key="y" class="rounded px-2 py-1" :class="windowYears === y ? 'bg-primary text-white' : 'text-[hsl(var(--muted-foreground))]'" @click="windowYears = y as 1 | 3 | 5">
              {{ y }}年
            </button>
          </div>
        </div>
      </div>

      <div v-if="activeSummary.series.length === 0" class="py-8 text-center text-xs text-[hsl(var(--muted-foreground))]">{{ NO_DATA_TEXT }}</div>
      <template v-else>
        <div class="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
          <div class="rounded-lg bg-[hsl(var(--background-deep))] p-2"><div class="text-[10px] text-[hsl(var(--muted-foreground))]">当前</div><div class="font-mono text-sm font-bold text-[hsl(var(--foreground))]">{{ formatMultiple(activeSummary.current) }}</div></div>
          <div class="rounded-lg bg-[hsl(var(--background-deep))] p-2"><div class="text-[10px] text-[hsl(var(--muted-foreground))]">历史中位数</div><div class="font-mono text-sm font-bold text-[hsl(var(--foreground))]">{{ formatMultiple(activeSummary.median) }}</div></div>
          <div class="rounded-lg bg-[hsl(var(--background-deep))] p-2"><div class="text-[10px] text-[hsl(var(--muted-foreground))]">历史分位</div><div class="font-mono text-sm font-bold text-warning">{{ activeSummary.percentile }}%</div></div>
          <div class="rounded-lg bg-[hsl(var(--background-deep))] p-2"><div class="text-[10px] text-[hsl(var(--muted-foreground))]">区间最低</div><div class="font-mono text-sm font-bold text-success">{{ formatMultiple(activeSummary.min) }}</div></div>
          <div class="rounded-lg bg-[hsl(var(--background-deep))] p-2"><div class="text-[10px] text-[hsl(var(--muted-foreground))]">区间最高</div><div class="font-mono text-sm font-bold text-destructive">{{ formatMultiple(activeSummary.max) }}</div></div>
        </div>
        <EchartsUI ref="chartRef" height="280px" />
      </template>
      <p class="mt-2 text-[10px] text-[hsl(var(--muted-foreground))]">同行业中位数对比：暂不可用（免费数据源没有可靠的同行分组接口，需要配置额外数据源）</p>
    </div>

    <!-- 估值区间：悲观/基准/乐观 -->
    <div class="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-4">
      <h3 class="mb-3 text-xs font-bold text-[hsl(var(--muted-foreground))]">估值区间（研究模型，不是目标价）</h3>
      <div v-if="!data.scenarios" class="py-8 text-center text-xs text-[hsl(var(--muted-foreground))]">{{ NO_DATA_TEXT }}（历史 PE 序列或未来 EPS 预期不足）</div>
      <template v-else>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div v-for="(s, key) in { 悲观: data.scenarios.bear, 基准: data.scenarios.base, 乐观: data.scenarios.bull }" :key="key" class="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3">
            <div class="text-xs font-bold text-[hsl(var(--foreground))]">{{ key }}情景</div>
            <div class="mt-1 font-mono text-xl font-black text-[hsl(var(--foreground))]">{{ formatUsdPerShare(s.implied_price) }}</div>
            <div class="font-mono text-[11px] font-bold" :class="s.vs_current_percent >= 0 ? 'text-destructive' : 'text-success'">
              {{ formatPercent(s.vs_current_percent) }} vs 当前价
            </div>
            <div class="mt-2 space-y-0.5 text-[10px] text-[hsl(var(--muted-foreground))]">
              <div>PE 倍数假设: {{ s.pe_multiple }}x</div>
              <div>EPS 假设（未来一年一致预期）: {{ s.eps_assumption }}</div>
              <div>{{ s.growth_assumption_note }}</div>
            </div>
          </div>
        </div>
        <p class="mt-3 text-[10px] text-warning">{{ data.scenarios.disclaimer }}</p>
      </template>
    </div>
  </div>
</template>
