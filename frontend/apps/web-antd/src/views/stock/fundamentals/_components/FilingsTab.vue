<script lang="ts" setup>
import type { FundamentalsApi } from '#/api/core/fundamentals';

import { computed, ref, watch } from 'vue';

import { Table, Tag } from 'ant-design-vue';

import { getFundamentalsFilingsApi } from '#/api/core/fundamentals';

import { formatDate, NO_DATA_TEXT } from '../_shared/format';

const props = defineProps<{ symbol: string; refreshTick: number }>();

const loading = ref(false);
const errorMsg = ref('');
const data = ref<FundamentalsApi.FilingsData | null>(null);
const activeCategory = ref<string>('全部');

async function load() {
  loading.value = true;
  errorMsg.value = '';
  activeCategory.value = '全部';
  try {
    const envelope = await getFundamentalsFilingsApi(props.symbol);
    data.value = envelope.data;
  } catch (e: any) {
    errorMsg.value = e.message || '加载失败';
  } finally {
    loading.value = false;
  }
}
watch(() => [props.symbol, props.refreshTick], load, { immediate: true });

const categories = computed(() => {
  if (!data.value) return [];
  return ['全部', ...Object.keys(data.value.grouped).sort((a, b) => data.value!.grouped[b]! - data.value!.grouped[a]!)];
});

const filteredFilings = computed(() => {
  if (!data.value) return [];
  if (activeCategory.value === '全部') return data.value.filings;
  return data.value.filings.filter((f) => f.category === activeCategory.value);
});

const columns = [
  { title: '类型', dataIndex: 'form', key: 'form', width: 90, sorter: (a: FundamentalsApi.Filing, b: FundamentalsApi.Filing) => a.form.localeCompare(b.form) },
  { title: '披露时间', dataIndex: 'filed_at', key: 'filed_at', width: 110, sorter: (a: FundamentalsApi.Filing, b: FundamentalsApi.Filing) => (a.filed_at || '').localeCompare(b.filed_at || ''), defaultSortOrder: 'descend' as const },
  { title: '财务期间', dataIndex: 'financial_period', key: 'financial_period', width: 110 },
  { title: '事件分类 / 说明', dataIndex: 'event_categories', key: 'event_categories' },
  { title: '修订', dataIndex: 'is_amendment', key: 'is_amendment', width: 70 },
  { title: '原文', dataIndex: 'url', key: 'url', width: 90 },
];
</script>

<template>
  <div v-if="loading" class="py-12 text-center text-xs text-slate-500">正在加载 SEC 披露文件…</div>
  <div v-else-if="errorMsg" class="py-12 text-center text-xs text-rose-400">{{ errorMsg }}</div>
  <div v-else-if="!data" class="py-12 text-center text-xs text-slate-500">{{ NO_DATA_TEXT }}</div>
  <div v-else class="space-y-3">
    <div class="flex flex-wrap gap-1.5">
      <button
        v-for="c in categories" :key="c"
        class="rounded-lg border px-2.5 py-1 text-[11px] font-semibold" :class="activeCategory === c ? 'border-indigo-500 bg-indigo-600 text-white' : 'border-[#232B3E] bg-[#121622] text-slate-400 hover:text-slate-200'"
        @click="activeCategory = c"
      >
        {{ c }} <span v-if="c !== '全部'" class="opacity-70">({{ data.grouped[c] }})</span>
      </button>
    </div>

    <div class="overflow-hidden rounded-2xl border border-[#1E2433] bg-[#0F131C]">
      <Table :columns="columns" :data-source="filteredFilings" :pagination="{ pageSize: 20 }" row-key="accession_number" size="small">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'filed_at'">{{ formatDate(record.filed_at) }}</template>
          <template v-else-if="column.key === 'financial_period'">{{ formatDate(record.financial_period) }}</template>
          <template v-else-if="column.key === 'event_categories'">
            <div class="flex flex-wrap gap-1">
              <Tag v-for="c in record.event_categories" :key="c" :color="record.is_material ? 'error' : 'default'">{{ c }}</Tag>
              <span v-if="!record.event_categories?.length" class="text-slate-500">{{ record.description || '--' }}</span>
            </div>
          </template>
          <template v-else-if="column.key === 'is_amendment'">
            <Tag v-if="record.is_amendment" color="warning">修订</Tag>
          </template>
          <template v-else-if="column.key === 'url'">
            <a v-if="record.url" :href="record.url" target="_blank" rel="noopener noreferrer" class="text-indigo-400 underline">查看原文</a>
            <a v-else :href="record.index_url" target="_blank" rel="noopener noreferrer" class="text-indigo-400 underline">查看目录</a>
          </template>
        </template>
      </Table>
    </div>
  </div>
</template>
