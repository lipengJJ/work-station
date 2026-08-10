<script lang="ts" setup>
import type { FundamentalsApi } from '#/api/core/fundamentals';

import { computed, ref, watch } from 'vue';

import { useRouter } from 'vue-router';

import { Alert, Table, Tag } from 'ant-design-vue';

import { getFundamentalsInsidersApi, getFundamentalsInstitutionsApi } from '#/api/core/fundamentals';

import { formatCompactUsd, formatDate, formatUsdPerShare, NO_DATA_TEXT } from '../_shared/format';

const props = defineProps<{ symbol: string; refreshTick: number }>();
const router = useRouter();

const loading = ref(false);
const errorMsg = ref('');
const institutions = ref<FundamentalsApi.InstitutionsData | null>(null);
const insiders = ref<FundamentalsApi.InsidersData | null>(null);

async function load() {
  loading.value = true;
  errorMsg.value = '';
  try {
    const [instEnv, insEnv] = await Promise.all([
      getFundamentalsInstitutionsApi(props.symbol),
      getFundamentalsInsidersApi(props.symbol),
    ]);
    institutions.value = instEnv.data;
    insiders.value = insEnv.data;
  } catch (e: any) {
    errorMsg.value = e.message || '加载失败';
  } finally {
    loading.value = false;
  }
}
watch(() => [props.symbol, props.refreshTick], load, { immediate: true });

interface FlatTransaction extends FundamentalsApi.InsiderTransaction {
  owner_name: string | null;
  officer_title: string | null;
  filed_at: string;
  index_url: string;
}

const flatTransactions = computed<FlatTransaction[]>(() => {
  if (!insiders.value) return [];
  return insiders.value.transactions.flatMap((filing) =>
    filing.transactions.map((t) => ({
      ...t,
      owner_name: filing.owner_name,
      officer_title: filing.officer_title || (filing.is_director ? '董事' : filing.is_ten_percent_owner ? '10%以上股东' : null),
      filed_at: filing.filed_at,
      index_url: filing.index_url,
    })),
  );
});

const insiderColumns = [
  { title: '姓名/职位', dataIndex: 'owner_name', key: 'owner_name' },
  { title: '披露日期', dataIndex: 'filed_at', key: 'filed_at', width: 100 },
  { title: '交易日期', dataIndex: 'transaction_date', key: 'transaction_date', width: 100 },
  { title: '类型', dataIndex: 'category', key: 'category', width: 110 },
  { title: '股数', dataIndex: 'shares', key: 'shares' },
  { title: '价格', dataIndex: 'price_per_share', key: 'price_per_share' },
  { title: '交易金额', dataIndex: 'amount', key: 'amount' },
  { title: '交易后持股', dataIndex: 'shares_owned_after', key: 'shares_owned_after' },
  { title: '原文', dataIndex: 'index_url', key: 'index_url', width: 70 },
];

const institutionColumns = [
  { title: '机构名称', dataIndex: 'institution', key: 'institution' },
  { title: '报告季度', dataIndex: 'report_period', key: 'report_period' },
  { title: '持股数量', dataIndex: 'shares', key: 'shares' },
  { title: '持股变化', dataIndex: 'shares_change', key: 'shares_change' },
  { title: '持仓市值', dataIndex: 'market_value', key: 'market_value' },
];

function goToApiConfig() {
  router.push('/settings/api-config');
}
</script>

<template>
  <div v-if="loading" class="py-12 text-center text-xs text-slate-500">正在加载机构与内部人数据…</div>
  <div v-else-if="errorMsg" class="py-12 text-center text-xs text-rose-400">{{ errorMsg }}</div>
  <div v-else class="space-y-4">
    <!-- 13F 机构持仓 -->
    <div class="rounded-2xl border border-[#1E2433] bg-[#0F131C] p-4">
      <h3 class="mb-2 text-xs font-bold text-slate-300">13F 机构持仓</h3>
      <Alert type="warning" show-icon class="mb-3" style="background: transparent">
        <template #message>
          <span class="text-xs">
            {{ institutions?.caveats.join('；') }}
          </span>
        </template>
      </Alert>

      <div v-if="!institutions?.configured" class="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-[#232B3E] py-8 text-center">
        <p class="text-xs text-slate-400">{{ institutions?.message }}</p>
        <button class="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500" @click="goToApiConfig">
          去系统设置配置数据源
        </button>
      </div>
      <div v-else-if="institutions.holdings.length === 0" class="py-8 text-center text-xs text-slate-500">
        {{ institutions.message || NO_DATA_TEXT }}
      </div>
      <Table v-else :columns="institutionColumns" :data-source="institutions.holdings" :pagination="{ pageSize: 10 }" row-key="institution" size="small">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'shares'">{{ record.shares?.toLocaleString() ?? NO_DATA_TEXT }}</template>
          <template v-else-if="column.key === 'shares_change'">{{ record.shares_change?.toLocaleString() ?? NO_DATA_TEXT }}</template>
          <template v-else-if="column.key === 'market_value'">{{ record.market_value ? formatCompactUsd(record.market_value) : NO_DATA_TEXT }}</template>
        </template>
      </Table>
    </div>

    <!-- Form 4 内部人交易 -->
    <div class="rounded-2xl border border-[#1E2433] bg-[#0F131C] p-4">
      <div class="mb-2 flex items-center justify-between">
        <h3 class="text-xs font-bold text-slate-300">Form 4 内部人交易（最近 {{ insiders?.transactions.length ?? 0 }} 份披露，共 {{ insiders?.total_form4_filings ?? 0 }} 份历史 Form 4）</h3>
        <span class="text-[10px] text-slate-500">公开市场主动买入单独高亮，行权/税务处置/股权激励不代表看多看空信号</span>
      </div>
      <div v-if="flatTransactions.length === 0" class="py-8 text-center text-xs text-slate-500">{{ NO_DATA_TEXT }}</div>
      <Table v-else :columns="insiderColumns" :data-source="flatTransactions" :pagination="{ pageSize: 15 }" row-key="index_url" size="small">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'owner_name'">
            <div class="font-semibold text-white">{{ record.owner_name }}</div>
            <div class="text-[10px] text-slate-500">{{ record.officer_title }}</div>
          </template>
          <template v-else-if="column.key === 'filed_at'">{{ formatDate(record.filed_at) }}</template>
          <template v-else-if="column.key === 'transaction_date'">{{ formatDate(record.transaction_date) }}</template>
          <template v-else-if="column.key === 'category'">
            <Tag :color="record.is_open_market_buy ? 'success' : record.category === '公开市场卖出' ? 'error' : 'default'">
              {{ record.category }}
            </Tag>
          </template>
          <template v-else-if="column.key === 'shares'">{{ record.shares?.toLocaleString() ?? NO_DATA_TEXT }}</template>
          <template v-else-if="column.key === 'price_per_share'">{{ record.price_per_share ? formatUsdPerShare(record.price_per_share) : NO_DATA_TEXT }}</template>
          <template v-else-if="column.key === 'amount'">{{ record.shares && record.price_per_share ? formatCompactUsd(record.shares * record.price_per_share) : NO_DATA_TEXT }}</template>
          <template v-else-if="column.key === 'shares_owned_after'">{{ record.shares_owned_after?.toLocaleString() ?? NO_DATA_TEXT }}</template>
          <template v-else-if="column.key === 'index_url'">
            <a :href="record.index_url" target="_blank" rel="noopener noreferrer" class="text-indigo-400 underline">原文</a>
          </template>
        </template>
      </Table>
    </div>
  </div>
</template>
