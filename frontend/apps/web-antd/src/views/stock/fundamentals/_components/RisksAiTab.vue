<script lang="ts" setup>
import type { FundamentalsApi } from '#/api/core/fundamentals';

import { ref, watch } from 'vue';

import { Tag } from 'ant-design-vue';
import MarkdownIt from 'markdown-it';

import {
  getFundamentalsCachedAiAnalysisApi,
  getFundamentalsRisksApi,
  postFundamentalsAiAnalysisApi,
} from '#/api/core/fundamentals';

import { NO_DATA_TEXT } from '../_shared/format';

const props = defineProps<{ symbol: string; refreshTick: number }>();

const md = new MarkdownIt({ breaks: true, linkify: true });

const loading = ref(false);
const errorMsg = ref('');
const risks = ref<FundamentalsApi.RisksData | null>(null);

const aiLoading = ref(false);
const aiError = ref('');
const aiAnalysis = ref<FundamentalsApi.AiAnalysisData | null>(null);
const aiHtml = ref('');

const LEVEL_COLOR: Record<string, string> = { high: 'error', medium: 'warning', low: 'success', unknown: 'default' };
const LEVEL_LABEL: Record<string, string> = { high: '高', medium: '中', low: '低', unknown: '数据不足' };

async function load() {
  loading.value = true;
  errorMsg.value = '';
  try {
    risks.value = (await getFundamentalsRisksApi(props.symbol)).data;
  } catch (e: any) {
    errorMsg.value = e.message || '加载失败';
  } finally {
    loading.value = false;
  }
}

async function loadCachedAi() {
  aiAnalysis.value = null;
  aiHtml.value = '';
  try {
    const cached = await getFundamentalsCachedAiAnalysisApi(props.symbol);
    if (cached) {
      aiAnalysis.value = cached.data;
      aiHtml.value = md.render(cached.data.markdown || '');
    }
  } catch {
    // 没有缓存就是 null/404，静默忽略，用户可以主动点生成
  }
}

async function generateAi() {
  aiLoading.value = true;
  aiError.value = '';
  try {
    const envelope = await postFundamentalsAiAnalysisApi(props.symbol);
    aiAnalysis.value = envelope.data;
    aiHtml.value = md.render(envelope.data.markdown || '');
  } catch (e: any) {
    aiError.value = e.message || 'AI 研判生成失败';
  } finally {
    aiLoading.value = false;
  }
}

watch(
  () => [props.symbol, props.refreshTick],
  () => {
    load();
    loadCachedAi();
  },
  { immediate: true },
);
</script>

<template>
  <div class="space-y-4">
    <!-- 风险项 -->
    <div>
      <h3 class="mb-2 text-xs font-bold text-[hsl(var(--muted-foreground))]">结构化风险扫描</h3>
      <div v-if="loading" class="py-8 text-center text-xs text-[hsl(var(--muted-foreground))]">正在加载风险数据…</div>
      <div v-else-if="errorMsg" class="py-8 text-center text-xs text-destructive">{{ errorMsg }}</div>
      <div v-else-if="!risks" class="py-8 text-center text-xs text-[hsl(var(--muted-foreground))]">{{ NO_DATA_TEXT }}</div>
      <div v-else class="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        <div v-for="item in risks.items" :key="item.key" class="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-3">
          <div class="mb-1 flex items-center justify-between">
            <span class="text-xs font-bold text-[hsl(var(--foreground))]">{{ item.title }}</span>
            <Tag :color="LEVEL_COLOR[item.level]">{{ LEVEL_LABEL[item.level] }}</Tag>
          </div>
          <p class="text-[11px] leading-relaxed text-[hsl(var(--muted-foreground))]">{{ item.trigger }}</p>
          <div v-if="item.data_used" class="mt-1.5 space-y-0.5 text-[10px] text-[hsl(var(--muted-foreground))]">
            <div>数据: {{ item.data_used }}</div>
            <div v-if="item.source">来源: {{ item.source }}</div>
            <div v-if="item.invalidation">失效条件: {{ item.invalidation }}</div>
          </div>
          <div v-else-if="item.needs_data_source" class="mt-1.5 text-[10px] text-warning">需要: {{ item.needs_data_source }}</div>
        </div>
      </div>
    </div>

    <!-- AI 综合研判 -->
    <div class="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-4">
      <div class="mb-3 flex items-center justify-between">
        <h3 class="text-xs font-bold text-[hsl(var(--muted-foreground))]">AI 综合研判</h3>
        <button
          class="rounded-lg bg-primary px-3 py-1.5 text-xs font-bold text-white hover:bg-primary disabled:opacity-50"
          :disabled="aiLoading"
          @click="generateAi"
        >
          {{ aiLoading ? '生成中…' : aiAnalysis ? '重新生成' : '生成 AI 研判' }}
        </button>
      </div>

      <div v-if="aiError" class="mb-3 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
        {{ aiError }}
      </div>

      <div v-if="!aiAnalysis && !aiLoading" class="py-8 text-center text-xs text-[hsl(var(--muted-foreground))]">
        点击"生成 AI 研判"，基于上面已经拉到的真实财务/估值/预期/风险数据做综合整理，不会凭空编数据。
      </div>
      <div v-else-if="aiLoading" class="py-8 text-center text-xs text-[hsl(var(--muted-foreground))]">正在生成，可能需要十几秒…</div>
      <!-- eslint-disable-next-line vue/no-v-html -- markdown-it 默认 html:false，裸 HTML 会被转义，和 xhs AI 分析页同一种用法 -->
      <div v-else class="fundamentals-ai-markdown text-xs leading-relaxed text-[hsl(var(--muted-foreground))]" v-html="aiHtml"></div>
    </div>
  </div>
</template>

<style scoped>
.fundamentals-ai-markdown :deep(h2) {
  margin-top: 16px;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 800;
  color: #fff;
}
.fundamentals-ai-markdown :deep(p) {
  margin-bottom: 8px;
}
.fundamentals-ai-markdown :deep(ul) {
  padding-left: 18px;
  list-style: disc;
  margin-bottom: 8px;
}
.fundamentals-ai-markdown :deep(strong) {
  color: #fff;
}
</style>
