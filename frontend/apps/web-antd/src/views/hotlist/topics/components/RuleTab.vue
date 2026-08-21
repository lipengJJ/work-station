<script lang="ts" setup>
import type { HotlistApi } from '#/api/core/hotlist';

import { computed, onMounted, reactive, ref, watch } from 'vue';

import { Form, FormItem, Input, InputNumber, message, Modal, Switch, Textarea } from 'ant-design-vue';
import { Plus } from 'lucide-vue-next';

import {
  createTopicRuleApi,
  deleteHotlistRuleApi,
  importTopicRulesApi,
  listTopicRulesApi,
  previewTopicRuleApi,
  updateHotlistRuleApi,
} from '#/api/core/hotlist';

const props = defineProps<{ topicId: number }>();
const emit = defineEmits<{ 'count-change': [number] }>();

type WordKind = 'exclude' | 'normal' | 'required';

// -------------------------------------------------------------- 列表 ----
const rules = ref<HotlistApi.Rule[]>([]);
const loading = ref(false);

const groupRules = computed(() => rules.value.filter((r) => r.rule_type === 'group'));
watch(groupRules, (v) => emit('count-change', v.length), { immediate: true });

async function fetchRules() {
  loading.value = true;
  try {
    rules.value = await listTopicRulesApi(props.topicId);
  } catch (e: any) {
    message.error(`加载失败：${e.message}`);
  } finally {
    loading.value = false;
  }
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
  max_count: 0,
  enabled: true,
  normal_words: [] as HotlistApi.Word[],
  required_words: [] as HotlistApi.Word[],
  exclude_words: [] as HotlistApi.Word[],
});
const draftInputs = reactive({ normal: '', required: '', exclude: '' });
const draftRegex = reactive({ normal: false, required: false, exclude: false });

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
  form.max_count = 0;
  form.enabled = true;
  form.normal_words = [];
  form.required_words = [];
  form.exclude_words = [];
  previewResult.value = null;
  editModalOpen.value = true;
}
function openEdit(rule: HotlistApi.Rule) {
  editTarget.value = rule;
  form.display_name = rule.display_name;
  form.max_count = rule.max_count;
  form.enabled = rule.enabled;
  form.normal_words = rule.normal_words.map((w) => ({ ...w }));
  form.required_words = rule.required_words.map((w) => ({ ...w }));
  form.exclude_words = rule.exclude_words.map((w) => ({ ...w }));
  previewResult.value = null;
  editModalOpen.value = true;
}

async function submitEdit() {
  if (!form.normal_words.length && !form.required_words.length) {
    message.warning('普通词 / 必须词至少填一个，否则规则永远不会命中');
    return;
  }
  editSaving.value = true;
  try {
    const payload: HotlistApi.RuleParams = {
      display_name: form.display_name.trim(),
      max_count: form.max_count,
      enabled: form.enabled,
      normal_words: form.normal_words,
      required_words: form.required_words,
      exclude_words: form.exclude_words,
    };
    if (editTarget.value) {
      const updated = await updateHotlistRuleApi(editTarget.value.id, payload);
      const idx = rules.value.findIndex((r) => r.id === updated.id);
      if (idx >= 0) rules.value[idx] = updated;
    } else {
      const created = await createTopicRuleApi(props.topicId, payload);
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
    previewResult.value = await previewTopicRuleApi(props.topicId, {
      normal_words: form.normal_words,
      required_words: form.required_words,
      exclude_words: form.exclude_words,
      sample_limit: 10,
    });
  } catch (e: any) {
    message.error(`试跑失败：${e.response?.data?.detail || e.message}`);
  } finally {
    previewLoading.value = false;
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
    const result = await importTopicRulesApi(props.topicId, importText.value);
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

onMounted(fetchRules);
</script>

<template>
  <div>
    <div class="mb-4 flex flex-wrap items-center justify-between gap-2">
      <p class="text-xs text-[hsl(var(--muted-foreground))]">
        普通词 OR / 必须词 AND / 排除词 NOT，支持正则和限量；保存前可试跑看命中样例。源范围由主题的「数据源」决定
      </p>
      <div class="flex items-center gap-2">
        <button
          class="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-1.5 text-xs text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
          @click="importModalOpen = true"
        >
          批量导入
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

    <!-- 词组规则卡片 -->
    <div v-if="!loading && groupRules.length === 0" class="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-12 text-center">
      <p class="text-sm font-semibold text-[hsl(var(--foreground))]">本主题还没有关键词规则</p>
      <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">→ 报告将按源全量分析（不按关键词过滤）。配了规则后只有命中的条目才会进报告</p>
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

        <FormItem label="最多显示条数（0 = 不限）">
          <InputNumber v-model:value="form.max_count" :min="0" class="w-full" />
        </FormItem>

        <FormItem label="启用">
          <Switch v-model:checked="form.enabled" />
        </FormItem>

        <div class="mb-3 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3">
          <div class="mb-2 flex items-center justify-between">
            <span class="text-xs font-semibold text-[hsl(var(--foreground))]">试跑（用主题的源 + 今天已抓数据，不落库）</span>
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

    <!-- 批量导入弹窗 -->
    <Modal v-model:open="importModalOpen" title="批量导入（TrendRadar 格式文本）" :footer="null" width="560px">
      <p class="mb-2 text-xs text-[hsl(var(--muted-foreground))]">
        空行分组；+必须词、!排除词、@限量、/正则/、"词 => 别名"、[组别名] 均支持；导入的词组归入本主题
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
  </div>
</template>
