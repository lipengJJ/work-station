<script lang="ts" setup>
import type { FundamentalsApi } from '#/api/core/fundamentals';

import { computed, ref, watch } from 'vue';

import { Table, Tag } from 'ant-design-vue';

import { getFundamentalsEarningsApi } from '#/api/core/fundamentals';

import { formatCompactUsd, formatDate, formatPercent, formatUsdPerShare, NO_DATA_TEXT } from '../_shared/format';

const props = defineProps<{
  symbol: string;
  refreshTick: number;
  overview: FundamentalsApi.OverviewData | null;
}>();

const loading = ref(false);
const errorMsg = ref('');
const data = ref<FundamentalsApi.EarningsData | null>(null);

async function load() {
  loading.value = true;
  errorMsg.value = '';
  try {
    const envelope = await getFundamentalsEarningsApi(props.symbol);
    data.value = envelope.data;
  } catch (e: any) {
    errorMsg.value = e.message || '加载失败';
  } finally {
    loading.value = false;
  }
}
watch(() => [props.symbol, props.refreshTick], load, { immediate: true });

const surpriseRows = computed(() => {
  if (!data.value) return [];
  const reactionByDate = new Map(data.value.post_earnings_reactions.map((r) => [r.report_date, r]));
  return [...data.value.eps_surprise_history].reverse().map((h) => ({
    ...h,
    reaction: reactionByDate.get(h.report_date) || null,
  }));
});

const lastReported = computed(() => data.value?.eps_surprise_history.filter((h) => h.eps_actual !== null).at(-1));

const surpriseColumns = [
  { title: '财报日期', dataIndex: 'report_date', key: 'report_date', width: 110 },
  { title: 'EPS 预期', dataIndex: 'eps_estimate', key: 'eps_estimate' },
  { title: 'EPS 实际', dataIndex: 'eps_actual', key: 'eps_actual' },
  { title: 'EPS Surprise', dataIndex: 'eps_surprise_percent', key: 'eps_surprise_percent' },
  { title: '下一交易日涨跌', dataIndex: 'next_day', key: 'next_day' },
  { title: '5个交易日涨跌', dataIndex: 'five_day', key: 'five_day' },
  { title: '盘后涨跌', dataIndex: 'after_hours', key: 'after_hours' },
];

const revenueEstimateColumns = [
  { title: '周期', dataIndex: 'period', key: 'period' },
  { title: '一致预期(均值)', dataIndex: 'avg', key: 'avg' },
  { title: '低值', dataIndex: 'low', key: 'low' },
  { title: '高值', dataIndex: 'high', key: 'high' },
  { title: '同比增速', dataIndex: 'growth', key: 'growth' },
  { title: '分析师人数', dataIndex: 'numberOfAnalysts', key: 'numberOfAnalysts' },
];

const gradeChangeColumns = [
  { title: '日期', dataIndex: 'GradeDate', key: 'GradeDate' },
  { title: '机构', dataIndex: 'Firm', key: 'Firm' },
  { title: '调整前评级', dataIndex: 'FromGrade', key: 'FromGrade' },
  { title: '调整后评级', dataIndex: 'ToGrade', key: 'ToGrade' },
  { title: '方向', dataIndex: 'Action', key: 'Action' },
  { title: '目标价', dataIndex: 'currentPriceTarget', key: 'currentPriceTarget' },
];

const PERIOD_LABEL: Record<string, string> = { '0q': '本季度', '+1q': '下季度', '0y': '本财年', '+1y': '下财年' };
</script>

<template>
  <div v-if="loading" class="py-12 text-center text-xs text-[hsl(var(--muted-foreground))]">正在加载财报与预期数据…</div>
  <div v-else-if="errorMsg" class="py-12 text-center text-xs text-destructive">{{ errorMsg }}</div>
  <div v-else-if="!data" class="py-12 text-center text-xs text-[hsl(var(--muted-foreground))]">{{ NO_DATA_TEXT }}</div>
  <div v-else class="space-y-4">
    <!-- 概览 -->
    <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <div class="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-3">
        <div class="text-[10px] text-[hsl(var(--muted-foreground))]">最近财报日期</div>
        <div class="font-mono text-sm font-bold text-[hsl(var(--foreground))]">{{ formatDate(lastReported?.report_date) }}</div>
      </div>
      <div class="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-3">
        <div class="text-[10px] text-[hsl(var(--muted-foreground))]">下次预计财报日期</div>
        <div class="font-mono text-sm font-bold text-[hsl(var(--foreground))]">{{ formatDate(overview?.next_earnings_date) }}</div>
      </div>
      <div class="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-3">
        <div class="text-[10px] text-[hsl(var(--muted-foreground))]">下次 EPS 一致预期</div>
        <div class="font-mono text-sm font-bold text-[hsl(var(--foreground))]">
          {{ formatUsdPerShare(overview?.eps_estimate_avg ?? null) }}
          <span class="text-[10px] text-[hsl(var(--muted-foreground))]">({{ formatUsdPerShare(overview?.eps_estimate_low ?? null) }} ~ {{ formatUsdPerShare(overview?.eps_estimate_high ?? null) }})</span>
        </div>
      </div>
      <div class="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-3">
        <div class="text-[10px] text-[hsl(var(--muted-foreground))]">下次营收一致预期</div>
        <div class="font-mono text-sm font-bold text-[hsl(var(--foreground))]">{{ formatCompactUsd(overview?.revenue_estimate_avg ?? null) }}</div>
      </div>
    </div>

    <!-- EPS Surprise 历史 + 财报后价格反应 -->
    <div class="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-4">
      <h3 class="mb-1 text-xs font-bold text-[hsl(var(--muted-foreground))]">EPS 预期差历史（Surprise = (实际-预期)/|预期|）</h3>
      <p class="mb-3 text-[10px] text-[hsl(var(--muted-foreground))]">
        营收 Surprise 历史需要"过去每期发布前的营收一致预期"，yfinance 免费接口只提供当前/未来周期的一致预期、不提供历史时点快照，这里暂时无法计算，标注为数据不足，不编造。
        盘后涨跌需要分钟级盘后行情，免费接口同样拿不到；下一交易日/5个交易日涨跌用真实日线收盘价计算。
      </p>
      <Table :columns="surpriseColumns" :data-source="surpriseRows" :pagination="{ pageSize: 8 }" row-key="report_date" size="small">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'eps_estimate'">{{ record.eps_estimate === null ? NO_DATA_TEXT : formatUsdPerShare(record.eps_estimate) }}</template>
          <template v-else-if="column.key === 'eps_actual'">{{ record.eps_actual === null ? NO_DATA_TEXT : formatUsdPerShare(record.eps_actual) }}</template>
          <template v-else-if="column.key === 'eps_surprise_percent'">
            <Tag v-if="record.eps_surprise_percent !== null" :color="record.eps_surprise_percent >= 0 ? 'success' : 'error'">
              {{ formatPercent(record.eps_surprise_percent) }}
            </Tag>
            <span v-else>{{ NO_DATA_TEXT }}</span>
          </template>
          <template v-else-if="column.key === 'next_day'">{{ record.reaction ? formatPercent(record.reaction.next_day_change_percent) : NO_DATA_TEXT }}</template>
          <template v-else-if="column.key === 'five_day'">{{ record.reaction ? formatPercent(record.reaction.five_day_change_percent) : NO_DATA_TEXT }}</template>
          <template v-else-if="column.key === 'after_hours'">数据不可用</template>
        </template>
      </Table>
    </div>

    <!-- 营收/EPS 一致预期 -->
    <div class="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-4">
      <h3 class="mb-3 text-xs font-bold text-[hsl(var(--muted-foreground))]">分析师一致预期（营收）</h3>
      <Table :columns="revenueEstimateColumns" :data-source="data.revenue_estimate" :pagination="false" row-key="period" size="small">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'period'">{{ PERIOD_LABEL[record.period] || record.period }}</template>
          <template v-else-if="['avg', 'low', 'high'].includes(column.key as string)">{{ formatCompactUsd(record[column.key as string]) }}</template>
          <template v-else-if="column.key === 'growth'">{{ record.growth === null ? NO_DATA_TEXT : formatPercent(record.growth * 100) }}</template>
        </template>
      </Table>
    </div>

    <!-- 分析师评级变化 -->
    <div class="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-4">
      <div class="mb-3 flex items-center justify-between">
        <h3 class="text-xs font-bold text-[hsl(var(--muted-foreground))]">最近90天分析师评级变化</h3>
        <div class="flex gap-2 text-xs font-mono">
          <Tag color="success">上调 {{ data.recent_90d_upgrades ?? NO_DATA_TEXT }}</Tag>
          <Tag color="error">下调 {{ data.recent_90d_downgrades ?? NO_DATA_TEXT }}</Tag>
        </div>
      </div>
      <Table :columns="gradeChangeColumns" :data-source="data.recent_grade_changes" :pagination="{ pageSize: 8 }" row-key="GradeDate" size="small">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'GradeDate'">{{ formatDate(record.GradeDate) }}</template>
          <template v-else-if="column.key === 'currentPriceTarget'">{{ record.currentPriceTarget ? formatUsdPerShare(record.currentPriceTarget) : NO_DATA_TEXT }}</template>
        </template>
      </Table>
    </div>
  </div>
</template>
