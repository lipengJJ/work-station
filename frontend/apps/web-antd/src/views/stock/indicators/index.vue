<script lang="ts" setup>
import { Page } from '@vben/common-ui';

import { Activity } from 'lucide-vue-next';

import { selectedStock as stock } from '../_shared/stock-state';

const indicators = [
  { name: 'RSI(14) 相对强弱指标', value: '68.4', status: '多头偏强', desc: '数值位于 60-70 强势多头区间，未触及 80 超买区，具备进一步拉升动能' },
  { name: 'MACD (12, 26, 9)', value: 'Bullish Cross', status: '金叉多头', desc: 'DIF 向上突破 DEA 形成金叉，柱状图(Hist)转正扩张' },
  { name: 'BOLL 20 布林带', value: '轨上发散', status: '突破中轨', desc: '股价运行于中轨与上轨之间，通道开口扩大，呈趋势性行情' },
  { name: 'MA5 / MA20 均线系统', value: '多头排列', status: '支撑强劲', desc: '5日均线呈陡峭上升角度，与20日均线形成强有力的多头支撑' },
];
</script>

<template>
  <Page :auto-content-height="true" content-class="!p-0">
    <div class="custom-scrollbar h-full space-y-6 overflow-y-auto bg-[#0B0E14] p-6 select-none">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="flex items-center gap-2 text-xl font-extrabold text-white">
            <Activity class="h-5 w-5 text-indigo-400" />
            <span>{{ stock.symbol }} - 量化技术指标图谱</span>
          </h1>
          <p class="mt-1 text-xs text-slate-400">多周期动能、均线聚散度与波动率诊断</p>
        </div>
      </div>

      <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div v-for="ind in indicators" :key="ind.name" class="space-y-3 rounded-2xl border border-[#1E2433] bg-[#0F131C] p-5">
          <div class="flex items-center justify-between border-b border-[#1E2433] pb-2">
            <span class="text-xs font-bold text-slate-200">{{ ind.name }}</span>
            <span class="rounded border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 font-mono text-xs font-bold text-emerald-400">
              {{ ind.status }}
            </span>
          </div>

          <div class="font-mono text-xl font-extrabold text-white">{{ ind.value }}</div>
          <p class="text-xs leading-relaxed text-slate-400">{{ ind.desc }}</p>
        </div>
      </div>
    </div>
  </Page>
</template>
