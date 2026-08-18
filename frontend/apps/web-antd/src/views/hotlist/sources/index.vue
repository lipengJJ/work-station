<script lang="ts" setup>
import type { HotlistApi } from '#/api/core/hotlist';

import { onMounted, reactive, ref } from 'vue';

import { Page } from '@vben/common-ui';

import { Form, FormItem, Input, message, Modal, Switch, Tooltip } from 'ant-design-vue';
import { Plus } from 'lucide-vue-next';

import {
  createHotlistSourceApi,
  deleteHotlistSourceApi,
  listHotlistSourcesApi,
  updateHotlistSourceApi,
} from '#/api/core/hotlist';

const KIND_LABEL: Record<HotlistApi.SourceKind, string> = {
  hotlist: '中文热榜',
  tech: '技术源',
};

function formatDateTime(iso: null | string) {
  if (!iso) return '—';
  return iso.slice(0, 16).replace('T', ' ');
}

function statusInfo(source: HotlistApi.Source) {
  if (!source.enabled) return { label: '已停用', dot: 'bg-slate-500', text: 'text-[hsl(var(--muted-foreground))]' };
  if (source.last_status === 'failed') return { label: `失败（连续 ${source.consecutive_failures} 次）`, dot: 'bg-rose-500', text: 'text-rose-400' };
  if (source.last_status === 'success') return { label: '正常', dot: 'bg-emerald-400', text: 'text-emerald-400' };
  return { label: '待抓取', dot: 'bg-slate-500', text: 'text-[hsl(var(--muted-foreground))]' };
}

// -------------------------------------------------------------- 列表 ----
const sources = ref<HotlistApi.Source[]>([]);
const loading = ref(false);

async function fetchSources() {
  loading.value = true;
  try {
    sources.value = await listHotlistSourcesApi();
  } catch (e: any) {
    message.error(`加载失败：${e.message}`);
  } finally {
    loading.value = false;
  }
}

async function toggleEnabled(source: HotlistApi.Source, enabled: boolean) {
  try {
    await updateHotlistSourceApi(source.id, { enabled });
    source.enabled = enabled;
    message.success(enabled ? '已启用' : '已停用');
  } catch (e: any) {
    message.error(`操作失败：${e.message}`);
  }
}

// -------------------------------------------------------------- 编辑 ----
const editModalOpen = ref(false);
const editTarget = ref<HotlistApi.Source | null>(null);
const editForm = reactive({ name: '', cron_expr: '', expected_domain: '' });
const editSaving = ref(false);

function openEdit(source: HotlistApi.Source) {
  editTarget.value = source;
  editForm.name = source.name;
  editForm.cron_expr = source.cron_expr;
  editForm.expected_domain = source.expected_domain;
  editModalOpen.value = true;
}

async function submitEdit() {
  if (!editTarget.value) return;
  editSaving.value = true;
  try {
    const updated = await updateHotlistSourceApi(editTarget.value.id, {
      name: editForm.name.trim() || undefined,
      cron_expr: editForm.cron_expr.trim() || undefined,
      expected_domain: editForm.expected_domain.trim(),
    });
    const idx = sources.value.findIndex((s) => s.id === updated.id);
    if (idx >= 0) sources.value[idx] = updated;
    message.success('已保存');
    editModalOpen.value = false;
  } catch (e: any) {
    message.error(`保存失败：${e.message}`);
  } finally {
    editSaving.value = false;
  }
}

// -------------------------------------------------------------- 新建（RSS）----
const createModalOpen = ref(false);
const createForm = reactive({ id: '', name: '', url: '', expected_domain: '', cron_expr: '*/30 * * * *' });
const createSaving = ref(false);

function openCreate() {
  createForm.id = '';
  createForm.name = '';
  createForm.url = '';
  createForm.expected_domain = '';
  createForm.cron_expr = '*/30 * * * *';
  createModalOpen.value = true;
}

async function submitCreate() {
  if (!createForm.id.trim() || !createForm.name.trim() || !createForm.url.trim()) {
    message.warning('请填写完整');
    return;
  }
  createSaving.value = true;
  try {
    const created = await createHotlistSourceApi({
      id: createForm.id.trim(),
      name: createForm.name.trim(),
      adapter: 'rss',
      adapter_params: { url: createForm.url.trim() },
      expected_domain: createForm.expected_domain.trim(),
      cron_expr: createForm.cron_expr.trim() || '*/30 * * * *',
    });
    sources.value.push(created);
    message.success('已创建');
    createModalOpen.value = false;
  } catch (e: any) {
    message.error(`创建失败：${e.message}`);
  } finally {
    createSaving.value = false;
  }
}

async function removeSource(source: HotlistApi.Source) {
  Modal.confirm({
    title: `删除源「${source.name}」？`,
    content: '删除后该源已抓取的历史条目仍会保留，只是不再继续抓取。',
    okType: 'danger',
    async onOk() {
      try {
        await deleteHotlistSourceApi(source.id);
        sources.value = sources.value.filter((s) => s.id !== source.id);
        message.success('已删除');
      } catch (e: any) {
        message.error(`删除失败：${e.message}`);
      }
    },
  });
}

onMounted(fetchSources);
</script>

<template>
  <Page :auto-content-height="true" content-class="!p-0">
    <div class="custom-scrollbar flex h-full flex-1 flex-col overflow-y-auto bg-[hsl(var(--background-deep))] p-6 select-none">
      <div class="mb-6 shrink-0 flex items-start justify-between gap-3">
        <div>
          <h1 class="text-xl font-extrabold text-[hsl(var(--foreground))]">热点聚合 · 源管理</h1>
          <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">
            开关 / 抓取频率 / 域名安全校验；RSS 类源可在此新增，无需改代码
          </p>
        </div>
        <button
          class="flex shrink-0 items-center gap-1 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500"
          @click="openCreate"
        >
          <Plus class="h-3.5 w-3.5" />
          新建 RSS 源
        </button>
      </div>

      <div class="shrink-0 overflow-hidden rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] shadow-xl">
        <div v-if="!loading && sources.length === 0" class="flex flex-col items-center justify-center gap-2 p-12 text-center">
          <p class="text-sm font-semibold text-[hsl(var(--foreground))]">暂无源</p>
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full text-left text-xs">
            <thead class="border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] font-mono text-[11px] text-[hsl(var(--muted-foreground))] uppercase">
              <tr>
                <th class="px-4 py-3">源</th>
                <th class="px-4 py-3">类型</th>
                <th class="px-4 py-3">抓取频率</th>
                <th class="px-4 py-3">状态</th>
                <th class="px-4 py-3">累计条数</th>
                <th class="px-4 py-3">最近成功</th>
                <th class="px-4 py-3">启用</th>
                <th class="px-4 py-3 text-right">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-[hsl(var(--border))]">
              <tr v-for="source in sources" :key="source.id" class="transition-colors hover:bg-[hsl(var(--accent))]">
                <td class="px-4 py-3">
                  <div class="font-semibold text-[hsl(var(--foreground))]">{{ source.name || source.id }}</div>
                  <div class="text-[11px] text-[hsl(var(--muted-foreground))]">{{ source.id }} · {{ source.adapter }}</div>
                </td>
                <td class="px-4 py-3 text-[hsl(var(--muted-foreground))]">{{ KIND_LABEL[source.source_kind] || source.source_kind }}</td>
                <td class="px-4 py-3 font-mono text-[hsl(var(--muted-foreground))]">{{ source.cron_expr }}</td>
                <td class="px-4 py-3">
                  <Tooltip :title="source.last_error || ''">
                    <span class="inline-flex items-center gap-1.5" :class="statusInfo(source).text">
                      <span class="h-1.5 w-1.5 rounded-full" :class="statusInfo(source).dot"></span>
                      {{ statusInfo(source).label }}
                    </span>
                  </Tooltip>
                </td>
                <td class="px-4 py-3 font-mono text-[hsl(var(--muted-foreground))]">{{ source.total_fetched }}</td>
                <td class="px-4 py-3 text-[hsl(var(--muted-foreground))]">{{ formatDateTime(source.last_success_at) }}</td>
                <td class="px-4 py-3">
                  <Switch size="small" :checked="source.enabled" @change="(v) => toggleEnabled(source, Boolean(v))" />
                </td>
                <td class="px-4 py-3 text-right">
                  <div class="flex items-center justify-end gap-3">
                    <button class="text-[11px] text-[hsl(var(--muted-foreground))] hover:text-indigo-400" @click="openEdit(source)">编辑</button>
                    <button class="text-[11px] text-[hsl(var(--muted-foreground))] hover:text-rose-400" @click="removeSource(source)">删除</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <Modal v-model:open="editModalOpen" title="编辑源" :footer="null" width="440px">
      <Form layout="vertical">
        <FormItem label="显示名">
          <Input v-model:value="editForm.name" placeholder="源显示名" />
        </FormItem>
        <FormItem label="cron 表达式">
          <Input v-model:value="editForm.cron_expr" placeholder="*/30 * * * *" />
        </FormItem>
        <FormItem label="期望域名（域名安全校验，留空跳过校验）">
          <Input v-model:value="editForm.expected_domain" placeholder="例如 weibo.com" />
        </FormItem>
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

    <Modal v-model:open="createModalOpen" title="新建 RSS 源" :footer="null" width="440px">
      <Form layout="vertical">
        <FormItem label="源 id（唯一，英文/数字/短横线）">
          <Input v-model:value="createForm.id" placeholder="例如 my-blog" />
        </FormItem>
        <FormItem label="显示名">
          <Input v-model:value="createForm.name" placeholder="源显示名" />
        </FormItem>
        <FormItem label="Feed 地址">
          <Input v-model:value="createForm.url" placeholder="https://example.com/feed.xml" />
        </FormItem>
        <FormItem label="期望域名（可选，留空跳过域名安全校验）">
          <Input v-model:value="createForm.expected_domain" placeholder="例如 example.com" />
        </FormItem>
        <FormItem label="cron 表达式">
          <Input v-model:value="createForm.cron_expr" />
        </FormItem>
        <div class="flex justify-end gap-2">
          <button class="rounded-lg border border-[hsl(var(--border))] px-3 py-1.5 text-xs" @click="createModalOpen = false">取消</button>
          <button
            :disabled="createSaving"
            class="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500 disabled:opacity-50"
            @click="submitCreate"
          >
            创建
          </button>
        </div>
      </Form>
    </Modal>
  </Page>
</template>
