<script lang="ts" setup>
import type { StockItem } from '../_shared/types';

import { computed, onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import { message } from 'ant-design-vue';
import { BarChart2, Plus, Star, X } from 'lucide-vue-next';

import { addStockToWatchlistApi, getStockWatchlistApi, removeStockFromWatchlistApi } from '#/api/core/stock';

import KlineViewer from './_components/KlineViewer.vue';
import { selectStock, stocks } from '../_shared/stock-state';

// 固定红涨绿跌（参考项目原来的切换开关在被丢弃的顶部栏里，这次不做那个开关）
const colorMode = 'cn' as const;

const activeTab = ref<'all' | 'ai' | 'china'>('all');
const displayLayout = ref<'heatmap' | 'list'>('list');

// K线抽屉：点击「查看K线」在当前页打开，不再跳转独立的行情与K线页面
const klineDrawerOpen = ref(false);
const klineDrawerStock = ref<StockItem | null>(null);

// 自选股都是"关注"的标的，不再有本地 mock 星标收藏的概念
const watchlistCount = computed(() => stocks.value.length);

// 真实自选股数据（后端 /api/stock/watchlist）没有 tags/isFavorite 这类 mock 字段，
// 分类过滤基于真实的 sector 字段
const filteredStocks = computed(() => {
  return stocks.value.filter((st) => {
    const sector = st.sector || '';
    if (activeTab.value === 'ai') {
      return (
        sector.includes('AI') ||
        sector.includes('芯片') ||
        sector.includes('半导体') ||
        sector.includes('Technology')
      );
    }
    if (activeTab.value === 'china') return sector.includes('中国');
    return true;
  });
});

function goToKline(st: StockItem) {
  selectStock(st);
  klineDrawerStock.value = st;
  klineDrawerOpen.value = true;
}

// 涨跌类字段：真实数据可能缺失（1W/1M 是 null，RSI/MACD 暂未提供），一律显示 "--"、
// 用中性灰色，不当成 0 处理
function changeClass(v: null | number | undefined) {
  if (v === null || v === undefined) return 'text-[hsl(var(--muted-foreground))]';
  return v >= 0 ? (colorMode === 'cn' ? 'text-rose-500' : 'text-emerald-400') : colorMode === 'cn' ? 'text-emerald-400' : 'text-rose-500';
}
function formatPercent(v: null | number | undefined) {
  if (v === null || v === undefined) return '--';
  return `${v >= 0 ? '+' : ''}${v}%`;
}
function rsiClass(v: null | number | undefined) {
  if (v === null || v === undefined) return 'border-slate-700 bg-slate-800 text-[hsl(var(--muted-foreground))]';
  if (v > 65) return 'border-rose-500/20 bg-rose-500/10 text-rose-400';
  if (v < 40) return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400';
  return 'border-slate-700 bg-slate-800 text-[hsl(var(--muted-foreground))]';
}
function macdClass(sig: StockItem['macdSignal']) {
  if (sig === 'Bullish Cross') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400';
  if (sig === 'Bearish Cross') return 'border-rose-500/30 bg-rose-500/10 text-rose-400';
  return 'border-slate-700 bg-slate-800 text-[hsl(var(--muted-foreground))]';
}
function macdText(sig: StockItem['macdSignal']) {
  if (sig === 'Bullish Cross') return '金叉多头';
  if (sig === 'Bearish Cross') return '死叉空头';
  if (sig === 'Neutral') return '震荡整理';
  return '--';
}

// ------------------------------------------------------- yfinance 真实数据 ----

const loadError = ref('');
const watchlistLoading = ref(false);

async function loadRealWatchlist() {
  watchlistLoading.value = true;
  loadError.value = '';
  try {
    stocks.value = await getStockWatchlistApi();
  } catch (e: any) {
    loadError.value = e.message || '获取自选股失败';
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
    <div class="custom-scrollbar flex h-full flex-1 flex-col overflow-y-auto bg-[hsl(var(--background-deep))] p-6 select-none">
      <!-- yfinance 真实数据配置状态提示 -->
      <div
        v-if="loadError"
        class="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-xs text-rose-300"
      >
        <span>获取自选股数据失败：{{ loadError }}</span>
        <button class="rounded-lg bg-rose-500/20 px-3 py-1 font-bold hover:bg-rose-500/30" @click="loadRealWatchlist">
          重试
        </button>
      </div>
      <div v-if="watchlistLoading" class="mb-4 text-xs text-[hsl(var(--muted-foreground))]">正在获取自选股数据…</div>

      <!-- 添加自选股代码 -->
      <div class="mb-4 flex flex-wrap items-center gap-2">
        <input
          v-model="newSymbol"
          placeholder="输入股票代码，例如 NVDA"
          class="w-48 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-1.5 text-xs text-[hsl(var(--foreground))] outline-none focus:border-indigo-500"
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
          <h1 class="flex items-center gap-2 text-xl font-extrabold text-[hsl(var(--foreground))]">
            <Star class="h-5 w-5 fill-amber-400 text-amber-400" />
            <span>自选股 · 关注的股票</span>
            <span class="rounded-full border border-amber-500/30 bg-amber-500/20 px-2 py-0.5 font-mono text-xs text-amber-300">
              共 {{ watchlistCount }} 支
            </span>
          </h1>
          <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">只专注核心自选标的，实时监控最新价格、1D / 1W / 1M 涨跌幅与量化信号</p>
        </div>

        <div class="flex flex-wrap items-center gap-3">
          <!-- Category Filters -->
          <div class="flex items-center rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-1 text-xs font-semibold">
            <button
              class="rounded-lg px-3 py-1.5 transition-all" :class="[
                activeTab === 'all' ? 'bg-indigo-600 font-bold text-white' : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]',
              ]"
              @click="activeTab = 'all'"
            >
              全部标的
            </button>
            <button
              class="rounded-lg px-3 py-1.5 transition-all" :class="[
                activeTab === 'ai' ? 'bg-indigo-600 font-bold text-white' : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]',
              ]"
              @click="activeTab = 'ai'"
            >
              AI/半导体
            </button>
            <button
              class="rounded-lg px-3 py-1.5 transition-all" :class="[
                activeTab === 'china' ? 'bg-indigo-600 font-bold text-white' : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]',
              ]"
              @click="activeTab = 'china'"
            >
              中概资产
            </button>
          </div>

          <!-- View Layout Switcher -->
          <div class="flex items-center rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-1 text-xs font-semibold">
            <button
              class="rounded-lg px-3 py-1.5 transition-all" :class="[
                displayLayout === 'list' ? 'bg-indigo-600 font-bold text-white' : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]',
              ]"
              @click="displayLayout = 'list'"
            >
              列表视图
            </button>
            <button
              class="rounded-lg px-3 py-1.5 transition-all" :class="[
                displayLayout === 'heatmap' ? 'bg-indigo-600 font-bold text-white' : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]',
              ]"
              @click="displayLayout = 'heatmap'"
            >
              热力卡片
            </button>
          </div>
        </div>
      </div>

      <!-- Empty State if no stocks -->
      <div
        v-if="filteredStocks.length === 0"
        class="my-auto flex flex-1 flex-col items-center justify-center rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-12 text-center"
      >
        <div class="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl border border-amber-500/20 bg-amber-500/10">
          <Star class="h-8 w-8 text-amber-400" />
        </div>
        <h3 class="mb-2 text-base font-bold text-[hsl(var(--foreground))]">暂无自选股</h3>
        <p class="mb-4 max-w-sm text-xs text-[hsl(var(--muted-foreground))]">在上方输入股票代码（如 NVDA）添加自选，添加后即可查看真实行情并跳转 K 线分析。</p>
      </div>

      <!-- Layout Mode 1: Comprehensive List View -->
      <div v-else-if="displayLayout === 'list'" class="overflow-hidden rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] shadow-xl">
        <div class="overflow-x-auto">
          <table class="wl-table w-full text-left text-xs">
            <thead class="border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] font-mono text-[11px] text-[hsl(var(--muted-foreground))] uppercase">
              <tr>
                <th class="px-3 py-3.5 text-center">移除</th>
                <th class="px-4 py-3.5">标的代码 / 名称</th>
                <th class="px-4 py-3.5">最新价格</th>
                <th class="px-4 py-3.5">24h涨跌</th>
                <th class="col-d1 px-4 py-3.5">1D 涨幅</th>
                <th class="col-w px-4 py-3.5">1W 涨幅</th>
                <th class="col-m px-4 py-3.5">1M 涨幅</th>
                <th class="col-vol px-4 py-3.5">成交量</th>
                <th class="col-pe px-4 py-3.5">PE / 市值</th>
                <th class="col-rsi px-4 py-3.5">RSI(14)</th>
                <th class="col-macd px-4 py-3.5">MACD 信号</th>
                <th class="px-4 py-3.5 text-right">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-[hsl(var(--border))] font-mono">
              <tr
                v-for="st in filteredStocks"
                :key="st.symbol"
                class="group cursor-pointer transition-colors hover:bg-[hsl(var(--accent))]"
                @click="goToKline(st)"
              >
                <!-- Remove from Watchlist -->
                <td class="px-3 py-4 text-center" @click.stop="removeStock(st)">
                  <button
                    class="rounded-lg p-1 text-[hsl(var(--muted-foreground))] transition-all hover:bg-rose-500/20 hover:text-rose-400"
                    title="点击移除自选"
                  >
                    <X class="h-4 w-4 transition-all" />
                  </button>
                </td>

                <!-- Symbol & Name -->
                <td class="px-4 py-4 font-sans">
                  <div class="flex items-center gap-2.5">
                    <div class="flex h-8 w-8 items-center justify-center rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--muted))] font-mono text-xs font-bold text-[hsl(var(--foreground))] transition-colors group-hover:border-indigo-500/50">
                      {{ st.symbol.slice(0, 2) }}
                    </div>
                    <div>
                      <div class="flex items-center gap-1.5 font-mono text-sm font-extrabold text-[hsl(var(--foreground))]">
                        <span>{{ st.symbol }}</span>
                        <span class="wl-sector-tag rounded border border-indigo-500/20 bg-indigo-500/10 px-1.5 py-0.5 text-[10px] font-normal text-indigo-400">
                          {{ (st.sector || '--').split('/')[0] }}
                        </span>
                      </div>
                      <div class="mt-0.5 text-[11px] text-[hsl(var(--muted-foreground))]">{{ st.name }}</div>
                    </div>
                  </div>
                </td>

                <!-- Price -->
                <td class="px-4 py-4 text-sm font-bold text-slate-100">${{ st.price.toFixed(2) }}</td>

                <!-- 24h Change -->
                <td class="px-4 py-4 font-bold" :class="[st.change >= 0 ? (colorMode === 'cn' ? 'text-rose-500' : 'text-emerald-400') : colorMode === 'cn' ? 'text-emerald-400' : 'text-rose-500']">
                  <div class="wl-chg-value">{{ st.change >= 0 ? '+' : '' }}{{ st.change.toFixed(2) }}</div>
                  <div class="text-[10px] opacity-80">{{ st.changePercent >= 0 ? '+' : '' }}{{ st.changePercent }}%</div>
                </td>

                <!-- 1D Change -->
                <td class="col-d1 px-4 py-4 font-bold" :class="changeClass(st.change1D)">{{ formatPercent(st.change1D ?? null) }}</td>

                <!-- 1W Change -->
                <td class="col-w px-4 py-4 font-bold" :class="changeClass(st.change1W)">{{ formatPercent(st.change1W) }}</td>

                <!-- 1M Change -->
                <td class="col-m px-4 py-4 font-bold" :class="changeClass(st.change1M)">{{ formatPercent(st.change1M) }}</td>

                <!-- Volume -->
                <td class="col-vol px-4 py-4 font-medium text-[hsl(var(--muted-foreground))]">{{ st.volume }}</td>

                <!-- PE / Market Cap -->
                <td class="col-pe px-4 py-4 text-[hsl(var(--muted-foreground))]">
                  <div class="font-semibold">{{ st.marketCap }}</div>
                  <div class="text-[10px] text-[hsl(var(--muted-foreground))]">{{ st.pe === null ? '--' : `${st.pe}x PE` }}</div>
                </td>

                <!-- RSI -->
                <td class="col-rsi px-4 py-4">
                  <span class="rounded border px-2 py-0.5 text-[10px] font-bold" :class="rsiClass(st.rsi)">
                    {{ st.rsi ?? '--' }}
                  </span>
                </td>

                <!-- MACD Signal -->
                <td class="col-macd px-4 py-4">
                  <span class="rounded border px-2 py-0.5 text-[10px] font-bold" :class="macdClass(st.macdSignal)">
                    {{ macdText(st.macdSignal) }}
                  </span>
                </td>

                <!-- Action Buttons -->
                <td class="px-4 py-4 text-right" @click.stop>
                  <div class="flex items-center justify-end gap-2">
                    <button
                      class="wl-action-btn flex items-center gap-1 rounded-lg border border-indigo-500/30 bg-indigo-600/20 p-1.5 text-xs font-semibold text-indigo-400 transition-all hover:bg-indigo-600 hover:text-white"
                      title="查看K线与结构"
                      @click="goToKline(st)"
                    >
                      <BarChart2 class="h-3.5 w-3.5" />
                      <span class="wl-action-text">查看K线</span>
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
                ? 'bg-gradient-to-br from-[#1c1216] to-[hsl(var(--card))] border-rose-500/30 hover:border-rose-500'
                : 'bg-gradient-to-br from-[#102019] to-[hsl(var(--card))] border-emerald-500/30 hover:border-emerald-500'
              : colorMode === 'cn'
                ? 'bg-gradient-to-br from-[#102019] to-[hsl(var(--card))] border-emerald-500/30 hover:border-emerald-500'
                : 'bg-gradient-to-br from-[#1c1216] to-[hsl(var(--card))] border-rose-500/30 hover:border-rose-500',
          ]"
          @click="goToKline(st)"
        >
          <div class="flex items-start justify-between">
            <div class="flex items-center gap-2">
              <button class="rounded-lg p-1 text-[hsl(var(--muted-foreground))] transition-all hover:bg-rose-500/20 hover:text-rose-400" title="点击移除自选" @click.stop="removeStock(st)">
                <X class="h-4 w-4" />
              </button>
              <div>
                <div class="font-mono text-base font-extrabold text-[hsl(var(--foreground))]">{{ st.symbol }}</div>
                <div class="text-xs text-[hsl(var(--muted-foreground))]">{{ st.name }}</div>
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
              <div class="text-[10px] text-[hsl(var(--muted-foreground))]">1D 涨幅</div>
              <div class="font-bold" :class="changeClass(st.change1D)">{{ formatPercent(st.change1D ?? null) }}</div>
            </div>
            <div>
              <div class="text-[10px] text-[hsl(var(--muted-foreground))]">1W 涨幅</div>
              <div class="font-bold" :class="changeClass(st.change1W)">{{ formatPercent(st.change1W) }}</div>
            </div>
            <div>
              <div class="text-[10px] text-[hsl(var(--muted-foreground))]">1M 涨幅</div>
              <div class="font-bold" :class="changeClass(st.change1M)">{{ formatPercent(st.change1M) }}</div>
            </div>
          </div>

          <div class="flex items-center justify-between font-mono text-xs">
            <span class="text-[hsl(var(--muted-foreground))]">市值: {{ st.marketCap }}</span>
            <span class="font-semibold text-indigo-400 transition-transform group-hover:translate-x-1">看K线 →</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 当前页内查看K线（抽屉，不跳转独立页面） -->
    <KlineViewer v-model:open="klineDrawerOpen" :stock="klineDrawerStock" />
  </Page>
</template>

<style scoped>
/* 移动端渐进披露：手机只保留核心 5 列（移除/代码/价格/24h涨跌/操作），
   次要列（1D/1W/1M/成交量/PE/RSI/MACD）在 <768px 隐藏，桌面完整显示。
   想看完整指标点进 K 线详情页。 */
@media (max-width: 767px) {
  .col-d1,
  .col-w,
  .col-m,
  .col-vol,
  .col-pe,
  .col-rsi,
  .col-macd {
    display: none;
  }
  /* 手机端密度压缩：板块 tag 隐藏、单元格内边距收紧、操作按钮只留图标 */
  .wl-sector-tag {
    display: none !important;
  }
  .wl-table th,
  .wl-table td {
    padding-left: 8px !important;
    padding-right: 8px !important;
  }
  .wl-action-text {
    display: none !important;
  }
  .wl-action-btn {
    padding: 6px !important;
  }
  /* 24h 涨跌两行信息在手机上改为单行（百分比为主） */
  .wl-chg-value {
    display: none;
  }
}
</style>
