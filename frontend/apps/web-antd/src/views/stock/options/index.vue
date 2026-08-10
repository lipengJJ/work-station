<script lang="ts" setup>
import { Page } from '@vben/common-ui';

import { Layers } from 'lucide-vue-next';

import { selectedStock as stock } from '../_shared/stock-state';
</script>

<template>
  <Page :auto-content-height="true" content-class="!p-0">
    <div class="custom-scrollbar h-full space-y-6 overflow-y-auto bg-[#0B0E14] p-6 select-none">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="flex items-center gap-2 text-xl font-extrabold text-white">
            <Layers class="h-5 w-5 text-indigo-400" />
            <span>{{ stock.symbol }} - 期权链与隐含波动率 (Options Chain)</span>
          </h1>
          <p class="mt-1 text-xs text-slate-400">认购(Call)与认沽(Put)行权价、IV、Delta分布</p>
        </div>
      </div>

      <div class="overflow-hidden rounded-2xl border border-[#1E2433] bg-[#0F131C]">
        <div class="overflow-x-auto">
          <table class="w-full text-left font-mono text-xs">
            <thead class="border-b border-[#1E2433] bg-[#121622] text-[11px] text-slate-400">
              <tr>
                <th class="bg-indigo-950/30 px-4 py-3 text-center text-indigo-300" colspan="4">认购期权 (Call)</th>
                <th class="bg-[#1A2233] px-4 py-3 text-center text-white">行权价 (Strike)</th>
                <th class="bg-rose-950/30 px-4 py-3 text-center text-rose-300" colspan="4">认沽期权 (Put)</th>
              </tr>
              <tr class="border-t border-[#1E2433] text-[10px]">
                <th class="px-3 py-2">最新价</th>
                <th class="px-3 py-2">IV</th>
                <th class="px-3 py-2">持仓量</th>
                <th class="px-3 py-2">Delta</th>
                <th class="px-3 py-2 text-center text-amber-400">$</th>
                <th class="px-3 py-2">最新价</th>
                <th class="px-3 py-2">IV</th>
                <th class="px-3 py-2">持仓量</th>
                <th class="px-3 py-2">Delta</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-[#1E2433]">
              <tr v-for="op in stock.optionsChain" :key="op.strike" class="hover:bg-[#161C2A]" :class="op.strike === 140 ? 'bg-indigo-950/20' : ''">
                <td class="px-3 py-3 font-bold text-emerald-400">${{ op.callPrice }}</td>
                <td class="px-3 py-3 text-slate-300">{{ op.callIV }}%</td>
                <td class="px-3 py-3 text-slate-400">{{ op.callOI }}</td>
                <td class="px-3 py-3 text-indigo-400">{{ op.callDelta }}</td>
                <td class="bg-[#121622] px-3 py-3 text-center font-bold text-white">${{ op.strike }}</td>
                <td class="px-3 py-3 font-bold text-rose-400">${{ op.putPrice }}</td>
                <td class="px-3 py-3 text-slate-300">{{ op.putIV }}%</td>
                <td class="px-3 py-3 text-slate-400">{{ op.putOI }}</td>
                <td class="px-3 py-3 text-rose-400">{{ op.putDelta }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </Page>
</template>
