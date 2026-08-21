<script lang="ts" setup>
import type { HotlistApi } from '#/api/core/hotlist';

import { onMounted, ref } from 'vue';

import { Form, FormItem, Input, message, Modal } from 'ant-design-vue';
import { ChevronDown, ChevronUp, Plus } from 'lucide-vue-next';

import {
  createGlobalFilterApi,
  deleteGlobalFilterApi,
  listGlobalFiltersApi,
} from '#/api/core/hotlist';

const expanded = ref(false);
const filters = ref<HotlistApi.Rule[]>([]);
const loading = ref(false);

async function fetchFilters() {
  loading.value = true;
  try {
    filters.value = await listGlobalFiltersApi();
  } catch (e: any) {
    message.error(`加载失败：${e.message}`);
  } finally {
    loading.value = false;
  }
}

async function removeFilter(rule: HotlistApi.Rule) {
  Modal.confirm({
    title: `删除全局过滤词「${rule.display_name}」？`,
    okType: 'danger',
    async onOk() {
      try {
        await deleteGlobalFilterApi(rule.id);
        filters.value = filters.value.filter((r) => r.id !== rule.id);
        message.success('已删除');
      } catch (e: any) {
        message.error(`删除失败：${e.message}`);
      }
    },
  });
}

const createOpen = ref(false);
const word = ref('');
const saving = ref(false);

async function submitCreate() {
  const w = word.value.trim();
  if (!w) return;
  saving.value = true;
  try {
    const created = await createGlobalFilterApi({ word: w });
    filters.value.push(created);
    message.success('已创建');
    createOpen.value = false;
    word.value = '';
  } catch (e: any) {
    message.error(`创建失败：${e.response?.data?.detail || e.message}`);
  } finally {
    saving.value = false;
  }
}

onMounted(fetchFilters);
</script>

<template>
  <div class="mb-5 rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
    <div class="flex items-center justify-between gap-2">
      <button
        class="flex items-center gap-1.5 text-sm font-semibold text-[hsl(var(--foreground))]"
        @click="expanded = !expanded"
      >
        <ChevronDown v-if="!expanded" class="size-4 text-[hsl(var(--muted-foreground))]" />
        <ChevronUp v-else class="size-4 text-[hsl(var(--muted-foreground))]" />
        全局过滤词（对所有主题生效）
        <span v-if="filters.length" class="rounded bg-rose-500/15 px-1.5 py-0.5 text-xs text-rose-400">
          {{ filters.length }}
        </span>
      </button>
      <button
        class="flex items-center gap-1 rounded-lg bg-rose-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-rose-500"
        @click="createOpen = true"
      >
        <Plus class="size-3.5" />
        新建
      </button>
    </div>

    <div v-if="expanded" class="mt-3">
      <p class="mb-2 text-xs text-[hsl(var(--muted-foreground))]">
        命中即从所有主题的词组匹配结果里剔除（如「广告」「软广」）；纯文本，不支持正则
      </p>
      <div v-if="loading" class="text-xs text-[hsl(var(--muted-foreground))]">加载中…</div>
      <div v-else-if="filters.length === 0" class="rounded-lg border border-dashed border-[hsl(var(--border))] px-3 py-4 text-center text-xs text-[hsl(var(--muted-foreground))]">
        还没有全局过滤词
      </div>
      <div v-else class="flex flex-wrap gap-2">
        <span
          v-for="gf in filters"
          :key="gf.id"
          class="flex items-center gap-1.5 rounded-lg bg-rose-500/10 px-2.5 py-1 text-xs text-rose-400"
        >
          {{ gf.display_name }}
          <button class="text-rose-400/60 hover:text-rose-400" @click="removeFilter(gf)">×</button>
        </span>
      </div>
    </div>

    <Modal v-model:open="createOpen" title="新建全局过滤词" :footer="null" width="400px">
      <Form layout="vertical">
        <FormItem label="词（纯文本，不支持正则，命中即从所有词组结果中剔除）">
          <Input v-model:value="word" placeholder="例如：广告" @press-enter="submitCreate" />
        </FormItem>
        <div class="flex justify-end gap-2">
          <button class="rounded-lg border border-[hsl(var(--border))] px-3 py-1.5 text-xs" @click="createOpen = false">取消</button>
          <button
            :disabled="saving"
            class="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500 disabled:opacity-50"
            @click="submitCreate"
          >
            创建
          </button>
        </div>
      </Form>
    </Modal>
  </div>
</template>
