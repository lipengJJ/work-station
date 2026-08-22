<script lang="ts" setup>
import { computed } from 'vue';

import { Page } from '@vben/common-ui';

import { Activity } from 'lucide-vue-next';

import IndicatorCards from '../_shared/IndicatorCards.vue';
import { selectedStock } from '../_shared/stock-state';

const stock = computed(() => selectedStock.value);
</script>

<template>
  <Page :auto-content-height="true" content-class="!p-0">
    <div class="custom-scrollbar h-full space-y-6 overflow-y-auto bg-[hsl(var(--background-deep))] p-6 select-none">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="flex items-center gap-2 text-xl font-extrabold text-[hsl(var(--foreground))]">
            <Activity class="h-5 w-5 text-primary" />
            <span>{{ stock?.symbol || '--' }} - 量化技术指标图谱</span>
          </h1>
          <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">基于真实日K数据实时计算：动能、均线系统与波动率诊断</p>
        </div>
      </div>

      <div v-if="!stock" class="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-12 text-center text-xs text-[hsl(var(--muted-foreground))]">
        未选择股票 — 请先到「自选股」页选择一只股票
      </div>
      <IndicatorCards v-else :symbol="stock.symbol" />
    </div>
  </Page>
</template>
