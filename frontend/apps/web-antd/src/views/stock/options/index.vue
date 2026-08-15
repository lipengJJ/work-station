<script lang="ts" setup>
import { computed } from 'vue';

import { Page } from '@vben/common-ui';

import { Layers } from 'lucide-vue-next';

import { selectedStock } from '../_shared/stock-state';

const stock = computed(() => selectedStock.value);
</script>

<template>
  <Page :auto-content-height="true" content-class="!p-0">
    <div class="custom-scrollbar h-full space-y-6 overflow-y-auto bg-[hsl(var(--background-deep))] p-6 select-none">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="flex items-center gap-2 text-xl font-extrabold text-[hsl(var(--foreground))]">
            <Layers class="h-5 w-5 text-indigo-400" />
            <span>{{ stock?.symbol || '--' }} - 期权链与隐含波动率 (Options Chain)</span>
          </h1>
          <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">认购(Call)与认沽(Put)行权价、IV、Delta分布</p>
        </div>
      </div>

      <div class="flex flex-col items-center justify-center rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-16 text-center">
        <div class="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-indigo-500/20 bg-indigo-500/10">
          <Layers class="h-7 w-7 text-indigo-400" />
        </div>
        <h3 class="mb-2 text-sm font-bold text-[hsl(var(--foreground))]">期权数据暂未接入</h3>
        <p class="max-w-md text-xs leading-relaxed text-[hsl(var(--muted-foreground))]">
          当前数据源（yfinance 免费接口）不提供期权链数据。期权链需要付费数据源（如 Polygon / 券商 API），
          接入后这里将展示各行权价的 Call/Put 最新价、隐含波动率 IV、持仓量与 Delta。
        </p>
      </div>
    </div>
  </Page>
</template>
