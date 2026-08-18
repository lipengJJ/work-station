<script lang="ts" setup>
import type { NotifyApi } from '#/api/core/notify';
import type { HotlistApi } from '#/api/core/hotlist';

import { computed, onMounted, reactive, ref } from 'vue';

import dayjs from 'dayjs';

import { Page } from '@vben/common-ui';

import { Form, FormItem, Input, InputNumber, message, Modal, Select, Switch, Textarea, TimePicker } from 'ant-design-vue';
import { Plus } from 'lucide-vue-next';

import {
  createHotlistGlobalFilterApi,
  createHotlistRuleApi,
  deleteHotlistRuleApi,
  importHotlistRulesApi,
  listHotlistRulesApi,
  listHotlistSourcesApi,
  previewHotlistRuleApi,
  updateHotlistRuleApi,
} from '#/api/core/hotlist';
import { listNotifyConfigsApi } from '#/api/core/notify';

type WordKind = 'exclude' | 'normal' | 'required';

const NOTIFY_FREQ_OPTIONS = [
  { value: 'realtime', label: '实时（抓到新命中立即推送）' },
  { value: '1h', label: '每 1 小时汇总' },
  { value: '6h', label: '每 6 小时汇总' },
  { value: '12h', label: '每 12 小时汇总' },
  { value: 'daily', label: '每天汇总（约 24 小时一次，从首条命中起算）' },
];

// -------------------------------------------------------------- 列表 ----
const rules = ref<HotlistApi.Rule[]>([]);
const loading = ref(false);
const sources = ref<HotlistApi.Source[]>([]);

const groupRules = computed(() => rules.value.filter((r) => r.rule_type === 'group'));
const globalFilters = computed(() => rules.value.filter((r) => r.rule_type === 'global_filter'));

const notifyConfigs = ref<NotifyApi.NotificationConfig[]>([]);
async function fetchNotifyConfigs() {
  try {
    notifyConfigs.value = await listNotifyConfigsApi();
  } catch {
    /* 通知渠道加载失败静默降级，推送设置区少几个选项而已 */
  }
}
function notifyChannelLabel(cfg: NotifyApi.NotificationConfig) {
  return cfg.remark || cfg.channel;
}

async function fetchRules() {
  loading.value = true;
  try {
    rules.value = await listHotlistRulesApi();
  } catch (e: any) {
    message.error(`加载失败：${e.message}`);
  } finally {
    loading.value = false;
  }
}
async function fetchSources() {
  try {
    sources.value = await listHotlistSourcesApi();
  } catch {
    /* 源加载失败静默降级，规则编辑里的「限定源」少几个选项而已 */
  }
}
function sourceLabel(ids: string[]) {
  if (!ids.length) return '全部源';
  return ids.map((id) => sources.value.find((s) => s.id === id)?.name || id).join('、');
}

async function toggleEnabled(rule: HotlistApi.Rule, enabled: boolean) {
  try {
    await updateHotlistRuleApi(rule.id, { enabled });
    rule.enabled = enabled;
  } catch (e: any) {
    message.error(`操作失败：${e.message}`);
  }
}

async function removeRule(rule: HotlistApi.Rule) {
  Modal.confirm({
    title: `删除「${rule.display_name || '未命名规则'}」？`,
    okType: 'danger',
    async onOk() {
      try {
        await deleteHotlistRuleApi(rule.id);
        rules.value = rules.value.filter((r) => r.id !== rule.id);
        message.success('已删除');
      } catch (e: any) {
        message.error(`删除失败：${e.message}`);
      }
    },
  });
}

// -------------------------------------------------------------- 词组编辑 ----
const editModalOpen = ref(false);
const editTarget = ref<HotlistApi.Rule | null>(null);
const editSaving = ref(false);
const form = reactive({
  display_name: '',
  source_ids: [] as string[],
  max_count: 0,
  enabled: true,
  normal_words: [] as HotlistApi.Word[],
  required_words: [] as HotlistApi.Word[],
  exclude_words: [] as HotlistApi.Word[],
  notify_enabled: false,
  notify_channel_ids: [] as number[],
  notify_frequency: 'realtime',
  notify_time_start: null as null | string,
  notify_time_end: null as null | string,
  notify_only_on_hit: true,
});
const draftInputs = reactive({ normal: '', required: '', exclude: '' });
const draftRegex = reactive({ normal: false, required: false, exclude: false });

const unlimitedTime = ref(true);
const startDayjs = computed(() => (form.notify_time_start ? dayjs(form.notify_time_start, 'HH:mm') : undefined));
const endDayjs = computed(() => (form.notify_time_end ? dayjs(form.notify_time_end, 'HH:mm') : undefined));
function toggleUnlimitedTime(checked: boolean) {
  unlimitedTime.value = checked;
  if (checked) {
    form.notify_time_start = null;
    form.notify_time_end = null;
  } else {
    form.notify_time_start = form.notify_time_start || '09:00';
    form.notify_time_end = form.notify_time_end || '22:00';
  }
}

function wordList(kind: WordKind) {
  return kind === 'normal' ? form.normal_words : kind === 'required' ? form.required_words : form.exclude_words;
}
function addWord(kind: WordKind) {
  const text = draftInputs[kind].trim();
  if (!text) return;
  wordList(kind).push({ word: text, is_regex: draftRegex[kind] });
  draftInputs[kind] = '';
  draftRegex[kind] = false;
}
function removeWord(kind: WordKind, idx: number) {
  wordList(kind).splice(idx, 1);
}

function openCreate() {
  editTarget.value = null;
  form.display_name = '';
  form.source_ids = [];
  form.max_count = 0;
  form.enabled = true;
  form.normal_words = [];
  form.required_words = [];
  form.exclude_words = [];
  form.notify_enabled = false;
  form.notify_channel_ids = [];
  form.notify_frequency = 'realtime';
  form.notify_time_start = null;
  form.notify_time_end = null;
  form.notify_only_on_hit = true;
  unlimitedTime.value = true;
  previewResult.value = null;
  editModalOpen.value = true;
}
function openEdit(rule: HotlistApi.Rule) {
  editTarget.value = rule;
  form.display_name = rule.display_name;
  form.source_ids = [...rule.source_ids];
  form.max_count = rule.max_count;
  form.enabled = rule.enabled;
  form.normal_words = rule.normal_words.map((w) => ({ ...w }));
  form.required_words = rule.required_words.map((w) => ({ ...w }));
  form.exclude_words = rule.exclude_words.map((w) => ({ ...w }));
  form.notify_enabled = rule.notify_enabled;
  form.notify_channel_ids = [...rule.notify_channel_ids];
  form.notify_frequency = rule.notify_frequency;
  form.notify_time_start = rule.notify_time_start;
  form.notify_time_end = rule.notify_time_end;
  form.notify_only_on_hit = rule.notify_only_on_hit;
  unlimitedTime.value = !rule.notify_time_start || !rule.notify_time_end;
  previewResult.value = null;
  editModalOpen.value = true;
}

async function submitEdit() {
  if (!form.normal_words.length && !form.required_words.length) {
    message.warning('普通词 / 必须词至少填一个，否则规则永远不会命中');
    return;
  }
  if (form.notify_enabled && form.notify_channel_ids.length === 0) {
    message.warning('开启了推送但没选通知渠道，规则不会真正发出消息');
    return;
  }
  editSaving.value = true;
  try {
    const payload: HotlistApi.RuleParams = {
      display_name: form.display_name.trim(),
      source_ids: form.source_ids,
      max_count: form.max_count,
      enabled: form.enabled,
      normal_words: form.normal_words,
      required_words: form.required_words,
      exclude_words: form.exclude_words,
      notify_enabled: form.notify_enabled,
      notify_channel_ids: form.notify_channel_ids,
      notify_time_start: form.notify_time_start,
      notify_time_end: form.notify_time_end,
      notify_frequency: form.notify_frequency,
      notify_only_on_hit: form.notify_only_on_hit,
    };
    if (editTarget.value) {
      const updated = await updateHotlistRuleApi(editTarget.value.id, payload);
      const idx = rules.value.findIndex((r) => r.id === updated.id);
      if (idx >= 0) rules.value[idx] = updated;
    } else {
      const created = await createHotlistRuleApi(payload);
      rules.value.push(created);
    }
    message.success('已保存');
    editModalOpen.value = false;
  } catch (e: any) {
    message.error(`保存失败：${e.response?.data?.detail || e.message}`);
  } finally {
    editSaving.value = false;
  }
}

// -------------------------------------------------------------- 试跑 ----
const previewLoading = ref(false);
const previewResult = ref<HotlistApi.RulePreviewResult | null>(null);

async function runPreview() {
  if (!form.normal_words.length && !form.required_words.length) {
    message.warning('先填普通词或必须词再试跑');
    return;
  }
  previewLoading.value = true;
  try {
    previewResult.value = await previewHotlistRuleApi({
      normal_words: form.normal_words,
      required_words: form.required_words,
      exclude_words: form.exclude_words,
      source_ids: form.source_ids,
      sample_limit: 10,
    });
  } catch (e: any) {
    message.error(`试跑失败：${e.response?.data?.detail || e.message}`);
  } finally {
    previewLoading.value = false;
  }
}

// -------------------------------------------------------------- 全局过滤词 ----
const globalFilterModalOpen = ref(false);
const globalFilterWord = ref('');
const globalFilterSaving = ref(false);

async function submitGlobalFilter() {
  const word = globalFilterWord.value.trim();
  if (!word) return;
  globalFilterSaving.value = true;
  try {
    const created = await createHotlistGlobalFilterApi({ word });
    rules.value.push(created);
    message.success('已创建');
    globalFilterModalOpen.value = false;
    globalFilterWord.value = '';
  } catch (e: any) {
    message.error(`创建失败：${e.message}`);
  } finally {
    globalFilterSaving.value = false;
  }
}

// -------------------------------------------------------------- 批量导入 ----
const importModalOpen = ref(false);
const importText = ref('');
const importSaving = ref(false);

async function submitImport() {
  if (!importText.value.trim()) return;
  importSaving.value = true;
  try {
    const result = await importHotlistRulesApi(importText.value);
    message.success(`导入完成：新增 ${result.created_groups} 个词组、${result.created_global_filters} 条全局过滤词`);
    importModalOpen.value = false;
    importText.value = '';
    fetchRules();
  } catch (e: any) {
    message.error(`导入失败：${e.response?.data?.detail || e.message}`);
  } finally {
    importSaving.value = false;
  }
}

onMounted(() => {
  fetchSources();
  fetchRules();
  fetchNotifyConfigs();
});
</script>

<template>
  <Page :auto-content-height="true" content-class="!p-0">
    <div class="custom-scrollbar flex h-full flex-1 flex-col overflow-y-auto bg-[hsl(var(--background-deep))] p-6 select-none">
      <div class="mb-6 shrink-0 flex items-start justify-between gap-3">
        <div>
          <h1 class="text-xl font-extrabold text-[hsl(var(--foreground))]">热点聚合 · 规则</h1>
          <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">
            普通词 OR / 必须词 AND / 排除词 NOT，支持正则和限量；保存前可试跑看命中样例
          </p>
        </div>
        <div class="flex shrink-0 items-center gap-2">
          <button
            class="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-1.5 text-xs text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
            @click="importModalOpen = true"
          >
            批量导入
          </button>
          <button
            class="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-1.5 text-xs text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
            @click="globalFilterModalOpen = true"
          >
            新建全局过滤词
          </button>
          <button
            class="flex items-center gap-1 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500"
            @click="openCreate"
          >
            <Plus class="h-3.5 w-3.5" />
            新建词组
          </button>
        </div>
      </div>

      <!-- 全局过滤词 -->
      <div v-if="globalFilters.length" class="mb-6 shrink-0">
        <h2 class="mb-2 text-xs font-bold text-[hsl(var(--muted-foreground))] uppercase">全局过滤词（命中即从所有词组结果中剔除）</h2>
        <div class="flex flex-wrap gap-2">
          <span
            v-for="gf in globalFilters"
            :key="gf.id"
            class="flex items-center gap-1.5 rounded-lg bg-rose-500/10 px-2.5 py-1 text-xs text-rose-400"
          >
            {{ gf.display_name }}
            <button class="text-rose-400/60 hover:text-rose-400" @click="removeRule(gf)">×</button>
          </span>
        </div>
      </div>

      <!-- 词组规则卡片 -->
      <h2 class="mb-2 shrink-0 text-xs font-bold text-[hsl(var(--muted-foreground))] uppercase">词组规则</h2>
      <div v-if="!loading && groupRules.length === 0" class="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-12 text-center">
        <p class="text-sm font-semibold text-[hsl(var(--foreground))]">暂无规则</p>
        <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">点右上角「新建词组」或「批量导入」开始配置</p>
      </div>
      <div v-else class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <div
          v-for="rule in groupRules"
          :key="rule.id"
          class="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-4 shadow-xl"
        >
          <div class="mb-2 flex items-start justify-between gap-2">
            <div class="min-w-0">
              <div class="truncate text-sm font-bold text-[hsl(var(--foreground))]">{{ rule.display_name || '未命名规则' }}</div>
              <div class="mt-0.5 truncate text-[11px] text-[hsl(var(--muted-foreground))]">{{ sourceLabel(rule.source_ids) }}</div>
            </div>
            <Switch size="small" :checked="rule.enabled" @change="(v) => toggleEnabled(rule, Boolean(v))" />
          </div>

          <div class="mb-3 flex flex-wrap gap-1">
            <span v-for="w in rule.normal_words" :key="`n-${w.word}`" class="rounded bg-blue-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-blue-400">
              {{ w.display_name || w.word }}
            </span>
            <span v-for="w in rule.required_words" :key="`r-${w.word}`" class="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-amber-400">
              +{{ w.display_name || w.word }}
            </span>
            <span v-for="w in rule.exclude_words" :key="`e-${w.word}`" class="rounded bg-rose-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-rose-400">
              !{{ w.display_name || w.word }}
            </span>
          </div>

          <div class="flex items-center justify-between text-[11px] text-[hsl(var(--muted-foreground))]">
            <span v-if="rule.max_count > 0">最多显示 {{ rule.max_count }} 条</span>
            <span v-else>不限量</span>
            <div class="flex items-center gap-3">
              <button class="hover:text-indigo-400" @click="openEdit(rule)">编辑</button>
              <button class="hover:text-rose-400" @click="removeRule(rule)">删除</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 词组编辑弹窗 -->
    <Modal v-model:open="editModalOpen" :title="editTarget ? '编辑词组' : '新建词组'" :footer="null" width="560px">
      <Form layout="vertical">
        <FormItem label="显示名（可选，留空则用关键词自动拼接）">
          <Input v-model:value="form.display_name" placeholder="例如：大模型" />
        </FormItem>

        <FormItem v-for="kind in (['normal', 'required', 'exclude'] as WordKind[])" :key="kind">
          <template #label>
            <span v-if="kind === 'normal'">普通词（OR，任一命中即算这组命中）</span>
            <span v-else-if="kind === 'required'">必须词（AND，全部命中才算这组命中）</span>
            <span v-else>排除词（NOT，命中则本组不算命中）</span>
          </template>
          <div class="mb-2 flex flex-wrap gap-1.5">
            <span
              v-for="(w, idx) in wordList(kind)"
              :key="`${kind}-${idx}`"
              class="flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-semibold"
              :class="{
                'bg-blue-500/15 text-blue-400': kind === 'normal',
                'bg-amber-500/15 text-amber-400': kind === 'required',
                'bg-rose-500/15 text-rose-400': kind === 'exclude',
              }"
            >
              {{ w.is_regex ? `/${w.word}/` : w.word }}
              <button class="opacity-60 hover:opacity-100" @click="removeWord(kind, idx)">×</button>
            </span>
          </div>
          <div class="flex items-center gap-2">
            <Input
              v-model:value="draftInputs[kind]"
              placeholder="输入词，回车添加"
              size="small"
              @press-enter="addWord(kind)"
            />
            <label class="flex shrink-0 items-center gap-1 text-[11px] text-[hsl(var(--muted-foreground))]">
              <Switch size="small" v-model:checked="draftRegex[kind]" />
              正则
            </label>
            <button class="shrink-0 rounded border border-[hsl(var(--border))] px-2 py-1 text-[11px]" @click="addWord(kind)">添加</button>
          </div>
        </FormItem>

        <FormItem label="限定源（留空 = 全部源）">
          <Select
            v-model:value="form.source_ids"
            mode="multiple"
            allow-clear
            placeholder="全部源"
            :options="sources.map((s) => ({ value: s.id, label: s.name || s.id }))"
          />
        </FormItem>

        <FormItem label="最多显示条数（0 = 不限）">
          <InputNumber v-model:value="form.max_count" :min="0" class="w-full" />
        </FormItem>

        <FormItem label="启用">
          <Switch v-model:checked="form.enabled" />
        </FormItem>

        <div class="mb-3 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3">
          <div class="mb-2 flex items-center justify-between">
            <span class="text-xs font-semibold text-[hsl(var(--foreground))]">命中推送</span>
            <Switch size="small" v-model:checked="form.notify_enabled" />
          </div>
          <template v-if="form.notify_enabled">
            <div v-if="notifyConfigs.length === 0" class="text-[11px] text-amber-400">
              还没有配置通知渠道，先去「系统设置 → 消息通知」加一个企业微信 / Server酱 / PushPlus
            </div>
            <template v-else>
              <div class="mb-2">
                <div class="mb-1 text-[11px] text-[hsl(var(--muted-foreground))]">推送到（可多选）</div>
                <Select
                  v-model:value="form.notify_channel_ids"
                  mode="multiple"
                  placeholder="选择通知渠道"
                  class="w-full"
                  :options="notifyConfigs.map((c) => ({ value: c.id, label: notifyChannelLabel(c) }))"
                />
              </div>
              <div class="mb-2">
                <div class="mb-1 text-[11px] text-[hsl(var(--muted-foreground))]">推送频率</div>
                <Select v-model:value="form.notify_frequency" class="w-full" :options="NOTIFY_FREQ_OPTIONS" />
              </div>
              <div class="mb-2">
                <div class="mb-1 text-[11px] text-[hsl(var(--muted-foreground))]">通知时段</div>
                <div class="flex items-center gap-2">
                  <TimePicker
                    :value="startDayjs"
                    format="HH:mm"
                    size="small"
                    class="w-24"
                    :disabled="unlimitedTime"
                    @change="(t: any) => (form.notify_time_start = t ? t.format('HH:mm') : null)"
                  />
                  <span class="text-[hsl(var(--muted-foreground))]">至</span>
                  <TimePicker
                    :value="endDayjs"
                    format="HH:mm"
                    size="small"
                    class="w-24"
                    :disabled="unlimitedTime"
                    @change="(t: any) => (form.notify_time_end = t ? t.format('HH:mm') : null)"
                  />
                  <label class="flex items-center gap-1 text-[11px] text-[hsl(var(--muted-foreground))]">
                    <input type="checkbox" :checked="unlimitedTime" @change="(e) => toggleUnlimitedTime((e.target as HTMLInputElement).checked)" />
                    不限时段
                  </label>
                </div>
              </div>
              <label class="flex items-center gap-1.5 text-[11px] text-[hsl(var(--muted-foreground))]">
                <Switch size="small" v-model:checked="form.notify_only_on_hit" />
                仅在有新命中时推送（关闭则无命中也会发一条空消息）
              </label>
            </template>
          </template>
        </div>

        <div class="mb-3 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3">
          <div class="mb-2 flex items-center justify-between">
            <span class="text-xs font-semibold text-[hsl(var(--foreground))]">试跑（拿今天已抓数据跑一遍，不落库）</span>
            <button
              :disabled="previewLoading"
              class="rounded border border-[hsl(var(--border))] px-2 py-1 text-[11px] disabled:opacity-50"
              @click="runPreview"
            >
              {{ previewLoading ? '跑一下…' : '试跑' }}
            </button>
          </div>
          <div v-if="previewResult" class="text-xs">
            <p class="mb-1 text-[hsl(var(--muted-foreground))]">命中 {{ previewResult.matched_count }} 条{{ previewResult.matched_count > previewResult.samples.length ? `，展示前 ${previewResult.samples.length} 条` : '' }}</p>
            <ul class="space-y-1">
              <li v-for="s in previewResult.samples" :key="s.id" class="truncate text-[hsl(var(--foreground))]">· {{ s.title }}</li>
            </ul>
          </div>
        </div>

        <div class="flex justify-end gap-2">
          <button class="rounded-lg border border-[hsl(var(--border))] px-3 py-1.5 text-xs" @click="editModalOpen = false">取消</button>
          <button
            :disabled="editSaving"
            class="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500 disabled:opacity-50"
            @click="submitEdit"
          >
            保存
          </button>
        </div>
      </Form>
    </Modal>

    <!-- 全局过滤词弹窗 -->
    <Modal v-model:open="globalFilterModalOpen" title="新建全局过滤词" :footer="null" width="400px">
      <Form layout="vertical">
        <FormItem label="词（纯文本，不支持正则，命中即从所有词组结果中剔除）">
          <Input v-model:value="globalFilterWord" placeholder="例如：广告" @press-enter="submitGlobalFilter" />
        </FormItem>
        <div class="flex justify-end gap-2">
          <button class="rounded-lg border border-[hsl(var(--border))] px-3 py-1.5 text-xs" @click="globalFilterModalOpen = false">取消</button>
          <button
            :disabled="globalFilterSaving"
            class="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500 disabled:opacity-50"
            @click="submitGlobalFilter"
          >
            创建
          </button>
        </div>
      </Form>
    </Modal>

    <!-- 批量导入弹窗 -->
    <Modal v-model:open="importModalOpen" title="批量导入（TrendRadar 格式文本）" :footer="null" width="560px">
      <p class="mb-2 text-xs text-[hsl(var(--muted-foreground))]">
        空行分组；+必须词、!排除词、@限量、/正则/、"词 => 别名"、[组别名]、[GLOBAL_FILTER] 均支持
      </p>
      <Textarea v-model:value="importText" :rows="10" placeholder="京东&#10;阿里&#10;&#10;[大模型]&#10;+AI&#10;融资&#10;!招聘&#10;@10" />
      <div class="mt-3 flex justify-end gap-2">
        <button class="rounded-lg border border-[hsl(var(--border))] px-3 py-1.5 text-xs" @click="importModalOpen = false">取消</button>
        <button
          :disabled="importSaving"
          class="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500 disabled:opacity-50"
          @click="submitImport"
        >
          导入
        </button>
      </div>
    </Modal>
  </Page>
</template>
