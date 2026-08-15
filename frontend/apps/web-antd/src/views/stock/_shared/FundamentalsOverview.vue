<script lang="ts" setup>
import type { FundamentalsApi } from '#/api/core/fundamentals';

import { computed, ref, watch } from 'vue';

import { Loader2 } from 'lucide-vue-next';

import { getFundamentalsOverviewApi } from '#/api/core/fundamentals';

/**
 * 精简基本面概览：拉取 overview 接口（yfinance + SEC），展示关键估值/盈利/财务指标网格。
 * 基本面页与 K线查看全屏层共用。
 */
const props = defineProps<{ symbol: string }>();

const loading = ref(false);
const error = ref('');
const data = ref<FundamentalsApi.OverviewData | null>(null);

async function loadOverview() {
  if (!props.symbol) return;
  loading.value = true;
  error.value = '';
  try {
    // overview 冷启动可能拉 SEC（慢/超时降级），给 30s 超时而不是用全局默认
    const env = await getFundamentalsOverviewApi(props.symbol, { timeout: 30000 });
    data.value = env.data;
  } catch (e: any) {
    error.value = e.message || '获取基本面数据失败';
    data.value = null;
  } finally {
    loading.value = false;
  }
}

watch(() => props.symbol, loadOverview, { immediate: true });

function fmtMoney(v: number | null | undefined) {
  if (v === null || v === undefined || Number.isNaN(v)) return '--';
  if (Math.abs(v) >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (Math.abs(v) >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (Math.abs(v) >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  return `$${v.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
}
function fmtNum(v: number | null | undefined, suffix = '') {
  if (v === null || v === undefined || Number.isNaN(v)) return '--';
  return `${v.toFixed(2)}${suffix}`;
}
function fmtPct(v: number | null | undefined) {
  return fmtNum(v, '%');
}

const items = computed(() => {
  const d = data.value;
  if (!d) return [];
  return [
    { label: '市值', value: fmtMoney(d.market_cap), sub: d.sector || '--' },
    { label: 'PE (TTM)', value: fmtNum(d.pe_ttm, 'x'), sub: d.pe_forward ? `Forward ${fmtNum(d.pe_forward, 'x')}` : '' },
    { label: 'PB', value: fmtNum(d.pb, 'x'), sub: d.peg_ratio ? `PEG ${fmtNum(d.peg_ratio)}` : '' },
    { label: 'ROE', value: fmtPct(d.roe), sub: d.roa ? `ROA ${fmtPct(d.roa)}` : '' },
    { label: '毛利率', value: fmtPct(d.gross_margin), sub: d.operating_margin ? `营业 ${fmtPct(d.operating_margin)}` : '' },
    { label: '营收增速', value: fmtPct(d.revenue_growth), sub: d.earnings_growth ? `利润 ${fmtPct(d.earnings_growth)}` : '' },
    { label: '股息率', value: fmtPct(d.dividend_yield), sub: d.fcf_yield ? `FCF ${fmtPct(d.fcf_yield)}` : '' },
    { label: '负债/权益', value: fmtNum(d.debt_to_equity), sub: d.net_debt != null ? `净债 ${fmtMoney(d.net_debt)}` : '' },
    { label: 'EPS (TTM)', value: d.eps_ttm ? `$${fmtNum(d.eps_ttm)}` : '--', sub: d.eps_forward ? `Forward $${fmtNum(d.eps_forward)}` : '' },
    { label: '下次财报', value: d.next_earnings_date || '--', sub: d.eps_estimate_avg ? `EPS预期 $${fmtNum(d.eps_estimate_avg)}` : '' },
  ];
});
</script>

<template>
  <div>
    <div v-if="loading" class="flex flex-col items-center justify-center gap-2 py-14 text-xs text-[hsl(var(--muted-foreground))]">
      <Loader2 class="h-5 w-5 animate-spin text-indigo-400" />
      正在拉取 {{ symbol }} 基本面数据…
    </div>
    <div v-else-if="error" class="rounded-xl border border-rose-500/30 bg-rose-500/10 p-8 text-center text-xs text-rose-300">
      {{ error }}
    </div>
    <div v-else class="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
      <div
        v-for="it in items"
        :key="it.label"
        class="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] px-3 py-2.5"
      >
        <div class="text-[10px] text-[hsl(var(--muted-foreground))]">{{ it.label }}</div>
        <div class="mt-0.5 font-mono text-sm font-extrabold text-[hsl(var(--foreground))]">{{ it.value }}</div>
        <div class="mt-0.5 truncate text-[10px] text-[hsl(var(--muted-foreground))]" :title="it.sub">{{ it.sub || '--' }}</div>
      </div>
    </div>
    <p class="mt-3 text-[10px] text-[hsl(var(--muted-foreground))]">
      数据来源：Yahoo Finance / SEC EDGAR（缓存 60 秒，可在「基本面」页查看完整财报与估值历史）
    </p>
  </div>
</template>
