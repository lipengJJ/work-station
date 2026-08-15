<script lang="ts" setup>
import type { FundamentalsApi } from '#/api/core/fundamentals';
import type { StockItem } from '../_shared/types';

import { computed, onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import { message } from 'ant-design-vue';
import { Building2, Star } from 'lucide-vue-next';

import { addStockToWatchlistApi, getStockWatchlistApi, removeStockFromWatchlistApi } from '#/api/core/stock';
import { postFundamentalsRefreshApi, searchFundamentalsSymbolApi } from '#/api/core/fundamentals';

import FundamentalsTabs from '../_shared/FundamentalsTabs.vue';

const symbol = ref('');
const refreshTick = ref(0);

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
  symbol.value = result.symbol.toUpperCase();
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

// ---------------------------------------------------------------------- 刷新 ----

const refreshing = ref(false);
async function manualRefresh() {
  if (!symbol.value) return;
  refreshing.value = true;
  try {
    await postFundamentalsRefreshApi(symbol.value);
    refreshTick.value += 1;
    message.success('已刷新');
  } catch (e: any) {
    message.error(`刷新失败：${e.message}`);
  } finally {
    refreshing.value = false;
  }
}

onMounted(() => {
  loadWatchlist();
});
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
            @click="symbol = s.symbol"
          >
            {{ s.symbol }}
          </button>
        </div>

        <button
          v-if="symbol"
          class="flex items-center gap-1.5 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-1.5 text-xs font-bold text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
          :disabled="refreshing"
          @click="manualRefresh"
        >
          <span class="text-[11px]" :class="refreshing ? 'animate-spin' : ''">⟳</span>
          刷新
        </button>

        <button
          v-if="symbol"
          class="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-bold transition-all"
          :class="isInWatchlist ? 'border-amber-500/40 bg-amber-500/15 text-amber-300' : 'border-[hsl(var(--border))] bg-[hsl(var(--card))] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'"
          :disabled="watchlistBusy"
          @click="toggleWatchlist"
        >
          <Star class="h-3.5 w-3.5" :class="isInWatchlist ? 'fill-amber-400 text-amber-400' : ''" />
          {{ isInWatchlist ? '已加自选' : '加入自选' }}
        </button>
      </div>

      <!-- 初始未选择股票 -->
      <div v-if="!symbol" class="flex flex-1 flex-col items-center justify-center rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-12 text-center">
        <Building2 class="mb-4 h-12 w-12 text-[hsl(var(--muted-foreground))]" />
        <h3 class="mb-2 text-base font-bold text-[hsl(var(--foreground))]">输入股票代码开始基本面分析</h3>
        <p class="max-w-sm text-xs text-[hsl(var(--muted-foreground))]">支持代码、公司名搜索，或者从上方自选股快捷选择</p>
      </div>

      <!-- 完整基本面面板（与自选股 K 线共用，完全打平） -->
      <FundamentalsTabs v-else :symbol="symbol" :refresh-tick="refreshTick" />
    </div>
  </Page>
</template>
