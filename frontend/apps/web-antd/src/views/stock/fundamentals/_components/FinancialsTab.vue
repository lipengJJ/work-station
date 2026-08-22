<script lang="ts" setup>
import { chartColor } from '../../_shared/chart-theme';
import type { EchartsUIType } from '@vben/plugins/echarts';
import type { FundamentalsApi } from '#/api/core/fundamentals';

import { computed, ref, watch } from 'vue';

import { EchartsUI, useEcharts } from '@vben/plugins/echarts';

import { Table, Tag } from 'ant-design-vue';

import { getFundamentalsFinancialsApi } from '#/api/core/fundamentals';

import { formatCompactUsd, formatPercent, formatUsdPerShare, NO_DATA_TEXT } from '../_shared/format';

const props = defineProps<{ symbol: string; refreshTick: number }>();

const loading = ref(false);
const errorMsg = ref('');
const data = ref<FundamentalsApi.FinancialsData | null>(null);

const period = ref<'annual' | 'quarterly'>('quarterly');
const mode = ref<'growth' | 'value'>('value');
const viewMode = ref<'chart' | 'table'>('chart');

type MetricSource = 'flow' | 'flow_multi' | 'instant_combo' | 'instant_single' | 'margin';
interface MetricDef {
  key: string;
  label: string;
  source: MetricSource;
  seriesKeys?: string[];
  unit: 'currency' | 'percent' | 'per_share' | 'shares';
}

const METRICS: MetricDef[] = [
  { key: 'revenue', label: '营业收入', source: 'flow', seriesKeys: ['revenue'], unit: 'currency' },
  { key: 'net_income', label: '净利润', source: 'flow', seriesKeys: ['net_income'], unit: 'currency' },
  { key: 'eps_diluted', label: 'EPS(稀释)', source: 'flow', seriesKeys: ['eps_diluted'], unit: 'per_share' },
  { key: 'margins', label: '毛利率/营业利润率/净利率', source: 'margin', unit: 'percent' },
  { key: 'operating_cash_flow', label: '经营现金流', source: 'flow', seriesKeys: ['operating_cash_flow'], unit: 'currency' },
  { key: 'free_cash_flow', label: '自由现金流', source: 'margin', seriesKeys: ['free_cash_flow'], unit: 'currency' },
  { key: 'capex', label: '资本开支', source: 'flow', seriesKeys: ['capex'], unit: 'currency' },
  { key: 'cash_debt', label: '现金和总债务', source: 'instant_combo', unit: 'currency' },
  { key: 'shares_outstanding', label: '流通股数', source: 'instant_single', seriesKeys: ['shares_outstanding'], unit: 'shares' },
  { key: 'rnd_sga', label: '研发费用和销售管理费用', source: 'flow_multi', seriesKeys: ['rnd_expense', 'sga_expense'], unit: 'currency' },
];
const selectedMetricKey = ref('revenue');
const selectedMetric = computed(() => METRICS.find((m) => m.key === selectedMetricKey.value)!);

// margin/free_cash_flow 图例 label 用不到 seriesKeys[0] 命名，这里单独维护中文名
const LINE_LABELS: Record<string, string> = {
  gross_margin: '毛利率', operating_margin: '营业利润率', net_margin: '净利率',
  rnd_expense: '研发费用', sga_expense: '销售管理费用',
  free_cash_flow: '自由现金流',
};

async function load() {
  loading.value = true;
  errorMsg.value = '';
  try {
    const envelope = await getFundamentalsFinancialsApi(props.symbol);
    data.value = envelope.data;
  } catch (e: any) {
    errorMsg.value = e.message || '加载失败';
  } finally {
    loading.value = false;
  }
}

watch(() => [props.symbol, props.refreshTick], load, { immediate: true });

function growthOf(points: FundamentalsApi.SeriesPoint[]): FundamentalsApi.SeriesPoint[] {
  const n = period.value === 'annual' ? 1 : 4;
  const out: FundamentalsApi.SeriesPoint[] = [];
  for (let i = n; i < points.length; i++) {
    const base = points[i - n]!.val;
    const cur = points[i]!.val;
    if (base && cur !== null && base !== 0) {
      out.push({ end: points[i]!.end, val: Math.round(((cur - base!) / Math.abs(base)) * 10_000) / 100 });
    }
  }
  return out;
}

function seriesFor(seriesKey: string): FundamentalsApi.SeriesPoint[] {
  if (!data.value) return [];
  const flow = data.value.series[period.value]?.[seriesKey];
  if (flow) return flow;
  const instant = data.value.series.instant?.[seriesKey];
  if (instant) return instant;
  const margin = data.value.growth_and_margins[period.value]?.[seriesKey];
  return margin || [];
}

const chartLines = computed<{ label: string; unit: MetricDef['unit']; points: FundamentalsApi.SeriesPoint[] }[]>(() => {
  const m = selectedMetric.value;
  if (!data.value) return [];

  if (m.source === 'margin' && m.key === 'margins') {
    return ['gross_margin', 'operating_margin', 'net_margin'].map((k) => ({
      label: LINE_LABELS[k]!, unit: 'percent' as const, points: seriesFor(k),
    }));
  }
  if (m.source === 'instant_combo') {
    const cash = data.value.series.instant.cash_and_equivalents || [];
    const lt = data.value.series.instant.long_term_debt || [];
    const st = data.value.series.instant.short_term_debt || [];
    const debtByEnd = new Map<string, number>();
    for (const p of [...lt, ...st]) debtByEnd.set(p.end, (debtByEnd.get(p.end) || 0) + (p.val || 0));
    const debt = [...debtByEnd.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([end, val]) => ({ end, val }));
    return [
      { label: '现金及等价物', unit: 'currency' as const, points: cash },
      { label: '有息负债合计', unit: 'currency' as const, points: debt },
    ];
  }

  const keys = m.seriesKeys || [m.key];
  return keys.map((k) => {
    const raw = seriesFor(k);
    const points = mode.value === 'growth' && m.source !== 'margin' ? growthOf(raw) : raw;
    return { label: LINE_LABELS[k] || m.label, unit: mode.value === 'growth' && m.source !== 'margin' ? ('percent' as const) : m.unit, points };
  });
});

function formatByUnit(unit: MetricDef['unit'], value: number | null): string {
  if (value === null || value === undefined) return NO_DATA_TEXT;
  if (unit === 'percent') return formatPercent(value);
  if (unit === 'per_share') return formatUsdPerShare(value);
  if (unit === 'shares') return value.toLocaleString();
  return formatCompactUsd(value);
}

// ------------------------------------------------------------------- 图表 ----
const chartRef = ref<EchartsUIType>();
const { renderEcharts } = useEcharts(chartRef);

watch(
  [chartLines, viewMode],
  () => {
    if (viewMode.value !== 'chart') return;
    const allEnds = [...new Set(chartLines.value.flatMap((l) => l.points.map((p) => p.end)))].sort();
    const isBar = mode.value === 'value' && selectedMetric.value.source !== 'margin' && chartLines.value.length === 1;
    renderEcharts({
      grid: { left: 60, right: 20, top: 40, bottom: 40 },
      legend: { top: 0, textStyle: { color: chartColor('--muted-foreground') } },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: allEnds, axisLabel: { color: chartColor('--muted-foreground') } },
      yAxis: { type: 'value', axisLabel: { color: chartColor('--muted-foreground') } },
      series: chartLines.value.map((line) => ({
        name: line.label,
        type: isBar ? 'bar' : 'line',
        smooth: true,
        data: allEnds.map((end) => line.points.find((p) => p.end === end)?.val ?? null),
      })),
    });
  },
  { deep: true },
);

const tableColumns = computed(() => [
  { title: '期间', dataIndex: 'end', key: 'end', fixed: 'left' as const, width: 110 },
  ...chartLines.value.map((line, idx) => ({ title: line.label, dataIndex: `v${idx}`, key: `v${idx}` })),
]);
const tableData = computed(() => {
  const allEnds = [...new Set(chartLines.value.flatMap((l) => l.points.map((p) => p.end)))].sort().reverse();
  return allEnds.map((end) => {
    const row: Record<string, any> = { end };
    chartLines.value.forEach((line, idx) => {
      const point = line.points.find((p) => p.end === end);
      row[`v${idx}`] = formatByUnit(line.unit, point?.val ?? null);
    });
    return row;
  });
});
</script>

<template>
  <div v-if="loading" class="py-12 text-center text-xs text-[hsl(var(--muted-foreground))]">正在加载财务数据…</div>
  <div v-else-if="errorMsg" class="py-12 text-center text-xs text-destructive">{{ errorMsg }}</div>
  <div v-else-if="!data" class="py-12 text-center text-xs text-[hsl(var(--muted-foreground))]">{{ NO_DATA_TEXT }}</div>
  <div v-else class="space-y-4">
    <!-- 预警信号 -->
    <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
      <div v-for="flag in data.red_flags" :key="flag.key" class="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-2.5">
        <div class="text-[10px] text-[hsl(var(--muted-foreground))]">{{ flag.title }}</div>
        <div class="flex items-center gap-1.5">
          <Tag :color="['是', '加速', '改善', '否', '减速', '恶化', '背离'].includes(flag.result) ? (['是', '加速', '恶化', '背离'].includes(flag.result) ? 'error' : 'success') : 'default'">
            {{ flag.result }}
          </Tag>
        </div>
        <div class="mt-0.5 text-[10px] text-[hsl(var(--muted-foreground))]">{{ flag.detail }}</div>
      </div>
    </div>

    <!-- 控制条 -->
    <div class="flex flex-wrap items-center gap-2">
      <div class="flex flex-wrap items-center gap-1 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-1">
        <button
          v-for="m in METRICS" :key="m.key"
          class="rounded px-2 py-1 text-[11px] font-semibold" :class="selectedMetricKey === m.key ? 'bg-primary text-white' : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'"
          @click="selectedMetricKey = m.key"
        >
          {{ m.label }}
        </button>
      </div>
      <span class="flex-1"></span>
      <div class="flex items-center gap-1 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-1 text-[11px] font-semibold">
        <button class="rounded px-2 py-1" :class="period === 'quarterly' ? 'bg-primary text-white' : 'text-[hsl(var(--muted-foreground))]'" @click="period = 'quarterly'">季度</button>
        <button class="rounded px-2 py-1" :class="period === 'annual' ? 'bg-primary text-white' : 'text-[hsl(var(--muted-foreground))]'" @click="period = 'annual'">年度</button>
      </div>
      <div class="flex items-center gap-1 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-1 text-[11px] font-semibold">
        <button class="rounded px-2 py-1" :class="mode === 'value' ? 'bg-primary text-white' : 'text-[hsl(var(--muted-foreground))]'" @click="mode = 'value'">数值</button>
        <button class="rounded px-2 py-1" :class="mode === 'growth' ? 'bg-primary text-white' : 'text-[hsl(var(--muted-foreground))]'" @click="mode = 'growth'">同比增速</button>
      </div>
      <div class="flex items-center gap-1 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-1 text-[11px] font-semibold">
        <button class="rounded px-2 py-1" :class="viewMode === 'chart' ? 'bg-primary text-white' : 'text-[hsl(var(--muted-foreground))]'" @click="viewMode = 'chart'">图表</button>
        <button class="rounded px-2 py-1" :class="viewMode === 'table' ? 'bg-primary text-white' : 'text-[hsl(var(--muted-foreground))]'" @click="viewMode = 'table'">数据表</button>
      </div>
    </div>

    <p class="text-[10px] text-[hsl(var(--muted-foreground))]">同比增速按{{ period === 'annual' ? '年度(N-1)' : '季度(N-4，同季度同比)' }}计算；毛利率等利润率指标本身就是比率，不支持切换成"同比增速"。</p>

    <div v-if="chartLines.every((l) => l.points.length === 0)" class="py-12 text-center text-xs text-[hsl(var(--muted-foreground))]">{{ NO_DATA_TEXT }}</div>
    <div v-else-if="viewMode === 'chart'" class="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-4">
      <EchartsUI ref="chartRef" height="360px" />
    </div>
    <div v-else class="overflow-hidden rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))]">
      <Table :columns="tableColumns" :data-source="tableData" :pagination="{ pageSize: 12 }" row-key="end" size="small" />
    </div>
  </div>
</template>
