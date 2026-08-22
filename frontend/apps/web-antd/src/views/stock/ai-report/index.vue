<script lang="ts" setup>
import type { StrategyAiApi } from '#/api/core/strategy-ai';

import { reactive, ref, onMounted, watch, computed } from 'vue';

import { Page } from '@vben/common-ui';
import { Input, message, Modal, Select, Table, Tabs, Tag } from 'ant-design-vue';
import MarkdownIt from 'markdown-it';
import {
  BrainCircuit,
  CheckCircle2,
  FileText,
  FolderOpen,
  Loader2,
  Pencil,
  Play,
  Plus,
  Search,
  Square,
  Trash2,
  TrendingUp,
} from 'lucide-vue-next';

import {
  createStrategyApi,
  deleteStrategyApi,
  deleteStrategyReportApi,
  getStrategyReportApi,
  listStrategiesApi,
  listStrategyReportsApi,
  streamStrategyAnalysisApi,
  updateStrategyApi,
} from '#/api/core/strategy-ai';

import { selectedStock } from '../_shared/stock-state';

const md = new MarkdownIt({ breaks: true, linkify: true });

const FOCUS_OPTIONS = [
  { value: 'financials', label: '基本面' },
  { value: 'valuation', label: '估值' },
  { value: 'kline', label: '技术面' },
  { value: 'risks', label: '风险' },
];
const FACTOR_OPTIONS = [
  { value: 'revenue_growth', label: '营收增长' },
  { value: 'margin', label: '利润率' },
  { value: 'roe', label: 'ROE' },
  { value: 'pe_percentile', label: 'PE 历史分位' },
  { value: 'debt', label: '负债水平' },
  { value: 'fcf', label: '自由现金流' },
  { value: 'dividend', label: '股息' },
  { value: 'volatility', label: '波动率' },
  { value: 'rsi', label: 'RSI' },
  { value: 'ma_trend', label: '均线趋势' },
  { value: 'macd', label: 'MACD' },
  { value: 'volume', label: '量能' },
  { value: 'change_20d', label: '20日涨跌' },
];
const RATING_COLOR: Record<string, string> = { buy: 'green', hold: 'gold', avoid: 'red' };
const RATING_STYLE: Record<string, { border: string; bg: string; text: string }> = {
  buy: { border: 'border-success/40', bg: 'bg-success/10', text: 'text-success' },
  hold: { border: 'border-warning/40', bg: 'bg-warning/10', text: 'text-warning' },
  avoid: { border: 'border-destructive/40', bg: 'bg-destructive/10', text: 'text-destructive' },
};
const RISK_LABEL: Record<string, string> = { low: '保守', medium: '平衡', high: '激进' };

/** 按评级中文标签取样式（买入/观望/回避），未识别时按回避（警示）处理 */
function ratingStyleFor(label: string | undefined): { border: string; bg: string; text: string } {
  if (label === '买入') return RATING_STYLE.buy!;
  if (label === '观望') return RATING_STYLE.hold!;
  return RATING_STYLE.avoid!;
}

const activeTab = ref('analyze');

// ---------------------------------------------------------------- 策略库 ----

const strategies = ref<StrategyAiApi.StrategyItem[]>([]);
const strategyLoading = ref(false);
const strategyModalOpen = ref(false);
const savingStrategy = ref(false);
const editingStrategy = ref<StrategyAiApi.StrategyItem | null>(null);
const strategyForm = reactive({
  name: '',
  description: '',
  focus: ['financials', 'valuation', 'kline', 'risks'],
  riskPreference: 'medium',
  keyFactors: [] as string[],
  buyBias: '',
  holdCondition: '',
  avoidCondition: '',
  outputSections: '策略结论\n核心逻辑\n关键指标依据\n风险点\n分级结论',
});

async function loadStrategies() {
  strategyLoading.value = true;
  try {
    strategies.value = await listStrategiesApi();
    if (!activeStrategyId.value && strategies.value.length > 0) {
      activeStrategyId.value = strategies.value[0]!.id;
    }
  } catch (e: any) {
    message.error(e?.message || '策略列表加载失败');
  } finally {
    strategyLoading.value = false;
  }
}

function openCreate() {
  editingStrategy.value = null;
  Object.assign(strategyForm, {
    name: '',
    description: '',
    focus: ['financials', 'valuation', 'kline', 'risks'],
    riskPreference: 'medium',
    keyFactors: [],
    buyBias: '',
    holdCondition: '',
    avoidCondition: '',
    outputSections: '策略结论\n核心逻辑\n关键指标依据\n风险点\n分级结论',
  });
  strategyModalOpen.value = true;
}

function openEdit(strategy: StrategyAiApi.StrategyItem) {
  editingStrategy.value = strategy;
  const rules = strategy.rules || {};
  Object.assign(strategyForm, {
    name: strategy.name,
    description: strategy.description,
    focus: rules.focus || [],
    riskPreference: rules.risk_preference || 'medium',
    keyFactors: rules.key_factors || [],
    buyBias: rules.buy_bias ? JSON.stringify(rules.buy_bias, null, 2) : '',
    holdCondition: rules.hold_condition || '',
    avoidCondition: rules.avoid_condition || '',
    outputSections: (rules.output_sections || []).join('\n'),
  });
  strategyModalOpen.value = true;
}

async function submitStrategy() {
  const name = strategyForm.name.trim();
  if (!name) {
    message.error('请填写策略名称');
    return;
  }
  let buyBias: Record<string, unknown> | undefined;
  if (strategyForm.buyBias.trim()) {
    try {
      buyBias = JSON.parse(strategyForm.buyBias);
    } catch {
      message.error('买入倾向 JSON 格式不正确');
      return;
    }
  }
  // 预设策略的 rules 后端会忽略（保持内置框架），这里不传
  const rules: StrategyAiApi.StrategyRules =
    editingStrategy.value?.is_preset
      ? {}
      : {
          focus: strategyForm.focus,
          risk_preference: strategyForm.riskPreference as StrategyAiApi.StrategyRules['risk_preference'],
          key_factors: strategyForm.keyFactors,
          buy_bias: buyBias,
          hold_condition: strategyForm.holdCondition.trim() || undefined,
          avoid_condition: strategyForm.avoidCondition.trim() || undefined,
          output_sections: strategyForm.outputSections
            .split('\n')
            .map((s) => s.trim())
            .filter(Boolean),
        };
  savingStrategy.value = true;
  try {
    if (editingStrategy.value) {
      await updateStrategyApi(editingStrategy.value.id, { name, description: strategyForm.description, rules });
      message.success('策略已更新');
    } else {
      await createStrategyApi({ name, description: strategyForm.description, rules });
      message.success('策略已创建');
    }
    strategyModalOpen.value = false;
    await loadStrategies();
  } catch (e: any) {
    message.error(e?.message || '保存失败');
  } finally {
    savingStrategy.value = false;
  }
}

async function removeStrategy(strategy: StrategyAiApi.StrategyItem) {
  try {
    await deleteStrategyApi(strategy.id);
    message.success('策略已删除');
    if (activeStrategyId.value === strategy.id) {
      activeStrategyId.value = strategies.value.find((s) => s.id !== strategy.id)?.id ?? undefined;
    }
    await loadStrategies();
  } catch (e: any) {
    message.error(e?.message || '删除失败');
  }
}

function useStrategy(strategy: StrategyAiApi.StrategyItem) {
  activeStrategyId.value = strategy.id;
  activeTab.value = 'analyze';
  message.success(`已切换到策略「${strategy.name}」`);
}

// ---------------------------------------------------------------- 分析 ----

const symbolInput = ref(selectedStock.value?.symbol ?? '');
const activeStrategyId = ref<number | undefined>(undefined);
const analyzing = ref(false);
const reportMd = ref('');
const reportHtml = ref('');
const aiError = ref('');
const lastRating = ref<StrategyAiApi.RatingPayload | null>(null);
const startedAt = ref('');
let controller: AbortController | null = null;

const activeStrategy = computed(() =>
  strategies.value.find((s) => s.id === activeStrategyId.value),
);

// 从行情页/自选股跳过来时，跟着切到当前选中的股票（仅当用户还没手动输入时）
let symbolTouched = false;
watch(
  () => selectedStock.value?.symbol,
  (v) => {
    if (!symbolTouched) symbolInput.value = v ?? '';
  },
);

async function runAnalysis() {
  const symbol = symbolInput.value.trim().toUpperCase();
  if (!symbol) {
    message.error('请输入股票代码');
    return;
  }
  if (!activeStrategyId.value) {
    message.error('请先选择策略');
    return;
  }
  symbolTouched = true;
  reportMd.value = '';
  reportHtml.value = '';
  aiError.value = '';
  lastRating.value = null;
  startedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false });
  controller = new AbortController();
  analyzing.value = true;
  try {
    await streamStrategyAnalysisApi(
      symbol,
      activeStrategyId.value,
      {
        onDelta: (t) => {
          reportMd.value += t;
          reportHtml.value = md.render(reportMd.value);
        },
        onRating: (r) => {
          lastRating.value = r;
        },
        onError: (e) => {
          aiError.value = e;
        },
        onEnd: () => {
          analyzing.value = false;
          controller = null;
          loadReports();
        },
      },
      controller.signal,
    );
  } catch (e: any) {
    if (e?.name !== 'AbortError') {
      aiError.value = e?.message || '分析请求失败';
    }
    analyzing.value = false;
    controller = null;
  }
}

function cancelAnalysis() {
  controller?.abort();
  analyzing.value = false;
  controller = null;
}

// ---------------------------------------------------------------- 历史报告 ----

const reports = ref<StrategyAiApi.ReportListItem[]>([]);
const reportTotal = ref(0);
const reportPage = ref(1);
const reportPageSize = ref(10);
const reportsLoading = ref(false);

async function loadReports() {
  reportsLoading.value = true;
  try {
    const result = await listStrategyReportsApi({
      page: reportPage.value,
      page_size: reportPageSize.value,
    });
    reports.value = result.items;
    reportTotal.value = result.total;
  } catch (e: any) {
    message.error(e?.message || '历史报告加载失败');
  } finally {
    reportsLoading.value = false;
  }
}

function formatTime(iso?: string) {
  return iso ? iso.replace('T', ' ').slice(0, 16) : '--';
}

const reportColumns = [
  { title: '股票', dataIndex: 'symbol', key: 'symbol', width: 100 },
  { title: '策略', dataIndex: 'strategy_name', key: 'strategy_name', width: 130 },
  { title: '评级', key: 'rating', width: 100 },
  { title: '结论理由', dataIndex: 'rating_reason', key: 'rating_reason', ellipsis: true },
  { title: '时间', key: 'created_at', width: 140 },
  { title: '操作', key: 'action', width: 130 },
];

const detailOpen = ref(false);
const detailLoading = ref(false);
const detailReport = ref<StrategyAiApi.ReportDetail | null>(null);
const detailHtml = ref('');

async function openDetail(row: StrategyAiApi.ReportListItem) {
  detailOpen.value = true;
  detailLoading.value = true;
  detailReport.value = null;
  detailHtml.value = '';
  try {
    const detail = await getStrategyReportApi(row.id);
    detailReport.value = detail;
    detailHtml.value = md.render(detail.report_markdown || '');
  } catch (e: any) {
    message.error(e?.message || '报告加载失败');
  } finally {
    detailLoading.value = false;
  }
}

async function removeReport(row: StrategyAiApi.ReportListItem) {
  try {
    await deleteStrategyReportApi(row.id);
    message.success('报告已删除');
    await loadReports();
  } catch (e: any) {
    message.error(e?.message || '删除失败');
  }
}

onMounted(() => {
  loadStrategies();
  loadReports();
});
</script>

<template>
  <Page :auto-content-height="true" content-class="!p-0">
    <div class="custom-scrollbar h-full overflow-y-auto bg-[hsl(var(--background-deep))] p-4 sm:p-6">
      <!-- Header：标题 + 当前股票 -->
      <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 class="flex items-center gap-2 text-xl font-extrabold text-[hsl(var(--foreground))]">
            <BrainCircuit class="h-5 w-5 text-primary" />
            <span>AI 个股分析</span>
          </h1>
          <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">按策略框架分析个股近期情况，给出「买入 / 观望 / 回避」分级结论</p>
        </div>
        <div v-if="selectedStock" class="flex items-center gap-2 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] px-3 py-2">
          <span class="text-sm font-extrabold text-[hsl(var(--foreground))]">{{ selectedStock.symbol }}</span>
          <span class="text-xs text-[hsl(var(--muted-foreground))]">{{ selectedStock.name }}</span>
          <span class="text-xs font-bold" :class="(selectedStock.change ?? 0) >= 0 ? 'text-success' : 'text-destructive'">
            {{ (selectedStock.changePercent ?? 0) >= 0 ? '+' : '' }}{{ selectedStock.changePercent ?? 0 }}%
          </span>
        </div>
      </div>

      <Tabs v-model:active-key="activeTab" class="strategy-tabs">
        <!-- ================= AI 分析 ================= -->
        <Tabs.TabPane key="analyze">
          <template #tab>
            <span class="flex items-center gap-1.5">
              <TrendingUp class="h-3.5 w-3.5" />
              AI 分析
            </span>
          </template>

          <div class="flex min-w-0 flex-col gap-4">
            <!-- 操作条：股票输入 + 分析/停止 -->
            <div class="flex flex-wrap items-center gap-2 rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-3">
              <div class="relative min-w-0 flex-1 sm:max-w-xs">
                <Search class="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[hsl(var(--muted-foreground))]" />
                <input
                  v-model="symbolInput"
                  placeholder="股票代码，如 AAPL / 0700.HK"
                  class="h-9 w-full rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] pl-8 pr-3 text-xs text-[hsl(var(--foreground))] outline-none placeholder:text-[hsl(var(--muted-foreground))] focus:border-primary"
                  @keyup.enter="!analyzing && runAnalysis()"
                />
              </div>
              <div class="ml-auto flex items-center gap-2">
                <button
                  v-if="!analyzing"
                  class="flex h-9 items-center gap-1.5 rounded-lg bg-primary px-5 text-xs font-bold text-white hover:bg-primary disabled:opacity-50"
                  :disabled="!activeStrategyId"
                  @click="runAnalysis"
                >
                  <Play class="h-3.5 w-3.5" />
                  开始分析
                </button>
                <button
                  v-else
                  class="flex h-9 items-center gap-1.5 rounded-lg bg-destructive px-5 text-xs font-bold text-white hover:bg-destructive"
                  @click="cancelAnalysis"
                >
                  <Square class="h-3.5 w-3.5" />
                  停止
                </button>
              </div>
            </div>

            <!-- 策略胶囊选择（比下拉更直观：当前用哪个策略一目了然） -->
            <div class="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-3">
              <div class="mb-2 flex items-center justify-between">
                <span class="text-[10px] font-bold uppercase tracking-wider text-[hsl(var(--muted-foreground))]">选择分析策略</span>
                <button class="text-[11px] text-primary hover:text-primary" @click="activeTab = 'strategies'">
                  管理策略 →
                </button>
              </div>
              <div v-if="strategyLoading" class="py-2 text-xs text-[hsl(var(--muted-foreground))]">加载策略中…</div>
              <div v-else class="flex flex-wrap items-center gap-1.5">
                <button
                  v-for="s in strategies"
                  :key="s.id"
                  class="flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[11px] font-bold transition-all"
                  :class="
                    activeStrategyId === s.id
                      ? 'border-primary bg-primary text-white shadow-lg shadow-primary/20'
                      : 'border-[hsl(var(--border))] bg-[hsl(var(--accent))] text-[hsl(var(--muted-foreground))] hover:border-primary/50 hover:text-[hsl(var(--foreground))]'
                  "
                  @click="activeStrategyId = s.id"
                >
                  <span class="h-1.5 w-1.5 rounded-full" :class="s.is_preset ? 'bg-primary' : 'bg-success'"></span>
                  {{ s.name }}
                </button>
                <button
                  class="flex items-center gap-1 rounded-full border border-dashed border-[hsl(var(--border))] px-3 py-1.5 text-[11px] font-bold text-[hsl(var(--muted-foreground))] hover:border-primary/50 hover:text-primary"
                  @click="openCreate"
                >
                  <Plus class="h-3 w-3" />
                  新建
                </button>
              </div>
              <p v-if="activeStrategy" class="mt-2 text-[11px] text-[hsl(var(--muted-foreground))]">
                <span class="font-bold text-primary">{{ activeStrategy.name }}</span>
                {{ activeStrategy.description || '（无描述）' }}
              </p>
            </div>

            <!-- 分析输出 -->
            <div class="min-w-0 rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-4 sm:p-5">
              <!-- 结论摘要卡（生成完成后） -->
              <div
                v-if="lastRating"
                class="mb-5 overflow-hidden rounded-2xl border"
                :class="ratingStyleFor(lastRating.label).border"
              >
                <div class="flex flex-col gap-3 p-4" :class="ratingStyleFor(lastRating.label).bg">
                  <div class="flex flex-wrap items-center gap-3">
                    <span
                      class="flex h-12 w-12 shrink-0 items-center justify-center rounded-full text-lg font-extrabold"
                      :class="ratingStyleFor(lastRating.label).text + ' ' + ratingStyleFor(lastRating.label).border"
                    >
                      {{ lastRating.label }}
                    </span>
                    <div class="min-w-0 flex-1">
                      <div class="text-[10px] font-bold uppercase tracking-wider text-[hsl(var(--muted-foreground))]">AI 分级结论</div>
                      <p class="mt-0.5 text-xs leading-relaxed text-[hsl(var(--muted-foreground))]">{{ lastRating.reason }}</p>
                    </div>
                  </div>
                  <div v-if="lastRating.key_indicators?.length" class="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                    <div
                      v-for="k in lastRating.key_indicators"
                      :key="k.name"
                      class="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))]/80 px-3 py-2"
                    >
                      <div class="text-[10px] text-[hsl(var(--muted-foreground))]">{{ k.name }}</div>
                      <div class="mt-0.5 flex items-baseline gap-2">
                        <span class="font-mono text-sm font-extrabold text-[hsl(var(--foreground))]">{{ k.value }}</span>
                        <span class="truncate text-[10px] text-[hsl(var(--muted-foreground))]" :title="k.verdict">{{ k.verdict }}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div v-if="aiError" class="mb-3 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                {{ aiError }}
              </div>

              <!-- 空态：三步引导 -->
              <div v-if="!reportMd && !analyzing && !aiError" class="py-14 text-center sm:py-16">
                <div class="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10">
                  <BrainCircuit class="h-8 w-8 text-primary" />
                </div>
                <p class="mt-4 text-sm font-bold text-[hsl(var(--foreground))]">开始一次策略分析</p>
                <div class="mx-auto mt-4 grid max-w-lg grid-cols-1 gap-2 sm:grid-cols-3">
                  <div class="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] px-3 py-2.5">
                    <div class="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-[11px] font-extrabold text-white">1</div>
                    <div class="mt-1.5 text-[11px] font-bold text-[hsl(var(--muted-foreground))]">输入股票代码</div>
                    <div class="mt-0.5 text-[10px] text-[hsl(var(--muted-foreground))]">如 AAPL / 0700.HK</div>
                  </div>
                  <div class="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] px-3 py-2.5">
                    <div class="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-[11px] font-extrabold text-white">2</div>
                    <div class="mt-1.5 text-[11px] font-bold text-[hsl(var(--muted-foreground))]">选择策略框架</div>
                    <div class="mt-0.5 text-[10px] text-[hsl(var(--muted-foreground))]">价值投资 / 趋势 / 防守</div>
                  </div>
                  <div class="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] px-3 py-2.5">
                    <div class="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-[11px] font-extrabold text-white">3</div>
                    <div class="mt-1.5 text-[11px] font-bold text-[hsl(var(--muted-foreground))]">AI 输出结论</div>
                    <div class="mt-0.5 text-[10px] text-[hsl(var(--muted-foreground))]">买入 / 观望 / 回避 + 依据</div>
                  </div>
                </div>
              </div>

              <!-- 生成中：步骤指示 -->
              <div v-else-if="!reportMd && analyzing" class="py-14 text-center sm:py-16">
                <div class="relative mx-auto h-12 w-12">
                  <Loader2 class="h-12 w-12 animate-spin text-primary" />
                </div>
                <p class="mt-4 text-sm font-bold text-[hsl(var(--foreground))]">
                  正在用「{{ activeStrategy?.name || '--' }}」策略分析 {{ symbolInput.toUpperCase() }}
                </p>
                <div class="mx-auto mt-4 flex max-w-sm items-center justify-center gap-2 text-[11px]">
                  <span class="flex items-center gap-1 rounded-full bg-success/15 px-2.5 py-1 font-bold text-success">
                    <CheckCircle2 class="h-3 w-3" /> 拉取数据
                  </span>
                  <span class="h-px w-4 bg-[hsl(var(--muted))]"></span>
                  <span class="flex items-center gap-1 rounded-full bg-primary/15 px-2.5 py-1 font-bold text-primary">
                    <Loader2 class="h-3 w-3 animate-spin" /> 策略分析
                  </span>
                  <span class="h-px w-4 bg-[hsl(var(--muted))]"></span>
                  <span class="flex items-center gap-1 rounded-full bg-[hsl(var(--accent))] px-2.5 py-1 font-bold text-[hsl(var(--muted-foreground))]">
                    生成结论
                  </span>
                </div>
                <p class="mt-3 text-[10px] text-[hsl(var(--muted-foreground))]">首次分析需拉取真实行情与基本面数据，通常需要 10-30 秒，可随时停止</p>
              </div>

              <!-- eslint-disable-next-line vue/no-v-html -- markdown-it 默认 html:false，裸 HTML 会被转义，和 xhs AI 分析页同一种用法 -->
              <div v-else class="strategy-ai-markdown min-w-0 text-xs leading-relaxed text-[hsl(var(--muted-foreground))]" v-html="reportHtml"></div>

              <!-- 底部信息条 -->
              <div v-if="reportMd" class="mt-5 flex flex-wrap items-center justify-between gap-2 border-t border-[hsl(var(--border))] pt-3 text-[10px] text-[hsl(var(--muted-foreground))]">
                <span>仅供研究，不构成投资建议 · 数据来源见正文标注（SEC EDGAR / Yahoo Finance / moomoo）</span>
                <span class="flex items-center gap-2">
                  <span>{{ symbolInput.toUpperCase() }} · {{ activeStrategy?.name }}</span>
                  <span v-if="startedAt">生成于 {{ startedAt }}</span>
                </span>
              </div>
            </div>
          </div>
        </Tabs.TabPane>

        <!-- ================= 策略库 ================= -->
        <Tabs.TabPane key="strategies">
          <template #tab>
            <span class="flex items-center gap-1.5">
              <FolderOpen class="h-3.5 w-3.5" />
              策略库
            </span>
          </template>

          <div class="flex min-w-0 flex-col gap-4">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <p class="text-xs text-[hsl(var(--muted-foreground))]">
                策略是 AI 分析的「框架」：关注哪些数据、风险偏好、什么条件下买入/观望/回避。内置 3 个预设，也可自建。
              </p>
              <button
                class="flex items-center gap-1 rounded-lg bg-primary px-3.5 py-2 text-xs font-bold text-white hover:bg-primary"
                @click="openCreate"
              >
                <Plus class="h-3.5 w-3.5" />
                新建策略
              </button>
            </div>

            <div v-if="strategyLoading" class="py-16 text-center text-xs text-[hsl(var(--muted-foreground))]">加载中…</div>
            <div
              v-else
              class="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4"
            >
              <div
                v-for="s in strategies"
                :key="s.id"
                class="flex min-w-0 flex-col rounded-2xl border p-4 transition-colors"
                :class="
                  activeStrategyId === s.id
                    ? 'border-primary/60 bg-primary/10'
                    : 'border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] hover:border-primary/40'
                "
              >
                <div class="flex items-center justify-between">
                  <span class="text-sm font-bold text-[hsl(var(--foreground))]">{{ s.name }}</span>
                  <span
                    :class="
                      s.is_preset
                        ? 'bg-primary/20 text-primary'
                        : 'bg-slate-500/20 text-[hsl(var(--muted-foreground))]'
                    "
                    class="rounded px-1.5 py-0.5 text-[10px] font-bold"
                  >
                    {{ s.is_preset ? '预设' : '自定义' }}
                  </span>
                </div>
                <p class="mt-2 line-clamp-3 min-h-12 text-[11px] leading-relaxed text-[hsl(var(--muted-foreground))]">{{ s.description }}</p>
                <div class="mt-3 flex flex-wrap items-center gap-2 text-[10px] text-[hsl(var(--muted-foreground))]">
                  <span class="rounded bg-[hsl(var(--background-deep))] px-2 py-1">偏好 {{ RISK_LABEL[s.rules?.risk_preference || 'medium'] }}</span>
                  <span v-if="s.rules?.focus?.length" class="rounded bg-[hsl(var(--background-deep))] px-2 py-1">
                    {{ s.rules.focus.map((f) => FOCUS_OPTIONS.find((o) => o.value === f)?.label || f).join('、') }}
                  </span>
                </div>
                <div class="mt-4 flex items-center gap-2 border-t border-[hsl(var(--border))] pt-3">
                  <button
                    class="flex flex-1 items-center justify-center gap-1 rounded-lg border border-primary/40 py-1.5 text-[11px] font-bold text-primary hover:bg-primary/10"
                    @click="useStrategy(s)"
                  >
                    <Play class="h-3 w-3" />
                    使用此策略
                  </button>
                  <button
                    class="rounded-lg border border-[hsl(var(--border))] p-2 text-[hsl(var(--muted-foreground))] hover:border-primary/40 hover:text-primary"
                    title="编辑"
                    @click="openEdit(s)"
                  >
                    <Pencil class="h-3.5 w-3.5" />
                  </button>
                  <button
                    class="rounded-lg border border-[hsl(var(--border))] p-2 text-[hsl(var(--muted-foreground))] hover:border-destructive/40 hover:text-destructive"
                    title="删除"
                    @click="removeStrategy(s)"
                  >
                    <Trash2 class="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            </div>
            <div v-if="!strategyLoading && !strategies.length" class="py-16 text-center">
              <FolderOpen class="mx-auto h-8 w-8 text-[hsl(var(--muted-foreground))]" />
              <p class="mt-2 text-xs text-[hsl(var(--muted-foreground))]">暂无策略，点「新建策略」创建一个</p>
            </div>
          </div>
        </Tabs.TabPane>

        <!-- ================= 历史报告 ================= -->
        <Tabs.TabPane key="reports">
          <template #tab>
            <span class="flex items-center gap-1.5">
              <FileText class="h-3.5 w-3.5" />
              历史报告
            </span>
          </template>

          <div class="min-w-0 rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-4">
            <Table
              :columns="reportColumns"
              :data-source="reports"
              :loading="reportsLoading"
              :pagination="{
                current: reportPage,
                pageSize: reportPageSize,
                total: reportTotal,
                showSizeChanger: false,
                onChange: (page: number) => {
                  reportPage = page;
                  loadReports();
                },
              }"
              size="middle"
              row-key="id"
              :locale="{ emptyText: '暂无历史报告' }"
              class="strategy-report-table"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'rating'">
                  <Tag v-if="record.rating" :color="RATING_COLOR[record.rating]">
                    {{ record.rating_label }}
                  </Tag>
                  <Tag v-else color="default">{{ record.status === 'failed' ? '失败' : '无结论' }}</Tag>
                </template>
                <template v-else-if="column.key === 'created_at'">{{ formatTime(record.created_at) }}</template>
                <template v-else-if="column.key === 'action'">
                  <button
                    class="mr-3 text-[11px] font-bold text-primary hover:text-primary"
                    @click="openDetail(record as StrategyAiApi.ReportListItem)"
                  >
                    查看
                  </button>
                  <button
                    class="text-[11px] text-[hsl(var(--muted-foreground))] hover:text-destructive"
                    @click="removeReport(record as StrategyAiApi.ReportListItem)"
                  >
                    删除
                  </button>
                </template>
              </template>
            </Table>
          </div>
        </Tabs.TabPane>
      </Tabs>

      <!-- 策略编辑弹窗 -->
      <Modal
        :open="strategyModalOpen"
        :title="editingStrategy ? `编辑策略：${editingStrategy.name}` : '新建策略'"
        :confirm-loading="savingStrategy"
        ok-text="保存"
        cancel-text="取消"
        width="640"
        @ok="submitStrategy"
        @cancel="strategyModalOpen = false"
      >
        <div class="space-y-3 pt-2">
          <div>
            <label class="mb-1 block text-xs font-bold text-[hsl(var(--muted-foreground))]">策略名称 *</label>
            <Input v-model:value="strategyForm.name" placeholder="如：高股息防御" :maxlength="64" />
          </div>
          <div>
            <label class="mb-1 block text-xs font-bold text-[hsl(var(--muted-foreground))]">描述</label>
            <Input.TextArea v-model:value="strategyForm.description" :rows="2" placeholder="这个策略看什么、适合什么场景" />
          </div>
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label class="mb-1 block text-xs font-bold text-[hsl(var(--muted-foreground))]">关注范围</label>
              <Select
                v-model:value="strategyForm.focus"
                mode="multiple"
                :options="FOCUS_OPTIONS"
                placeholder="选数据范围"
                class="w-full"
                :disabled="!!editingStrategy?.is_preset"
              />
            </div>
            <div>
              <label class="mb-1 block text-xs font-bold text-[hsl(var(--muted-foreground))]">风险偏好</label>
              <Select
                v-model:value="strategyForm.riskPreference"
                :options="[
                  { value: 'low', label: '保守' },
                  { value: 'medium', label: '平衡' },
                  { value: 'high', label: '激进' },
                ]"
                class="w-full"
                :disabled="!!editingStrategy?.is_preset"
              />
            </div>
          </div>
          <div>
            <label class="mb-1 block text-xs font-bold text-[hsl(var(--muted-foreground))]">优先关注因子</label>
            <Select
              v-model:value="strategyForm.keyFactors"
              mode="multiple"
              :options="FACTOR_OPTIONS"
              placeholder="选因子（可多选）"
              class="w-full"
              :disabled="!!editingStrategy?.is_preset"
            />
          </div>
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label class="mb-1 block text-xs font-bold text-[hsl(var(--muted-foreground))]">观望（hold）条件</label>
              <Input v-model:value="strategyForm.holdCondition" placeholder="什么情况下选择观望" :disabled="!!editingStrategy?.is_preset" />
            </div>
            <div>
              <label class="mb-1 block text-xs font-bold text-[hsl(var(--muted-foreground))]">回避（avoid）条件</label>
              <Input v-model:value="strategyForm.avoidCondition" placeholder="什么情况下选择回避" :disabled="!!editingStrategy?.is_preset" />
            </div>
          </div>
          <div>
            <label class="mb-1 block text-xs font-bold text-[hsl(var(--muted-foreground))]">买入倾向阈值（JSON，可选）</label>
            <Input.TextArea
              v-model:value="strategyForm.buyBias"
              :rows="3"
              class="font-mono text-[11px]"
              placeholder='如 {"pe_max": 25, "roe_min": 15, "rsi_max": 45}'
              :disabled="!!editingStrategy?.is_preset"
            />
          </div>
          <div>
            <label class="mb-1 block text-xs font-bold text-[hsl(var(--muted-foreground))]">输出小节（每行一个）</label>
            <Input.TextArea
              v-model:value="strategyForm.outputSections"
              :rows="4"
              :disabled="!!editingStrategy?.is_preset"
            />
          </div>
          <p v-if="editingStrategy?.is_preset" class="text-[11px] text-warning">
            预设策略只允许修改名称和描述，规则保持内置框架。
          </p>
        </div>
      </Modal>

      <!-- 报告详情弹窗 -->
      <Modal
        :open="detailOpen"
        :title="detailReport ? `${detailReport.symbol} · ${detailReport.strategy_name} · ${formatTime(detailReport.created_at)}` : '报告详情'"
        :footer="null"
        width="860"
        @cancel="detailOpen = false"
      >
        <div v-if="detailLoading" class="py-10 text-center text-xs text-[hsl(var(--muted-foreground))]">加载中…</div>
        <div v-else-if="detailReport">
          <div v-if="detailReport.rating" class="mb-3 flex items-center gap-2">
            <Tag :color="RATING_COLOR[detailReport.rating]">{{ detailReport.rating_label }}</Tag>
            <span class="text-[11px] text-[hsl(var(--muted-foreground))]">{{ detailReport.rating_reason }}</span>
          </div>
          <!-- eslint-disable-next-line vue/no-v-html -- markdown-it 默认 html:false，裸 HTML 会被转义 -->
          <div class="strategy-ai-markdown max-h-[65vh] overflow-y-auto text-xs leading-relaxed text-[hsl(var(--muted-foreground))]" v-html="detailHtml"></div>
        </div>
      </Modal>
    </div>
  </Page>
</template>

<style scoped>
:deep(.strategy-tabs > .ant-tabs-nav) {
  margin-bottom: 16px;
}
:deep(.strategy-tabs .ant-tabs-tab) {
  font-size: 13px;
  padding: 8px 4px;
}
:deep(.strategy-tabs .ant-tabs-ink-bar) {
  background: var(--primary);
}
:deep(.strategy-report-table .ant-table) {
  background: transparent;
}
:deep(.strategy-report-table .ant-table-thead > tr > th) {
  background: #0B0E14;
  border-bottom: 1px solid var(--border);
  color: hsl(var(--muted-foreground));
  font-size: 11px;
}
:deep(.strategy-report-table .ant-table-tbody > tr > td) {
  border-bottom: 1px solid rgba(30, 36, 51, 0.5);
  color: hsl(var(--muted-foreground));
  font-size: 12px;
}
:deep(.strategy-report-table .ant-table-tbody > tr:hover > td) {
  background: rgba(99, 102, 241, 0.06);
}
.strategy-ai-markdown :deep(h1),
.strategy-ai-markdown :deep(h2),
.strategy-ai-markdown :deep(h3) {
  margin-top: 18px;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 800;
  color: #fff;
}
.strategy-ai-markdown :deep(h2) {
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(99, 102, 241, 0.25);
  color: #c7d2fe;
}
.strategy-ai-markdown :deep(h2):first-child {
  margin-top: 0;
}
.strategy-ai-markdown :deep(h3) {
  color: hsl(var(--foreground));
}
.strategy-ai-markdown :deep(p) {
  margin-bottom: 8px;
  word-break: break-word;
  line-height: 1.7;
}
.strategy-ai-markdown :deep(ul) {
  padding-left: 18px;
  list-style: disc;
  margin-bottom: 8px;
}
.strategy-ai-markdown :deep(ul) > :deep(li) {
  margin-bottom: 4px;
}
.strategy-ai-markdown :deep(blockquote) {
  border-left: 3px solid var(--primary);
  background: rgba(99, 102, 241, 0.06);
  border-radius: 0 8px 8px 0;
  padding: 6px 10px;
  margin: 8px 0;
  color: hsl(var(--muted-foreground));
}
.strategy-ai-markdown :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 8px 0;
  font-size: 11px;
}
.strategy-ai-markdown :deep(th),
.strategy-ai-markdown :deep(td) {
  border: 1px solid #232b3e;
  padding: 5px 8px;
  text-align: left;
}
.strategy-ai-markdown :deep(th) {
  background: hsl(var(--card));
  color: hsl(var(--foreground));
  font-weight: 700;
}
.strategy-ai-markdown :deep(hr) {
  border: none;
  border-top: 1px solid #1e2433;
  margin: 12px 0;
}
.strategy-ai-markdown :deep(strong) {
  color: #fff;
}
.strategy-ai-markdown :deep(em) {
  color: hsl(var(--muted-foreground));
}
.strategy-ai-markdown :deep(code) {
  background: rgba(255, 255, 255, 0.06);
  border-radius: 4px;
  padding: 1px 4px;
  font-size: 11px;
}
.strategy-ai-markdown :deep(pre) {
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid #1e2433;
  border-radius: 8px;
  padding: 10px;
  overflow-x: auto;
  margin-bottom: 8px;
}
.strategy-ai-markdown :deep(pre code) {
  background: transparent;
  padding: 0;
}
</style>
