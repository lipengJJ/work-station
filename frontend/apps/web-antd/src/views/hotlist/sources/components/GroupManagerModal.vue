<script lang="ts" setup>
import type { HotlistApi } from '#/api/core/hotlist';

import { onMounted, ref } from 'vue';

import { Form, FormItem, Input, InputNumber, message, Modal } from 'ant-design-vue';
import { Lock, Plus } from 'lucide-vue-next';

import {
  createSourceGroupApi,
  deleteSourceGroupApi,
  listSourceGroupsApi,
  updateSourceGroupApi,
} from '#/api/core/hotlist';

const open = defineModel<boolean>('open', { default: false });

const emit = defineEmits<{ changed: [] }>();

const groups = ref<HotlistApi.SourceGroup[]>([]);
const loading = ref(false);

const COLOR_OPTIONS = [
  '#f5222d',
  '#fa8c16',
  '#fadb14',
  '#52c41a',
  '#13c2c2',
  '#1677ff',
  '#722ed1',
  '#eb2f96',
  '#8c8c8c',
];

async function fetchGroups() {
  loading.value = true;
  try {
    groups.value = await listSourceGroupsApi();
  } catch (e: any) {
    message.error(`加载失败：${e.message}`);
  } finally {
    loading.value = false;
  }
}

// -------------------------------------------------------------- 新建 ----
const createOpen = ref(false);
const createForm = ref({ name: '', description: '', color: '#1677ff', sort_order: 0 });
const createSaving = ref(false);

function openCreate() {
  createForm.value = { name: '', description: '', color: '#1677ff', sort_order: groups.value.length };
  createOpen.value = true;
}

async function submitCreate() {
  if (!createForm.value.name.trim()) {
    message.warning('请填写分组名');
    return;
  }
  createSaving.value = true;
  try {
    await createSourceGroupApi(createForm.value);
    message.success('已创建');
    createOpen.value = false;
    await fetchGroups();
    emit('changed');
  } catch (e: any) {
    message.error(`创建失败：${e.response?.data?.detail || e.message}`);
  } finally {
    createSaving.value = false;
  }
}

// -------------------------------------------------------------- 编辑 ----
const editTarget = ref<HotlistApi.SourceGroup | null>(null);
const editModalOpen = ref(false);
const editForm = ref({ name: '', description: '', color: '', sort_order: 0 });
const editSaving = ref(false);

function openEdit(group: HotlistApi.SourceGroup) {
  editTarget.value = group;
  editForm.value = {
    name: group.name,
    description: group.description,
    color: group.color || '#1677ff',
    sort_order: group.sort_order,
  };
  editModalOpen.value = true;
}

async function submitEdit() {
  if (!editTarget.value || !editForm.value.name.trim()) return;
  editSaving.value = true;
  try {
    await updateSourceGroupApi(editTarget.value.id, editForm.value);
    message.success('已保存');
    editModalOpen.value = false;
    editTarget.value = null;
    await fetchGroups();
    emit('changed');
  } catch (e: any) {
    message.error(`保存失败：${e.response?.data?.detail || e.message}`);
  } finally {
    editSaving.value = false;
  }
}

// -------------------------------------------------------------- 删除 ----
function removeGroup(group: HotlistApi.SourceGroup) {
  Modal.confirm({
    title: `删除分组「${group.name}」？`,
    content: `组内 ${group.source_count} 个源将移回「未分组」（源本身不会删除）。`,
    okType: 'danger',
    async onOk() {
      try {
        await deleteSourceGroupApi(group.id);
        message.success('已删除');
        await fetchGroups();
        emit('changed');
      } catch (e: any) {
        message.error(`删除失败：${e.response?.data?.detail || e.message}`);
      }
    },
  });
}

onMounted(fetchGroups);
</script>

<template>
  <Modal v-model:open="open" title="分组管理" :footer="null" width="560px">
    <div class="mb-3 flex justify-end">
      <button
        class="flex items-center gap-1 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500"
        @click="openCreate"
      >
        <Plus class="size-3.5" />
        新建分组
      </button>
    </div>

    <div v-if="loading" class="py-8 text-center text-xs text-[hsl(var(--muted-foreground))]">加载中…</div>
    <div v-else class="space-y-2">
      <div
        v-for="group in groups"
        :key="group.id"
        class="flex items-center gap-3 rounded-xl border border-[hsl(var(--border))] px-3 py-2.5"
      >
        <span
          class="h-3.5 w-3.5 shrink-0 rounded-full"
          :style="{ backgroundColor: group.color || '#8c8c8c' }"
        ></span>
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-1.5 text-sm font-semibold text-[hsl(var(--foreground))]">
            {{ group.name }}
            <Lock v-if="group.is_builtin" class="size-3 text-[hsl(var(--muted-foreground))]" />
          </div>
          <div class="text-[11px] text-[hsl(var(--muted-foreground))]">
            {{ group.source_count }} 个源{{ group.description ? ` · ${group.description}` : '' }}
          </div>
        </div>
        <button
          class="rounded px-2 py-1 text-[11px] text-[hsl(var(--muted-foreground))] hover:text-indigo-400"
          @click="openEdit(group)"
        >
          编辑
        </button>
        <button
          class="rounded px-2 py-1 text-[11px] text-[hsl(var(--muted-foreground))] hover:text-rose-400 disabled:opacity-40"
          :disabled="group.is_builtin"
          :title="group.is_builtin ? '内置分组不允许删除' : ''"
          @click="removeGroup(group)"
        >
          删除
        </button>
      </div>
      <div v-if="groups.length === 0" class="py-8 text-center text-xs text-[hsl(var(--muted-foreground))]">
        还没有分组
      </div>
    </div>

    <!-- 新建分组弹窗 -->
    <Modal v-model:open="createOpen" title="新建分组" :footer="null" width="440px">
      <Form layout="vertical">
        <FormItem label="分组名" required>
          <Input v-model:value="createForm.name" placeholder="如：股票财经 / AI 工具" :maxlength="64" />
        </FormItem>
        <FormItem label="描述">
          <Input v-model:value="createForm.description" placeholder="这个分组装什么源" />
        </FormItem>
        <FormItem label="排序">
          <InputNumber v-model:value="createForm.sort_order" :min="0" class="w-full" />
        </FormItem>
        <FormItem label="颜色">
          <div class="flex flex-wrap gap-2">
            <button
              v-for="c in COLOR_OPTIONS"
              :key="c"
              class="h-6 w-6 rounded-full border-2"
              :class="createForm.color === c ? 'border-[hsl(var(--foreground))]' : 'border-transparent'"
              :style="{ backgroundColor: c }"
              @click="createForm.color = c"
            ></button>
          </div>
        </FormItem>
        <div class="flex justify-end gap-2">
          <button class="rounded-lg border border-[hsl(var(--border))] px-3 py-1.5 text-xs" @click="createOpen = false">取消</button>
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

    <!-- 编辑分组弹窗 -->
    <Modal v-model:open="editModalOpen" title="编辑分组" :footer="null" width="440px">
      <Form layout="vertical">
        <FormItem label="分组名" required>
          <Input v-model:value="editForm.name" :maxlength="64" />
        </FormItem>
        <FormItem label="描述">
          <Input v-model:value="editForm.description" />
        </FormItem>
        <FormItem label="排序">
          <InputNumber v-model:value="editForm.sort_order" :min="0" class="w-full" />
        </FormItem>
        <FormItem label="颜色">
          <div class="flex flex-wrap gap-2">
            <button
              v-for="c in COLOR_OPTIONS"
              :key="c"
              class="h-6 w-6 rounded-full border-2"
              :class="editForm.color === c ? 'border-[hsl(var(--foreground))]' : 'border-transparent'"
              :style="{ backgroundColor: c }"
              @click="editForm.color = c"
            ></button>
          </div>
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
  </Modal>
</template>
