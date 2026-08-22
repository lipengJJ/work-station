<script lang="ts" setup>
import type { FundamentalsApi } from '#/api/core/fundamentals';

import { ref, watch } from 'vue';

import { Tabs } from 'ant-design-vue';
import {
  DollarSign, FileText, Gauge, Loader2, ScanSearch, ShieldAlert, TrendingUp, Users,
} from 'lucide-vue-next';

import { getFundamentalsOverviewApi } from '#/api/core/fundamentals';

import { formatCompactUsd, formatDate, formatMultiple, formatPercent } from '../fundamentals/_shared/format';
import OverviewTab from '../fundamentals/_components/OverviewTab.vue';
import FinancialsTab from '../fundamentals/_components/FinancialsTab.vue';
import ValuationTab from '../fundamentals/_components/ValuationTab.vue';
import EarningsTab from '../fundamentals/_components/EarningsTab.vue';
import FilingsTab from '../fundamentals/_components/FilingsTab.vue';
import InstitutionsInsidersTab from '../fundamentals/_components/InstitutionsInsidersTab.vue';
import RisksAiTab from '../fundamentals/_components/RisksAiTab.vue';

/**
 * 完整基本面面板（与「股票分析 > 基本面」页共用同一套 tab 组件）：
 * 核心总览 / 财务趋势(财报) / 估值 / 财报与预期 / SEC公告 / 机构内部人 / 风险AI研判。
 * 自选股 K 线全屏层与基本面页都用它，保证两边完全打平。
 * 自身负责拉取 overview 摘要（供摘要区 + OverviewTab/EarningsTab 使用）。
 */
const props = defineProps<{ symbol: string; refreshTick?: number }>();

const activeTab = ref('overview');
const overview = ref<FundamentalsApi.OverviewData | null>(null);
const overviewSources = ref<string[]>([]);
const overviewPartialFailures = ref<string[]>([]);
const overviewFetchedAt = ref('');
const loading = ref(false);
const errorMsg = ref('');

const TABS = [
  { key: 'overview', label: '核心总览', icon: Gauge },
  { key: 'financials', label: '财务趋势', icon: TrendingUp },
  { key: 'valuation', label: '估值分析', icon: DollarSign },
  { key: 'earnings', label: '财报与预期', icon: ScanSearch },
  { key: 'filings', label: 'SEC公告与事件', icon: FileText },
  { key: 'institutions', label: '机构与内部人', icon: Users },
  { key: 'risks', label: '风险与AI研判', icon: ShieldAlert },
];

async function loadOverview() {
  if (!props.symbol) return;
  loading.value = true;
  errorMsg.value = '';
  try {
    // overview 冷启动可能拉 SEC（慢/超时降级），给 30s 超时
    const envelope = await getFundamentalsOverviewApi(props.symbol, { timeout: 30000 });
    overview.value = envelope.data;
    overviewSources.value = envelope.sources;
    overviewPartialFailures.value = envelope.partial_failures;
    overviewFetchedAt.value = envelope.fetched_at;
  } catch (e: any) {
    overview.value = null;
    errorMsg.value = e?.response?.status === 404
      ? (e?.response?.data?.detail || `找不到 ${props.symbol}`)
      : (e.message || '加载失败，请稍后重试');
  } finally {
    loading.value = false;
  }
}

watch(
  () => [props.symbol, props.refreshTick] as const,
  () => loadOverview(),
  { immediate: true },
);
</script>

<template>
  <div class="flex h-full flex-1 flex-col overflow-y-auto">
    <!-- 加载中 -->
    <div v-if="loading" class="flex flex-1 items-center justify-center gap-2 text-sm text-[hsl(var(--muted-foreground))]">
      <Loader2 class="h-4 w-4 animate-spin" />
      正在加载 {{ symbol }} 的基本面数据…
    </div>

    <!-- 加载失败 -->
    <div v-else-if="errorMsg" class="flex flex-1 flex-col items-center justify-center rounded-2xl border border-destructive/30 bg-destructive/5 p-12 text-center">
      <ShieldAlert class="mb-4 h-12 w-12 text-destructive" />
      <h3 class="mb-2 text-base font-bold text-[hsl(var(--foreground))]">加载 {{ symbol }} 失败</h3>
      <p class="mb-4 max-w-md text-xs text-destructive">{{ errorMsg }}</p>
      <button class="rounded-lg bg-destructive/20 px-4 py-1.5 text-xs font-bold text-destructive hover:bg-destructive/30" @click="loadOverview()">
        重试
      </button>
    </div>

    <!-- 成功 -->
    <template v-else-if="overview">
      <div
        v-if="overviewPartialFailures.length > 0"
        class="mb-4 rounded-xl border border-warning/30 bg-warning/10 px-4 py-2 text-xs text-warning"
      >
        部分数据源本次获取失败，以下内容可能不完整：{{ overviewPartialFailures.join('；') }}
      </div>

      <!-- 公司摘要区 -->
      <div class="mb-4 rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-5">
        <div class="flex flex-wrap items-start justify-between gap-4">
          <div class="flex items-center gap-3">
            <div class="flex h-12 w-12 items-center justify-center rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--muted))] font-mono text-sm font-bold text-[hsl(var(--foreground))]">
              {{ overview.symbol.slice(0, 2) }}
            </div>
            <div>
              <div class="flex items-center gap-2">
                <h1 class="text-xl font-extrabold text-[hsl(var(--foreground))]">{{ overview.symbol }}</h1>
                <span class="text-sm text-[hsl(var(--muted-foreground))]">{{ overview.name }}</span>
              </div>
              <div class="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-[hsl(var(--muted-foreground))]">
                <span v-if="overview.sector" class="rounded border border-primary/20 bg-primary/10 px-2 py-0.5 text-primary">
                  {{ overview.sector }}<template v-if="overview.industry"> / {{ overview.industry }}</template>
                </span>
                <span>数据更新: {{ overviewFetchedAt.slice(0, 19).replace('T', ' ') }}</span>
                <span>来源: {{ overviewSources.join(', ') || '暂无' }}</span>
              </div>
            </div>
          </div>
        </div>

        <div class="mt-4 grid grid-cols-2 gap-3 font-mono sm:grid-cols-3 lg:grid-cols-6">
          <div>
            <div class="text-[10px] text-[hsl(var(--muted-foreground))]">当前价格</div>
            <div class="text-lg font-black text-[hsl(var(--foreground))]">${{ overview.price?.toFixed(2) ?? '--' }}</div>
            <div class="text-[11px] font-bold" :class="(overview.change ?? 0) >= 0 ? 'text-destructive' : 'text-success'">
              {{ overview.change >= 0 ? '+' : '' }}{{ overview.change?.toFixed(2) }} ({{ formatPercent(overview.change_percent) }})
            </div>
          </div>
          <div>
            <div class="text-[10px] text-[hsl(var(--muted-foreground))]">市值</div>
            <div class="text-sm font-bold text-[hsl(var(--foreground))]">{{ formatCompactUsd(overview.market_cap) }}</div>
          </div>
          <div>
            <div class="text-[10px] text-[hsl(var(--muted-foreground))]">TTM PE</div>
            <div class="text-sm font-bold text-[hsl(var(--foreground))]">{{ formatMultiple(overview.pe_ttm) }}</div>
          </div>
          <div>
            <div class="text-[10px] text-[hsl(var(--muted-foreground))]">Forward PE</div>
            <div class="text-sm font-bold text-[hsl(var(--foreground))]">{{ formatMultiple(overview.pe_forward) }}</div>
          </div>
          <div>
            <div class="text-[10px] text-[hsl(var(--muted-foreground))]">下次财报日期</div>
            <div class="text-sm font-bold text-[hsl(var(--foreground))]">{{ formatDate(overview.next_earnings_date) }}</div>
          </div>
          <div>
            <div class="text-[10px] text-[hsl(var(--muted-foreground))]">员工人数</div>
            <div class="text-sm font-bold text-[hsl(var(--foreground))]">{{ overview.employees?.toLocaleString() ?? '暂无数据' }}</div>
          </div>
        </div>
      </div>

      <!-- 子 Tab -->
      <Tabs v-model:active-key="activeTab" class="fundamentals-tabs">
        <Tabs.TabPane v-for="t in TABS" :key="t.key">
          <template #tab>
            <span class="flex items-center gap-1.5">
              <component :is="t.icon" class="h-3.5 w-3.5" />
              {{ t.label }}
            </span>
          </template>
        </Tabs.TabPane>
      </Tabs>

      <div class="mt-2 flex-1">
        <OverviewTab v-if="activeTab === 'overview'" :overview="overview" />
        <FinancialsTab v-else-if="activeTab === 'financials'" :symbol="symbol" :refresh-tick="refreshTick ?? 0" />
        <ValuationTab v-else-if="activeTab === 'valuation'" :symbol="symbol" :refresh-tick="refreshTick ?? 0" />
        <EarningsTab v-else-if="activeTab === 'earnings'" :symbol="symbol" :refresh-tick="refreshTick ?? 0" :overview="overview" />
        <FilingsTab v-else-if="activeTab === 'filings'" :symbol="symbol" :refresh-tick="refreshTick ?? 0" />
        <InstitutionsInsidersTab v-else-if="activeTab === 'institutions'" :symbol="symbol" :refresh-tick="refreshTick ?? 0" />
        <RisksAiTab v-else-if="activeTab === 'risks'" :symbol="symbol" :refresh-tick="refreshTick ?? 0" />
      </div>
    </template>
  </div>
</template>

<style scoped>
:deep(.fundamentals-tabs .ant-tabs-nav) {
  margin-bottom: 0;
}
</style>
