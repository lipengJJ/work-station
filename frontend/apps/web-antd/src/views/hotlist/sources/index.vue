<script lang="ts" setup>
import type { HotlistApi } from '#/api/core/hotlist';

import { computed, onMounted, reactive, ref } from 'vue';

import { Page } from '@vben/common-ui';

import {
  Form,
  FormItem,
  Input,
  message,
  Modal,
  Select,
  Switch,
  Tooltip,
} from 'ant-design-vue';
import { ArrowLeft, FolderInput, Layers, Plus, Upload } from 'lucide-vue-next';

import GroupManagerModal from './components/GroupManagerModal.vue';

import {
  batchSourcesApi,
  createHotlistSourceApi,
  deleteHotlistSourceApi,
  importSourcesOpmlApi,
  listHotlistSourcesApi,
  listSourceGroupsApi,
  updateHotlistSourceApi,
} from '#/api/core/hotlist';

const KIND_LABEL: Record<HotlistApi.SourceKind, string> = {
  hotlist: '中文热榜',
  tech: '技术源',
};

function statusInfo(source: HotlistApi.Source) {
  if (!source.enabled) return { label: '已停用', dot: 'bg-slate-500', text: 'text-[hsl(var(--muted-foreground))]' };
  if (source.last_status === 'failed') return { label: `失败（连续 ${source.consecutive_failures} 次）`, dot: 'bg-rose-500', text: 'text-rose-400' };
  if (source.last_status === 'success') return { label: '正常', dot: 'bg-emerald-400', text: 'text-emerald-400' };
  return { label: '待抓取', dot: 'bg-slate-500', text: 'text-[hsl(var(--muted-foreground))]' };
}

// -------------------------------------------------------------- 数据 ----
const allSources = ref<HotlistApi.Source[]>([]);
const groups = ref<HotlistApi.SourceGroup[]>([]);
const loading = ref(false);
type FilterKey = 'all' | 'ungrouped' | number;
const activeFilter = ref<FilterKey>('all');

// -------------------------------------------------------------- 分组卡片视图 ----
// 默认只看分组，不关心具体某条 RSS 源；点进某个分组才展开该组的源表格。
const viewMode = ref<'groups' | 'table'>('groups');

function healthSummary(sources: HotlistApi.Source[]) {
  let failed = 0;
  let ok = 0;
  let pending = 0;
  for (const s of sources) {
    if (!s.enabled) continue;
    if (s.last_status === 'failed') failed++;
    else if (s.last_status === 'success') ok++;
    else pending++;
  }
  return { failed, ok, pending };
}

const groupCards = computed(() => {
  const ungroupedSources = allSources.value.filter((s) => s.group_id === null || s.group_id === undefined);
  const cards = groups.value.map((g) => {
    const sources = allSources.value.filter((s) => s.group_id === g.id);
    return {
      key: g.id as FilterKey,
      name: g.name,
      color: g.color || '#8c8c8c',
      count: sources.length,
      enabledCount: sources.filter((s) => s.enabled).length,
      ...healthSummary(sources),
    };
  });
  cards.push({
    key: 'ungrouped',
    name: '未分组',
    color: '#8c8c8c',
    count: ungroupedSources.length,
    enabledCount: ungroupedSources.filter((s) => s.enabled).length,
    ...healthSummary(ungroupedSources),
  });
  return cards;
});

function enterGroup(key: FilterKey) {
  activeFilter.value = key;
  viewMode.value = 'table';
}

function backToGroups() {
  viewMode.value = 'groups';
}

const groupById = computed(() => new Map(groups.value.map((g) => [g.id, g])));

const filteredSources = computed(() => {
  if (activeFilter.value === 'all') return allSources.value;
  if (activeFilter.value === 'ungrouped') {
    return allSources.value.filter((s) => s.group_id === null || s.group_id === undefined);
  }
  return allSources.value.filter((s) => s.group_id === activeFilter.value);
});

const filterTabs = computed(() => {
  const total = allSources.value.length;
  const ungrouped = allSources.value.filter((s) => s.group_id === null || s.group_id === undefined).length;
  return [
    { key: 'all' as FilterKey, label: `全部（${total}）` },
    { key: 'ungrouped' as FilterKey, label: `未分组（${ungrouped}）` },
    ...groups.value.map((g) => ({
      key: g.id as FilterKey,
      label: `${g.name}（${g.source_count}）`,
    })),
  ];
});

async function fetchSources() {
  loading.value = true;
  try {
    const [sources, groupList] = await Promise.all([listHotlistSourcesApi(), listSourceGroupsApi()]);
    allSources.value = sources;
    groups.value = groupList;
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

// -------------------------------------------------------------- 多选 + 批量 ----
const selectedKeys = ref<string[]>([]);
const batchMoveOpen = ref(false);
const batchMoveGroup = ref<number | undefined>(undefined);
const batchMoving = ref(false);

function groupLabel(id: number | null | undefined) {
  if (id === null || id === undefined) return '未分组';
  return groupById.value.get(id)?.name || `分组 ${id}`;
}

async function batchSetEnabled(enabled: boolean) {
  if (selectedKeys.value.length === 0) {
    message.warning('请先勾选源');
    return;
  }
  try {
    const res = await batchSourcesApi({ source_ids: selectedKeys.value, enabled });
    message.success(`已${enabled ? '启用' : '停用'} ${res.enabled_changed} 个源`);
    selectedKeys.value = [];
    fetchSources();
  } catch (e: any) {
    message.error(`操作失败：${e.response?.data?.detail || e.message}`);
  }
}

async function submitBatchMove() {
  if (selectedKeys.value.length === 0) {
    message.warning('请先勾选源');
    return;
  }
  batchMoving.value = true;
  try {
    const res = await batchSourcesApi({
      source_ids: selectedKeys.value,
      group_id: batchMoveGroup.value ?? null,
    });
    message.success(`已移动 ${res.moved} 个源`);
    batchMoveOpen.value = false;
    batchMoveGroup.value = undefined;
    selectedKeys.value = [];
    fetchSources();
  } catch (e: any) {
    message.error(`移动失败：${e.response?.data?.detail || e.message}`);
  } finally {
    batchMoving.value = false;
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
    const idx = allSources.value.findIndex((s) => s.id === updated.id);
    if (idx >= 0) allSources.value[idx] = updated;
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
    allSources.value.push(created);
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
        allSources.value = allSources.value.filter((s) => s.id !== source.id);
        message.success('已删除');
      } catch (e: any) {
        message.error(`删除失败：${e.message}`);
      }
    },
  });
}

// -------------------------------------------------------------- OPML 导入 ----
const importModalOpen = ref(false);
const importFileText = ref('');
const importUrl = ref('');
const importGroupId = ref<number | undefined>(undefined);
const importSaving = ref(false);

function readOpmlFile(file: File) {
  const reader = new FileReader();
  reader.onload = () => {
    importFileText.value = String(reader.result || '');
  };
  reader.readAsText(file);
  return false;
}

async function submitImport() {
  if (!importFileText.value.trim() && !importUrl.value.trim()) {
    message.warning('请上传 .opml 文件或填写 OPML 的 URL');
    return;
  }
  importSaving.value = true;
  try {
    const res = await importSourcesOpmlApi({
      content: importFileText.value || undefined,
      opml_url: importUrl.value || undefined,
      group_id: importGroupId.value ?? null,
    });
    message.success(`导入完成：新增 ${res.created.length} 个、复用 ${res.reused.length} 个、跳过 ${res.skipped} 个`);
    importModalOpen.value = false;
    importFileText.value = '';
    importUrl.value = '';
    importGroupId.value = undefined;
    fetchSources();
  } catch (e: any) {
    message.error(`导入失败：${e.response?.data?.detail || e.message}`);
  } finally {
    importSaving.value = false;
  }
}

// -------------------------------------------------------------- 分组管理 ----
const groupManagerOpen = ref(false);

onMounted(fetchSources);
</script>

<template>
  <Page :auto-content-height="true" content-class="!p-0">
    <div class="custom-scrollbar flex h-full flex-1 flex-col overflow-y-auto bg-[hsl(var(--background-deep))] p-6 select-none">
      <div class="mb-6 shrink-0 flex items-start justify-between gap-3">
        <div>
          <h1 class="text-xl font-extrabold text-[hsl(var(--foreground))]">热点聚合 · 源管理</h1>
          <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">
            分组管理 / 批量开关 / OPML 批量导入；RSS 类源可在此新增，无需改代码
          </p>
        </div>
        <div class="flex shrink-0 items-center gap-2">
          <button
            class="flex items-center gap-1 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-1.5 text-xs text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
            @click="importModalOpen = true"
          >
            <Upload class="h-3.5 w-3.5" />
            批量导入 OPML
          </button>
          <button
            class="flex items-center gap-1 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-1.5 text-xs text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
            @click="groupManagerOpen = true"
          >
            <Layers class="h-3.5 w-3.5" />
            分组管理
          </button>
          <button
            class="flex items-center gap-1 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500"
            @click="openCreate"
          >
            <Plus class="h-3.5 w-3.5" />
            新建 RSS 源
          </button>
        </div>
      </div>

      <!-- ===================== 分组卡片视图（默认） ===================== -->
      <div v-if="viewMode === 'groups'">
        <div class="mb-4 shrink-0 flex items-center justify-between">
          <p class="text-xs text-[hsl(var(--muted-foreground))]">点击分组查看组内的源；不关心具体某条源时看这一层就够了</p>
          <button
            class="shrink-0 text-xs text-[hsl(var(--muted-foreground))] hover:text-indigo-400"
            @click="enterGroup('all')"
          >
            查看全部源列表（{{ allSources.length }}）→
          </button>
        </div>
        <div v-if="!loading && groupCards.length === 0" class="rounded-2xl border border-dashed border-[hsl(var(--border))] p-12 text-center text-sm text-[hsl(var(--muted-foreground))]">
          还没有分组，先在右上角「分组管理」里建一个
        </div>
        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <div
            v-for="card in groupCards"
            :key="String(card.key)"
            class="cursor-pointer rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 shadow-xl transition-colors hover:border-indigo-500/50"
            @click="enterGroup(card.key)"
          >
            <div class="mb-2 flex items-center gap-2">
              <span class="h-3 w-3 shrink-0 rounded-full" :style="{ backgroundColor: card.color }"></span>
              <span class="truncate text-sm font-bold text-[hsl(var(--foreground))]">{{ card.name }}</span>
              <span class="ml-auto shrink-0 text-xs text-[hsl(var(--muted-foreground))]">{{ card.count }} 个源</span>
            </div>
            <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-[hsl(var(--muted-foreground))]">
              <span>启用 <b class="text-[hsl(var(--foreground))]">{{ card.enabledCount }}</b></span>
              <span v-if="card.ok" class="text-emerald-400">正常 {{ card.ok }}</span>
              <span v-if="card.failed" class="text-rose-400">失败 {{ card.failed }}</span>
              <span v-if="card.pending" class="text-slate-400">待抓取 {{ card.pending }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- ===================== 分组筛选 Tab + 源表格 ===================== -->
      <template v-else>
        <div class="mb-4 shrink-0 flex flex-wrap items-center gap-2">
          <button
            class="flex items-center gap-1 rounded-lg border border-[hsl(var(--border))] px-2.5 py-1.5 text-xs text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
            @click="backToGroups"
          >
            <ArrowLeft class="h-3.5 w-3.5" />
            分组
          </button>
          <button
            v-for="tab in filterTabs"
            :key="String(tab.key)"
            class="rounded-lg border px-3 py-1.5 text-xs transition-colors"
            :class="
              activeFilter === tab.key
                ? 'border-indigo-500 bg-indigo-500/10 text-indigo-400'
                : 'border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'
            "
            @click="activeFilter = tab.key"
          >
            {{ tab.label }}
          </button>
        </div>

        <!-- 批量操作条 -->
      <div
        v-if="selectedKeys.length > 0"
        class="mb-4 flex shrink-0 items-center gap-3 rounded-xl border border-indigo-500/30 bg-indigo-500/10 px-4 py-2.5 text-xs"
      >
        <span class="font-semibold text-indigo-400">已选 {{ selectedKeys.length }} 个源</span>
        <button class="rounded border border-[hsl(var(--border))] px-2.5 py-1 text-[11px] hover:text-indigo-400" @click="batchMoveOpen = true">
          <FolderInput class="mr-1 inline size-3" />
          移动到分组
        </button>
        <button class="rounded border border-[hsl(var(--border))] px-2.5 py-1 text-[11px] hover:text-emerald-400" @click="batchSetEnabled(true)">批量启用</button>
        <button class="rounded border border-[hsl(var(--border))] px-2.5 py-1 text-[11px] hover:text-amber-400" @click="batchSetEnabled(false)">批量停用</button>
        <button class="ml-auto text-[11px] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]" @click="selectedKeys = []">取消选择</button>
      </div>

      <div class="shrink-0 overflow-hidden rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] shadow-xl">
        <div v-if="!loading && filteredSources.length === 0" class="flex flex-col items-center justify-center gap-2 p-12 text-center">
          <p class="text-sm font-semibold text-[hsl(var(--foreground))]">暂无源</p>
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full text-left text-xs">
            <thead class="border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] font-mono text-[11px] text-[hsl(var(--muted-foreground))] uppercase">
              <tr>
                <th class="w-10 px-2 py-3">
                  <input
                    type="checkbox"
                    class="accent-indigo-500"
                    :checked="filteredSources.length > 0 && filteredSources.every((s) => selectedKeys.includes(s.id))"
                    @change="(e) => {
                      const checked = (e.target as HTMLInputElement).checked;
                      selectedKeys = checked ? filteredSources.map((s) => s.id) : [];
                    }"
                  />
                </th>
                <th class="px-4 py-3">源</th>
                <th class="px-4 py-3">分组</th>
                <th class="px-4 py-3">类型</th>
                <th class="px-4 py-3">抓取频率</th>
                <th class="px-4 py-3">状态</th>
                <th class="px-4 py-3">累计条数</th>
                <th class="px-4 py-3">启用</th>
                <th class="px-4 py-3 text-right">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-[hsl(var(--border))]">
              <tr v-for="source in filteredSources" :key="source.id" class="transition-colors hover:bg-[hsl(var(--accent))]">
                <td class="px-2 py-3">
                  <input
                    type="checkbox"
                    class="accent-indigo-500"
                    :value="source.id"
                    v-model="selectedKeys"
                  />
                </td>
                <td class="px-4 py-3">
                  <div class="font-semibold text-[hsl(var(--foreground))]">{{ source.name || source.id }}</div>
                  <div class="text-[11px] text-[hsl(var(--muted-foreground))]">{{ source.id }} · {{ source.adapter }}</div>
                </td>
                <td class="px-4 py-3">
                  <span
                    class="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px]"
                    :style="{
                      backgroundColor: source.group_id ? `${groupById.get(source.group_id)?.color || '#8c8c8c'}22` : 'transparent',
                      color: source.group_id ? groupById.get(source.group_id)?.color || '#8c8c8c' : 'hsl(var(--muted-foreground))',
                      border: source.group_id ? `1px solid ${groupById.get(source.group_id)?.color || '#8c8c8c'}55` : '1px dashed hsl(var(--border))',
                    }"
                  >
                    {{ groupLabel(source.group_id) }}
                  </span>
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
      </template>
    </div>

    <!-- 移动到分组弹窗 -->
    <Modal v-model:open="batchMoveOpen" title="移动到分组" :footer="null" width="400px">
      <Form layout="vertical">
        <FormItem label="目标分组（选择「未分组」= 移出分组）">
          <Select
            v-model:value="batchMoveGroup"
            allow-clear
            placeholder="未分组"
            :options="groups.map((g) => ({ value: g.id, label: `${g.name}（${g.source_count}）` }))"
          />
        </FormItem>
        <p class="mb-3 text-xs text-[hsl(var(--muted-foreground))]">将移动 {{ selectedKeys.length }} 个源</p>
        <div class="flex justify-end gap-2">
          <button class="rounded-lg border border-[hsl(var(--border))] px-3 py-1.5 text-xs" @click="batchMoveOpen = false">取消</button>
          <button
            :disabled="batchMoving"
            class="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500 disabled:opacity-50"
            @click="submitBatchMove"
          >
            移动
          </button>
        </div>
      </Form>
    </Modal>

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

    <!-- OPML 批量导入 -->
    <Modal v-model:open="importModalOpen" title="批量导入 OPML 到分组" :footer="null" width="480px">
      <Form layout="vertical">
        <FormItem label="上传 .opml 文件">
          <input type="file" accept=".opml,.xml" class="text-xs" @change="(e) => readOpmlFile((e.target as HTMLInputElement).files?.[0] as File)" />
        </FormItem>
        <FormItem label="或填写 OPML 的 URL">
          <Input v-model:value="importUrl" placeholder="https://example.com/feeds.opml" />
        </FormItem>
        <FormItem label="归入分组（可选）">
          <Select
            v-model:value="importGroupId"
            allow-clear
            placeholder="不归组"
            :options="groups.map((g) => ({ value: g.id, label: `${g.name}（${g.source_count}）` }))"
          />
        </FormItem>
        <div class="flex justify-end gap-2">
          <button class="rounded-lg border border-[hsl(var(--border))] px-3 py-1.5 text-xs" @click="importModalOpen = false">取消</button>
          <button
            :disabled="importSaving"
            class="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500 disabled:opacity-50"
            @click="submitImport"
          >
            导入
          </button>
        </div>
      </Form>
    </Modal>

    <GroupManagerModal v-model:open="groupManagerOpen" @changed="fetchSources" />
  </Page>
</template>
