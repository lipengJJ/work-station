<script lang="ts" setup>
import type { FundamentalsApi } from '#/api/core/fundamentals';
import type { StockItem } from '../_shared/types';

import { computed, onMounted, ref, watch } from 'vue';

import { Page } from '@vben/common-ui';

import { message, Tabs } from 'ant-design-vue';
import {
  Building2, DollarSign, FileText, Gauge, RefreshCw, ScanSearch,
  ShieldAlert, Star, TrendingUp, Users,
} from 'lucide-vue-next';

import { addStockToWatchlistApi, getStockWatchlistApi, removeStockFromWatchlistApi } from '#/api/core/stock';
import { getFundamentalsOverviewApi, postFundamentalsRefreshApi, searchFundamentalsSymbolApi } from '#/api/core/fundamentals';

import { formatCompactUsd, formatDate, formatMultiple, formatPercent } from './_shared/format';
import OverviewTab from './_components/OverviewTab.vue';
import FinancialsTab from './_components/FinancialsTab.vue';
import ValuationTab from './_components/ValuationTab.vue';
import EarningsTab from './_components/EarningsTab.vue';
import FilingsTab from './_components/FilingsTab.vue';
import InstitutionsInsidersTab from './_components/InstitutionsInsidersTab.vue';
import RisksAiTab from './_components/RisksAiTab.vue';

type PageState = 'empty' | 'error' | 'loading' | 'no_data' | 'success';

const symbol = ref('');
const activeTab = ref('overview');
const refreshTick = ref(0);

const pageState = ref<PageState>('empty');
const errorMessage = ref('');
const overview = ref<FundamentalsApi.OverviewData | null>(null);
const overviewSources = ref<string[]>([]);
const overviewPartialFailures = ref<string[]>([]);
const overviewFetchedAt = ref('');

// ---------------------------------------------------------------------- 搜索 ----

const searchQuery = ref('');
const searchResults = ref<FundamentalsApi.SearchResult[]>([]);
const searchLoading = ref(false);
const searchOpen = ref(false);
let searchDebounce: ReturnType<typeof setTimeout> | undefined;

function onSearchInput() {
  searchOpen.value = true;
  if (searchDebounce) clearTimeout(searchDebounce);
  const q = searchQuery.value.trim();
  if (!q) {
    searchResults.value = [];
    return;
  }
  searchDebounce = setTimeout(async () => {
    searchLoading.value = true;
    try {
      searchResults.value = await searchFundamentalsSymbolApi(q);
    } catch {
      searchResults.value = [];
    } finally {
      searchLoading.value = false;
    }
  }, 300);
}

function pickResult(result: FundamentalsApi.SearchResult) {
  searchQuery.value = '';
  searchResults.value = [];
  searchOpen.value = false;
  loadSymbol(result.symbol);
}

// -------------------------------------------------------------- 自选股快捷选择 ----

const watchlistStocks = ref<StockItem[]>([]);
async function loadWatchlist() {
  try {
    watchlistStocks.value = await getStockWatchlistApi();
  } catch {
    watchlistStocks.value = [];
  }
}

const isInWatchlist = computed(() => watchlistStocks.value.some((s) => s.symbol === symbol.value));
const watchlistBusy = ref(false);

async function toggleWatchlist() {
  if (!symbol.value) return;
  watchlistBusy.value = true;
  try {
    if (isInWatchlist.value) {
      watchlistStocks.value = await removeStockFromWatchlistApi(symbol.value);
      message.success(`已从自选股移除 ${symbol.value}`);
    } else {
      watchlistStocks.value = await addStockToWatchlistApi(symbol.value);
      message.success(`已加入自选股 ${symbol.value}`);
    }
  } catch (e: any) {
    message.error(`操作失败：${e.message}`);
  } finally {
    watchlistBusy.value = false;
  }
}

// ---------------------------------------------------------------------- 加载 ----

async function loadSymbol(sym: string) {
  symbol.value = sym.trim().toUpperCase();
  pageState.value = 'loading';
  errorMessage.value = '';
  try {
    const envelope = await getFundamentalsOverviewApi(symbol.value);
    overview.value = envelope.data;
    overviewSources.value = envelope.sources;
    overviewPartialFailures.value = envelope.partial_failures;
    overviewFetchedAt.value = envelope.fetched_at;
    pageState.value = 'success';
  } catch (e: any) {
    overview.value = null;
    if (e?.response?.status === 404) {
      pageState.value = 'no_data';
      errorMessage.value = e?.response?.data?.detail || `找不到 ${symbol.value}`;
    } else {
      pageState.value = 'error';
      errorMessage.value = e.message || '加载失败，请稍后重试';
    }
  }
}

const refreshing = ref(false);
async function manualRefresh() {
  if (!symbol.value) return;
  refreshing.value = true;
  try {
    await postFundamentalsRefreshApi(symbol.value);
    await loadSymbol(symbol.value);
    refreshTick.value += 1;
    message.success('已刷新');
  } catch (e: any) {
    message.error(`刷新失败：${e.message}`);
  } finally {
    refreshing.value = false;
  }
}

watch(activeTab, () => {
  // 子 tab 组件自己在 mounted/symbol 变化时懒加载数据，这里不用做什么，
  // 留一个挂载点方便以后要做"tab 首次激活才加载"之外的行为
});

onMounted(() => {
  loadWatchlist();
});

const TABS = [
  { key: 'overview', label: '核心总览', icon: Gauge },
  { key: 'financials', label: '财务趋势', icon: TrendingUp },
  { key: 'valuation', label: '估值分析', icon: DollarSign },
  { key: 'earnings', label: '财报与预期', icon: ScanSearch },
  { key: 'filings', label: 'SEC公告与事件', icon: FileText },
  { key: 'institutions', label: '机构与内部人', icon: Users },
  { key: 'risks', label: '风险与AI研判', icon: ShieldAlert },
];
</script>

<template>
  <Page :auto-content-height="true" content-class="!p-0">
    <div class="custom-scrollbar flex h-full flex-1 flex-col overflow-y-auto bg-[hsl(var(--background-deep))] p-6 select-none">
      <!-- 搜索区 -->
      <div class="mb-4 flex flex-wrap items-center gap-3">
        <div class="relative w-80">
          <input
            v-model="searchQuery"
            placeholder="输入代码或公司名，例如 AAPL / Apple"
            class="w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-2 text-sm text-[hsl(var(--foreground))] outline-none focus:border-indigo-500"
            @input="onSearchInput"
            @focus="searchOpen = true"
            @keyup.enter="searchResults[0] && pickResult(searchResults[0])"
          />
          <div
            v-if="searchOpen && (searchResults.length > 0 || searchLoading)"
            class="absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--accent))] shadow-xl"
          >
            <div v-if="searchLoading" class="px-3 py-2 text-xs text-[hsl(var(--muted-foreground))]">搜索中…</div>
            <button
              v-for="r in searchResults"
              :key="r.symbol"
              class="flex w-full items-center justify-between px-3 py-2 text-left text-xs hover:bg-[hsl(var(--muted))]"
              @click="pickResult(r)"
            >
              <span class="font-mono font-bold text-[hsl(var(--foreground))]">{{ r.symbol }}</span>
              <span class="ml-2 truncate text-[hsl(var(--muted-foreground))]">{{ r.title }}</span>
            </button>
          </div>
        </div>

        <div class="flex flex-wrap items-center gap-1.5">
          <span class="text-xs text-[hsl(var(--muted-foreground))]">自选股快捷选择:</span>
          <button
            v-for="s in watchlistStocks"
            :key="s.symbol"
            class="rounded-lg border px-2 py-1 font-mono text-xs font-bold transition-all"
            :class="symbol === s.symbol ? 'border-indigo-500 bg-indigo-600 text-white' : 'border-[hsl(var(--border))] bg-[hsl(var(--card))] text-[hsl(var(--muted-foreground))] hover:border-indigo-500/50'"
            @click="loadSymbol(s.symbol)"
          >
            {{ s.symbol }}
          </button>
        </div>
      </div>

      <!-- 初始未选择股票 -->
      <div v-if="pageState === 'empty'" class="flex flex-1 flex-col items-center justify-center rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-12 text-center">
        <Building2 class="mb-4 h-12 w-12 text-[hsl(var(--muted-foreground))]" />
        <h3 class="mb-2 text-base font-bold text-[hsl(var(--foreground))]">输入股票代码开始基本面分析</h3>
        <p class="max-w-sm text-xs text-[hsl(var(--muted-foreground))]">支持代码、公司名搜索，或者从上方自选股快捷选择</p>
      </div>

      <!-- 加载中 -->
      <div v-else-if="pageState === 'loading'" class="flex flex-1 items-center justify-center text-sm text-[hsl(var(--muted-foreground))]">
        正在加载 {{ symbol }} 的基本面数据…
      </div>

      <!-- 无数据 / 找不到 -->
      <div v-else-if="pageState === 'no_data'" class="flex flex-1 flex-col items-center justify-center rounded-2xl border border-amber-500/30 bg-amber-500/5 p-12 text-center">
        <ScanSearch class="mb-4 h-12 w-12 text-amber-500" />
        <h3 class="mb-2 text-base font-bold text-[hsl(var(--foreground))]">找不到 {{ symbol }}</h3>
        <p class="max-w-sm text-xs text-amber-300">{{ errorMessage }}</p>
      </div>

      <!-- 网络错误 / API 报错 -->
      <div v-else-if="pageState === 'error'" class="flex flex-1 flex-col items-center justify-center rounded-2xl border border-rose-500/30 bg-rose-500/5 p-12 text-center">
        <ShieldAlert class="mb-4 h-12 w-12 text-rose-500" />
        <h3 class="mb-2 text-base font-bold text-[hsl(var(--foreground))]">加载 {{ symbol }} 失败</h3>
        <p class="mb-4 max-w-md text-xs text-rose-300">{{ errorMessage }}</p>
        <button class="rounded-lg bg-rose-500/20 px-4 py-1.5 text-xs font-bold text-rose-300 hover:bg-rose-500/30" @click="loadSymbol(symbol)">
          重试
        </button>
      </div>

      <!-- 成功（含部分数据源失败的降级展示）-->
      <template v-else-if="pageState === 'success' && overview">
        <div
          v-if="overviewPartialFailures.length > 0"
          class="mb-4 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-xs text-amber-300"
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
                  <span v-if="overview.sector" class="rounded border border-indigo-500/20 bg-indigo-500/10 px-2 py-0.5 text-indigo-300">
                    {{ overview.sector }}<template v-if="overview.industry"> / {{ overview.industry }}</template>
                  </span>
                  <span>数据更新: {{ overviewFetchedAt.slice(0, 19).replace('T', ' ') }}</span>
                  <span>来源: {{ overviewSources.join(', ') || '暂无' }}</span>
                </div>
              </div>
            </div>

            <div class="flex items-center gap-2">
              <button
                class="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-bold transition-all"
                :class="isInWatchlist ? 'border-amber-500/40 bg-amber-500/15 text-amber-300' : 'border-[hsl(var(--border))] bg-[hsl(var(--card))] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'"
                :disabled="watchlistBusy"
                @click="toggleWatchlist"
              >
                <Star class="h-3.5 w-3.5" :class="isInWatchlist ? 'fill-amber-400 text-amber-400' : ''" />
                {{ isInWatchlist ? '已加自选' : '加入自选' }}
              </button>
              <button
                class="flex items-center gap-1.5 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-1.5 text-xs font-bold text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
                :disabled="refreshing"
                @click="manualRefresh"
              >
                <RefreshCw class="h-3.5 w-3.5" :class="refreshing ? 'animate-spin' : ''" />
                刷新
              </button>
            </div>
          </div>

          <div class="mt-4 grid grid-cols-2 gap-3 font-mono sm:grid-cols-3 lg:grid-cols-6">
            <div>
              <div class="text-[10px] text-[hsl(var(--muted-foreground))]">当前价格</div>
              <div class="text-lg font-black text-[hsl(var(--foreground))]">${{ overview.price?.toFixed(2) ?? '--' }}</div>
              <div class="text-[11px] font-bold" :class="(overview.change ?? 0) >= 0 ? 'text-rose-500' : 'text-emerald-400'">
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
          <FinancialsTab v-else-if="activeTab === 'financials'" :symbol="symbol" :refresh-tick="refreshTick" />
          <ValuationTab v-else-if="activeTab === 'valuation'" :symbol="symbol" :refresh-tick="refreshTick" />
          <EarningsTab v-else-if="activeTab === 'earnings'" :symbol="symbol" :refresh-tick="refreshTick" :overview="overview" />
          <FilingsTab v-else-if="activeTab === 'filings'" :symbol="symbol" :refresh-tick="refreshTick" />
          <InstitutionsInsidersTab v-else-if="activeTab === 'institutions'" :symbol="symbol" :refresh-tick="refreshTick" />
          <RisksAiTab v-else-if="activeTab === 'risks'" :symbol="symbol" :refresh-tick="refreshTick" />
        </div>
      </template>
    </div>
  </Page>
</template>

<style scoped>
:deep(.fundamentals-tabs .ant-tabs-nav) {
  margin-bottom: 0;
}
</style>
