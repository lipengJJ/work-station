<script lang="ts" setup>
import { Page } from '@vben/common-ui';

import { FileText, Sparkles } from 'lucide-vue-next';

import { selectedStock as stock } from '../_shared/stock-state';
</script>

<template>
  <Page :auto-content-height="true" content-class="!p-0">
    <div class="custom-scrollbar h-full space-y-6 overflow-y-auto bg-[#0B0E14] p-6 select-none">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="flex items-center gap-2 text-xl font-extrabold text-white">
            <FileText class="h-5 w-5 text-indigo-400" />
            <span>{{ stock.symbol }} - AI 机构深度投研报告</span>
          </h1>
          <p class="mt-1 text-xs text-slate-400">DeepSeek Quant Agent 多维度深度逻辑拆解</p>
        </div>

        <span class="rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 px-3 py-1 text-xs font-bold text-slate-950 shadow-lg">
          评级: 强力推荐买入 (STRONG BUY)
        </span>
      </div>

      <div class="space-y-4 rounded-2xl border border-[#1E2433] bg-[#0F131C] p-6">
        <div class="flex items-center gap-2 text-sm font-bold text-indigo-400">
          <Sparkles class="h-4 w-4" />
          <span>核心投资逻辑 (Investment Thesis)</span>
        </div>
        <p class="text-xs leading-relaxed text-slate-300">
          1. 行业垄断地位：标的作为行业龙头，在智能算力与关键供应链领域拥有超过 85% 的定价权与全球客户粘性。<br />
          2. 财务盈利强劲：毛利率稳定在 70% 以上，自由现金流增长强劲，支撑未来长期估值扩张。<br />
          3. 筹码集中度：机构重仓占比超 68%，近期短线调整消化了期权高 IV 溢价，形成强有力的技术性二次起飞点。
        </p>
      </div>
    </div>
  </Page>
</template>
