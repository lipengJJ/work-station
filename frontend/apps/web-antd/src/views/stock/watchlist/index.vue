<script lang="ts" setup>
import type { StockItem } from '../_shared/types';

import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';

import { Page } from '@vben/common-ui';

import { message } from 'ant-design-vue';
import { BarChart2, CheckCircle2, Plus, Star, X } from 'lucide-vue-next';

import { addStockToWatchlistApi, getStockWatchlistApi, removeStockFromWatchlistApi } from '#/api/core/stock';

import { selectStock, stocks, toggleFavorite } from '../_shared/stock-state';

// 固定红涨绿跌（参考项目原来的切换开关在被丢弃的顶部栏里，这次不做那个开关）
const colorMode = 'cn' as const;

const router = useRouter();

const activeTab = ref<'ai' | 'all' | 'china' | 'favorites' | 'high_rsi'>('favorites');
const onlyFavorites = ref(true);
const displayLayout = ref<'heatmap' | 'list'>('list');

const favoriteCount = computed(() => stocks.value.filter((s) => s.isFavorite).length);

const filteredStocks = computed(() => {
  return stocks.value.filter((st) => {
    if (onlyFavorites.value && !st.isFavorite) {
      return false;
    }
    if (activeTab.value === 'favorites') {
      return st.isFavorite;
    }
    if (activeTab.value === 'ai') return st.tags.some((t) => t.includes('AI') || t.includes('芯片'));
    if (activeTab.value === 'china') return st.sector.includes('中国') || st.tags.some((t) => t.includes('中国'));
    if (activeTab.value === 'high_rsi') return st.rsi !== null && st.rsi > 60;
    return true;
  });
});

function goToKline(st: StockItem) {
  selectStock(st);
  router.push('/stock/quotes');
}

// 涨跌类字段（1D/1W/1M）真实数据里 1W/1M 是 null（自选股列表只有当日快照，1W/1M
// 需要额外拉历史K线自己算，这次没做），null 一律显示 "--"、用中性灰色，不当成 0 处理
function changeClass(v: null | number) {
  if (v === null) return 'text-slate-500';
  return v >= 0 ? (colorMode === 'cn' ? 'text-rose-500' : 'text-emerald-400') : colorMode === 'cn' ? 'text-emerald-400' : 'text-rose-500';
}
function formatPercent(v: null | number) {
  if (v === null) return '--';
  return `${v >= 0 ? '+' : ''}${v}%`;
}
function rsiClass(v: null | number) {
  if (v === null) return 'border-slate-700 bg-slate-800 text-slate-400';
  if (v > 65) return 'border-rose-500/20 bg-rose-500/10 text-rose-400';
  if (v < 40) return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400';
  return 'border-slate-700 bg-slate-800 text-slate-300';
}
function macdClass(sig: StockItem['macdSignal']) {
  if (sig === 'Bullish Cross') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400';
  if (sig === 'Bearish Cross') return 'border-rose-500/30 bg-rose-500/10 text-rose-400';
  return 'border-slate-700 bg-slate-800 text-slate-400';
}
function macdText(sig: StockItem['macdSignal']) {
  if (sig === 'Bullish Cross') return '金叉多头';
  if (sig === 'Bearish Cross') return '死叉空头';
  if (sig === 'Neutral') return '震荡整理';
  return '--';
}

// ------------------------------------------------------- yfinance 真实数据 ----

const usingRealData = ref(false);
const loadError = ref('');
const watchlistLoading = ref(false);

async function loadRealWatchlist() {
  watchlistLoading.value = true;
  loadError.value = '';
  try {
    const real = await getStockWatchlistApi();
    stocks.value = real;
    usingRealData.value = true;
  } catch (e: any) {
    loadError.value = e.message || '获取自选股失败';
    usingRealData.value = false;
  } finally {
    watchlistLoading.value = false;
  }
}

// ---------------------------------------------------------- 添加 / 移除代码 ----

const newSymbol = ref('');
const addingSymbol = ref(false);

async function addStock() {
  const symbol = newSymbol.value.trim().toUpperCase();
  if (!symbol) {
    message.error('请输入股票代码');
    return;
  }
  addingSymbol.value = true;
  try {
    stocks.value = await addStockToWatchlistApi(symbol);
    usingRealData.value = true;
    loadError.value = '';
    newSymbol.value = '';
    message.success(`已添加 ${symbol}`);
  } catch (e: any) {
    message.error(`添加失败：${e.message}`);
  } finally {
    addingSymbol.value = false;
  }
}

async function removeStock(st: StockItem) {
  if (!usingRealData.value) {
    // 尚未接上真实数据（比如还没配置 API Key）时展示的是示例数据，星标只做本地演示切换
    toggleFavorite(st);
    return;
  }
  try {
    stocks.value = await removeStockFromWatchlistApi(st.symbol);
    message.success(`已移除 ${st.symbol}`);
  } catch (e: any) {
    message.error(`移除失败：${e.message}`);
  }
}

onMounted(() => {
  loadRealWatchlist();
});
</script>

<template>
  <Page :auto-content-height="true" content-class="!p-0">
    <div class="custom-scrollbar flex h-full flex-1 flex-col overflow-y-auto bg-[#0B0E14] p-6 select-none">
      <!-- yfinance 真实数据配置状态提示 -->
      <div
        v-if="loadError"
        class="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-xs text-rose-300"
      >
        <span>获取真实自选股失败：{{ loadError }}（当前展示的是示例数据）</span>
        <button class="rounded-lg bg-rose-500/20 px-3 py-1 font-bold hover:bg-rose-500/30" @click="loadRealWatchlist">
          重试
        </button>
      </div>
      <div
        v-else-if="usingRealData"
        class="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-xs text-emerald-300"
      >
        <span>已连接 Yahoo Finance，展示真实自选股数据（1W/1M 涨幅、RSI、MACD 信号暂不支持，显示为 --）</span>
      </div>
      <div v-if="watchlistLoading" class="mb-4 text-xs text-slate-400">正在获取真实自选股数据…</div>

      <!-- 添加自选股代码 -->
      <div class="mb-4 flex flex-wrap items-center gap-2">
        <input
          v-model="newSymbol"
          placeholder="输入股票代码，例如 NVDA"
          class="w-48 rounded-lg border border-[#232B3E] bg-[#121622] px-3 py-1.5 text-xs text-white outline-none focus:border-indigo-500"
          @keyup.enter="addStock"
        />
        <button
          class="flex items-center gap-1 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500 disabled:opacity-50"
          :disabled="addingSymbol"
          @click="addStock"
        >
          <Plus class="h-3.5 w-3.5" />
          <span>{{ addingSymbol ? '添加中...' : '添加自选股' }}</span>
        </button>
      </div>

      <!-- Header Controls Banner -->
      <div class="mb-6 flex flex-col justify-between gap-4 md:flex-row md:items-center">
        <div>
          <h1 class="flex items-center gap-2 text-xl font-extrabold text-white">
            <Star class="h-5 w-5 fill-amber-400 text-amber-400" />
            <span>关注的股票研判</span>
            <span class="rounded-full border border-amber-500/30 bg-amber-500/20 px-2 py-0.5 font-mono text-xs text-amber-300">
              已关注 {{ favoriteCount }} 支
            </span>
          </h1>
          <p class="mt-1 text-xs text-slate-400">只专注核心自选标的，实时监控最新价格、1D / 1W / 1M 涨跌幅与量化信号</p>
        </div>

        <div class="flex flex-wrap items-center gap-3">
          <!-- Quick "Only Favorites" Checkbox Toggle -->
          <button
            class="flex items-center gap-2 rounded-xl border px-3 py-1.5 text-xs font-bold transition-all" :class="[
              onlyFavorites
                ? 'border-amber-500/40 bg-amber-500/15 text-amber-300 shadow-md shadow-amber-500/10'
                : 'border-[#232B3E] bg-[#121622] text-slate-400 hover:text-slate-200',
            ]"
            @click="onlyFavorites = !onlyFavorites"
          >
            <CheckCircle2 class="h-4 w-4" :class="[onlyFavorites ? 'text-amber-400' : 'text-slate-500']" />
            <span>只看关注的股票</span>
          </button>

          <!-- Category Filters -->
          <div class="flex items-center rounded-xl border border-[#232B3E] bg-[#121622] p-1 text-xs font-semibold">
            <button
              class="flex items-center gap-1.5 rounded-lg px-3 py-1.5 transition-all" :class="[
                activeTab === 'favorites' ? 'bg-amber-500 font-extrabold text-slate-950' : 'text-slate-400 hover:text-slate-200',
              ]"
              @click="activeTab = 'favorites'"
            >
              <Star class="h-3.5 w-3.5" :class="activeTab === 'favorites' ? 'fill-slate-950' : ''" />
              <span>关注标的 ({{ favoriteCount }})</span>
            </button>
            <button
              class="rounded-lg px-3 py-1.5 transition-all" :class="[
                activeTab === 'all' ? 'bg-indigo-600 font-bold text-white' : 'text-slate-400 hover:text-slate-200',
              ]"
              @click="activeTab = 'all'"
            >
              全部标的
            </button>
            <button
              class="rounded-lg px-3 py-1.5 transition-all" :class="[
                activeTab === 'ai' ? 'bg-indigo-600 font-bold text-white' : 'text-slate-400 hover:text-slate-200',
              ]"
              @click="activeTab = 'ai'"
            >
              AI/半导体
            </button>
            <button
              class="rounded-lg px-3 py-1.5 transition-all" :class="[
                activeTab === 'china' ? 'bg-indigo-600 font-bold text-white' : 'text-slate-400 hover:text-slate-200',
              ]"
              @click="activeTab = 'china'"
            >
              中概资产
            </button>
          </div>

          <!-- View Layout Switcher -->
          <div class="flex items-center rounded-xl border border-[#232B3E] bg-[#121622] p-1 text-xs font-semibold">
            <button
              class="rounded-lg px-3 py-1.5 transition-all" :class="[
                displayLayout === 'list' ? 'bg-indigo-600 font-bold text-white' : 'text-slate-400 hover:text-slate-200',
              ]"
              @click="displayLayout = 'list'"
            >
              列表视图
            </button>
            <button
              class="rounded-lg px-3 py-1.5 transition-all" :class="[
                displayLayout === 'heatmap' ? 'bg-indigo-600 font-bold text-white' : 'text-slate-400 hover:text-slate-200',
              ]"
              @click="displayLayout = 'heatmap'"
            >
              热力卡片
            </button>
          </div>
        </div>
      </div>

      <!-- Empty State if no favorites -->
      <div
        v-if="filteredStocks.length === 0"
        class="my-auto flex flex-1 flex-col items-center justify-center rounded-2xl border border-[#1E2433] bg-[#0F131C] p-12 text-center"
      >
        <div class="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl border border-amber-500/20 bg-amber-500/10">
          <Star class="h-8 w-8 text-amber-400" />
        </div>
        <h3 class="mb-2 text-base font-bold text-white">暂无满足条件的关注股票</h3>
        <p class="mb-4 max-w-sm text-xs text-slate-400">您可以点击"全部标的"浏览其他股票，并点击 ⭐ 星号将感兴趣的股票加入关注列表。</p>
        <button
          class="rounded-xl bg-indigo-600 px-4 py-2 text-xs font-bold text-white transition-all hover:bg-indigo-500"
          @click="
            onlyFavorites = false;
            activeTab = 'all';
          "
        >
          查看全部标的
        </button>
      </div>

      <!-- Layout Mode 1: Comprehensive List View -->
      <div v-else-if="displayLayout === 'list'" class="overflow-hidden rounded-2xl border border-[#1E2433] bg-[#0F131C] shadow-xl">
        <div class="overflow-x-auto">
          <table class="w-full text-left text-xs">
            <thead class="border-b border-[#1E2433] bg-[#121622] font-mono text-[11px] text-slate-400 uppercase">
              <tr>
                <th class="px-3 py-3.5 text-center">移除</th>
                <th class="px-4 py-3.5">标的代码 / 名称</th>
                <th class="px-4 py-3.5">最新价格</th>
                <th class="px-4 py-3.5">24h涨跌</th>
                <th class="px-4 py-3.5">1D 涨幅</th>
                <th class="px-4 py-3.5">1W 涨幅</th>
                <th class="px-4 py-3.5">1M 涨幅</th>
                <th class="px-4 py-3.5">成交量</th>
                <th class="px-4 py-3.5">PE / 市值</th>
                <th class="px-4 py-3.5">RSI(14)</th>
                <th class="px-4 py-3.5">MACD 信号</th>
                <th class="px-4 py-3.5 text-right">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-[#1E2433] font-mono">
              <tr
                v-for="st in filteredStocks"
                :key="st.symbol"
                class="group cursor-pointer transition-colors hover:bg-[#161C2A]"
                @click="goToKline(st)"
              >
                <!-- Remove from Watchlist -->
                <td class="px-3 py-4 text-center" @click.stop="removeStock(st)">
                  <button
                    class="rounded-lg p-1 text-slate-500 transition-all hover:bg-rose-500/20 hover:text-rose-400"
                    title="点击移除自选"
                  >
                    <X class="h-4 w-4 transition-all" />
                  </button>
                </td>

                <!-- Symbol & Name -->
                <td class="px-4 py-4 font-sans">
                  <div class="flex items-center gap-2.5">
                    <div class="flex h-8 w-8 items-center justify-center rounded-lg border border-[#232B3E] bg-[#181F30] font-mono text-xs font-bold text-white transition-colors group-hover:border-indigo-500/50">
                      {{ st.symbol.slice(0, 2) }}
                    </div>
                    <div>
                      <div class="flex items-center gap-1.5 font-mono text-sm font-extrabold text-white">
                        <span>{{ st.symbol }}</span>
                        <span class="rounded border border-indigo-500/20 bg-indigo-500/10 px-1.5 py-0.5 text-[10px] font-normal text-indigo-400">
                          {{ st.sector.split('/')[0] }}
                        </span>
                      </div>
                      <div class="mt-0.5 text-[11px] text-slate-400">{{ st.name }}</div>
                    </div>
                  </div>
                </td>

                <!-- Price -->
                <td class="px-4 py-4 text-sm font-bold text-slate-100">${{ st.price.toFixed(2) }}</td>

                <!-- 24h Change -->
                <td class="px-4 py-4 font-bold" :class="[st.change >= 0 ? (colorMode === 'cn' ? 'text-rose-500' : 'text-emerald-400') : colorMode === 'cn' ? 'text-emerald-400' : 'text-rose-500']">
                  <div>{{ st.change >= 0 ? '+' : '' }}{{ st.change.toFixed(2) }}</div>
                  <div class="text-[10px] opacity-80">{{ st.changePercent >= 0 ? '+' : '' }}{{ st.changePercent }}%</div>
                </td>

                <!-- 1D Change -->
                <td class="px-4 py-4 font-bold" :class="changeClass(st.change1D)">{{ formatPercent(st.change1D) }}</td>

                <!-- 1W Change -->
                <td class="px-4 py-4 font-bold" :class="changeClass(st.change1W)">{{ formatPercent(st.change1W) }}</td>

                <!-- 1M Change -->
                <td class="px-4 py-4 font-bold" :class="changeClass(st.change1M)">{{ formatPercent(st.change1M) }}</td>

                <!-- Volume -->
                <td class="px-4 py-4 font-medium text-slate-300">{{ st.volume }}</td>

                <!-- PE / Market Cap -->
                <td class="px-4 py-4 text-slate-300">
                  <div class="font-semibold">{{ st.marketCap }}</div>
                  <div class="text-[10px] text-slate-500">{{ st.pe === null ? '--' : `${st.pe}x PE` }}</div>
                </td>

                <!-- RSI -->
                <td class="px-4 py-4">
                  <span class="rounded border px-2 py-0.5 text-[10px] font-bold" :class="rsiClass(st.rsi)">
                    {{ st.rsi === null ? '--' : st.rsi }}
                  </span>
                </td>

                <!-- MACD Signal -->
                <td class="px-4 py-4">
                  <span class="rounded border px-2 py-0.5 text-[10px] font-bold" :class="macdClass(st.macdSignal)">
                    {{ macdText(st.macdSignal) }}
                  </span>
                </td>

                <!-- Action Buttons -->
                <td class="px-4 py-4 text-right" @click.stop>
                  <div class="flex items-center justify-end gap-2">
                    <button
                      class="flex items-center gap-1 rounded-lg border border-indigo-500/30 bg-indigo-600/20 p-1.5 text-xs font-semibold text-indigo-400 transition-all hover:bg-indigo-600 hover:text-white"
                      title="查看K线与结构"
                      @click="goToKline(st)"
                    >
                      <BarChart2 class="h-3.5 w-3.5" />
                      <span>查看K线</span>
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Layout Mode 2: Heatmap Visual Cards -->
      <div v-else class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <div
          v-for="st in filteredStocks"
          :key="st.symbol"
          class="group relative flex h-52 cursor-pointer flex-col justify-between rounded-2xl border p-5 transition-all hover:scale-[1.02]" :class="[
            st.change >= 0
              ? colorMode === 'cn'
                ? 'bg-gradient-to-br from-[#1c1216] to-[#0F131C] border-rose-500/30 hover:border-rose-500'
                : 'bg-gradient-to-br from-[#102019] to-[#0F131C] border-emerald-500/30 hover:border-emerald-500'
              : colorMode === 'cn'
                ? 'bg-gradient-to-br from-[#102019] to-[#0F131C] border-emerald-500/30 hover:border-emerald-500'
                : 'bg-gradient-to-br from-[#1c1216] to-[#0F131C] border-rose-500/30 hover:border-rose-500',
          ]"
          @click="goToKline(st)"
        >
          <div class="flex items-start justify-between">
            <div class="flex items-center gap-2">
              <button class="rounded-lg p-1 text-slate-400 transition-all hover:bg-rose-500/20 hover:text-rose-400" title="点击移除自选" @click.stop="removeStock(st)">
                <X class="h-4 w-4" />
              </button>
              <div>
                <div class="font-mono text-base font-extrabold text-white">{{ st.symbol }}</div>
                <div class="text-xs text-slate-400">{{ st.name }}</div>
              </div>
            </div>
            <span
              class="rounded px-2 py-1 font-mono text-xs font-bold" :class="[
                st.change >= 0 ? (colorMode === 'cn' ? 'bg-rose-500/20 text-rose-400' : 'bg-emerald-500/20 text-emerald-400') : colorMode === 'cn' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-rose-500/20 text-rose-400',
              ]"
            >
              {{ st.changePercent >= 0 ? '+' : '' }}{{ st.changePercent }}%
            </span>
          </div>

          <div class="my-2 grid grid-cols-3 gap-2 border-y border-white/5 py-2 text-center font-mono text-xs">
            <div>
              <div class="text-[10px] text-slate-500">1D 涨幅</div>
              <div class="font-bold" :class="changeClass(st.change1D)">{{ formatPercent(st.change1D) }}</div>
            </div>
            <div>
              <div class="text-[10px] text-slate-500">1W 涨幅</div>
              <div class="font-bold" :class="changeClass(st.change1W)">{{ formatPercent(st.change1W) }}</div>
            </div>
            <div>
              <div class="text-[10px] text-slate-500">1M 涨幅</div>
              <div class="font-bold" :class="changeClass(st.change1M)">{{ formatPercent(st.change1M) }}</div>
            </div>
          </div>

          <div class="flex items-center justify-between font-mono text-xs">
            <span class="text-slate-400">市值: {{ st.marketCap }}</span>
            <span class="font-semibold text-indigo-400 transition-transform group-hover:translate-x-1">看K线 →</span>
          </div>
        </div>
      </div>
    </div>
  </Page>
</template>
