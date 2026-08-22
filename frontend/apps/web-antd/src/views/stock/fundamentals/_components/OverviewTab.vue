<script lang="ts" setup>
import type { FundamentalsApi } from '#/api/core/fundamentals';

import { computed } from 'vue';

import { Tooltip } from 'ant-design-vue';

import { formatCompactUsd, formatMultiple, formatPercent, formatRatioAsPercent, NO_DATA_TEXT } from '../_shared/format';

const props = defineProps<{
  overview: FundamentalsApi.OverviewData | null;
}>();

type Polarity = 'higher-better' | 'inverse' | 'neutral';

interface CardDef {
  key: keyof FundamentalsApi.OverviewData;
  title: string;
  tooltip: string;
  polarity: Polarity;
  format: (v: any) => string;
}

// 不是所有指标都是"越高越好"：负债权益比越低越健康（inverse），估值倍数本身没有绝对
// 好坏（neutral，得结合增长/行业判断），只有盈利能力、现金流这类才是越高越正面
const CARDS: CardDef[] = [
  { key: 'market_cap', title: '市值', tooltip: '总股本 × 当前股价，反映公司整体市场规模', polarity: 'neutral', format: formatCompactUsd },
  { key: 'enterprise_value', title: '企业价值 EV', tooltip: '市值 + 总债务 - 现金，衡量收购这家公司的实际成本', polarity: 'neutral', format: formatCompactUsd },
  { key: 'pe_ttm', title: 'TTM市盈率', tooltip: '股价 / 过去12个月每股收益，越低不代表越便宜，要结合增长和行业对比', polarity: 'neutral', format: (v) => formatMultiple(v) },
  { key: 'pe_forward', title: 'Forward PE', tooltip: '股价 / 未来12个月市场一致预期每股收益', polarity: 'neutral', format: (v) => formatMultiple(v) },
  { key: 'peg_ratio', title: 'PEG', tooltip: 'PE / 盈利增速，衡量估值相对增长是否合理，一般认为1附近算合理', polarity: 'neutral', format: (v) => formatMultiple(v) },
  { key: 'ps_ttm', title: 'Price/Sales', tooltip: '市值 / 过去12个月营收，常用于还没盈利的公司', polarity: 'neutral', format: (v) => formatMultiple(v) },
  { key: 'pb', title: 'Price/Book', tooltip: '股价 / 每股净资产', polarity: 'neutral', format: (v) => formatMultiple(v) },
  { key: 'ev_ebitda', title: 'EV/EBITDA', tooltip: '企业价值 / 息税折旧摊销前利润，剔除资本结构和折旧政策差异后的估值倍数', polarity: 'neutral', format: (v) => formatMultiple(v) },
  { key: 'dividend_yield', title: '股息率', tooltip: '年化每股分红 / 股价', polarity: 'higher-better', format: (v) => formatPercent(v) },
  { key: 'roe', title: 'ROE', tooltip: '净利润 / 股东权益，衡量股东资本的回报效率', polarity: 'higher-better', format: (v) => formatRatioAsPercent(v) },
  { key: 'roic', title: 'ROIC', tooltip: '税后经营利润 / 投入资本（估算值，假设21%税率，见下方说明），衡量资本配置效率', polarity: 'higher-better', format: (v) => formatPercent(v) },
  { key: 'gross_margin', title: '毛利率', tooltip: '(营收-成本) / 营收', polarity: 'higher-better', format: (v) => formatRatioAsPercent(v) },
  { key: 'operating_margin', title: '营业利润率', tooltip: '营业利润 / 营收', polarity: 'higher-better', format: (v) => formatRatioAsPercent(v) },
  { key: 'net_margin', title: '净利率', tooltip: '净利润 / 营收', polarity: 'higher-better', format: (v) => formatRatioAsPercent(v) },
  { key: 'debt_to_equity', title: '负债权益比', tooltip: '总负债 / 股东权益（yfinance 口径已是百分数），数值越高杠杆越高、财务风险通常越大——但多高算高因行业而异，这里不做简单的红绿判断', polarity: 'neutral', format: (v) => formatMultiple(v, '%') },
  { key: 'net_debt', title: '净负债', tooltip: '总债务 - 现金，负数表示现金比债务还多（净现金状态）', polarity: 'inverse', format: formatCompactUsd },
  { key: 'fcf_yield', title: '自由现金流收益率', tooltip: '自由现金流 / 市值', polarity: 'higher-better', format: (v) => formatPercent(v) },
];

function cardValue(card: CardDef): any {
  return props.overview ? props.overview[card.key] : null;
}

function cardColorClass(card: CardDef): string {
  const raw = cardValue(card);
  if (raw === null || raw === undefined) return 'text-[hsl(var(--muted-foreground))]';
  if (card.polarity === 'neutral') return 'text-[hsl(var(--foreground))]';
  const positive = card.polarity === 'higher-better' ? raw > 0 : raw < 0;
  return positive ? 'text-success' : 'text-destructive';
}

const hasOverview = computed(() => !!props.overview);
</script>

<template>
  <div v-if="!hasOverview" class="py-12 text-center text-xs text-[hsl(var(--muted-foreground))]">{{ NO_DATA_TEXT }}</div>
  <div v-else class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
    <div v-for="card in CARDS" :key="card.key" class="space-y-1.5 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-3.5">
      <Tooltip :title="card.tooltip">
        <div class="flex cursor-help items-center gap-1 text-[11px] font-semibold text-[hsl(var(--muted-foreground))]">
          {{ card.title }}
        </div>
      </Tooltip>
      <div class="font-mono text-lg font-black" :class="cardColorClass(card)">
        {{ card.format(cardValue(card)) }}
      </div>
    </div>
  </div>
</template>
