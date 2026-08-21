<script lang="ts" setup>
import type { HotlistApi } from '#/api/core/hotlist';

import { computed, ref, watch } from 'vue';

import { message, Modal } from 'ant-design-vue';

import { listHotlistSourcesApi, listSourceGroupsApi } from '#/api/core/hotlist';
import { batchSetTopicSourcesApi } from '#/api/core/topics';

defineOptions({ inheritAttrs: false });

const props = defineProps<{ currentEnabledIds: string[]; topicId: number }>();
const emit = defineEmits<{ applied: [] }>();
const open = defineModel<boolean>('open', { default: false });

const loading = ref(false);
const saving = ref(false);
const groups = ref<HotlistApi.SourceGroup[]>([]);
const allSources = ref<HotlistApi.Source[]>([]);
const selectedIds = ref<string[]>([]);

async function fetchData() {
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

watch(open, (v) => {
  if (v) {
    selectedIds.value = [...props.currentEnabledIds];
    fetchData();
  }
});

const groupedView = computed(() => {
  const list: { key: string; label: string; sources: HotlistApi.Source[] }[] = [];
  const map = new Map<number, HotlistApi.Source[]>();
  const ungrouped: HotlistApi.Source[] = [];
  for (const s of allSources.value) {
    if (s.group_id === null || s.group_id === undefined) ungrouped.push(s);
    else {
      if (!map.has(s.group_id)) map.set(s.group_id, []);
      map.get(s.group_id)!.push(s);
    }
  }
  for (const g of groups.value) {
    const items = map.get(g.id) || [];
    if (items.length) list.push({ key: `g-${g.id}`, label: g.name, sources: items });
  }
  if (ungrouped.length) list.push({ key: 'ungrouped', label: '未分组', sources: ungrouped });
  return list;
});

function isGroupAllSelected(sources: HotlistApi.Source[]) {
  return sources.length > 0 && sources.every((s) => selectedIds.value.includes(s.id));
}
function toggleGroup(sources: HotlistApi.Source[], checked: boolean) {
  const ids = sources.map((s) => s.id);
  const set = new Set(selectedIds.value);
  if (checked) ids.forEach((id) => set.add(id));
  else ids.forEach((id) => set.delete(id));
  selectedIds.value = [...set];
}

async function submit() {
  saving.value = true;
  try {
    const res = await batchSetTopicSourcesApi(props.topicId, { mode: 'set', source_ids: selectedIds.value });
    message.success(`已更新 ${res.changed} 个源（当前启用 ${res.enabled_count} 个）`);
    open.value = false;
    emit('applied');
  } catch (e: any) {
    message.error(`保存失败：${e.message}`);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <Modal v-model:open="open" title="从分组关联源" :footer="null" width="640px">
    <p class="mb-3 text-xs text-[hsl(var(--muted-foreground))]">
      勾选的源会覆盖本主题当前启用的源（含之前 OPML 导入或手动关联的）；按分组批量勾选，来自「源管理」的分组
    </p>
    <div v-if="loading" class="py-8 text-center text-xs text-[hsl(var(--muted-foreground))]">加载中…</div>
    <div v-else class="max-h-[50vh] overflow-y-auto pr-1">
      <div v-if="groupedView.length === 0" class="rounded-lg border border-dashed border-[hsl(var(--border))] px-3 py-8 text-center text-xs text-[hsl(var(--muted-foreground))]">
        还没有源，先去「源管理」添加
      </div>
      <div v-for="group in groupedView" :key="group.key" class="mb-4">
        <div class="mb-1.5 flex items-center justify-between">
          <span class="text-xs font-semibold text-[hsl(var(--foreground))]">{{ group.label }}（{{ group.sources.length }}）</span>
          <label class="flex items-center gap-1 text-[11px] text-[hsl(var(--muted-foreground))]">
            <input
              type="checkbox"
              class="accent-indigo-500"
              :checked="isGroupAllSelected(group.sources)"
              @change="(e) => toggleGroup(group.sources, (e.target as HTMLInputElement).checked)"
            />
            全选本组
          </label>
        </div>
        <div class="flex flex-wrap gap-2">
          <label
            v-for="s in group.sources"
            :key="s.id"
            class="flex cursor-pointer items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs"
            :class="selectedIds.includes(s.id) ? 'border-indigo-500 bg-indigo-500/10 text-indigo-400' : 'border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))]'"
          >
            <input v-model="selectedIds" type="checkbox" class="accent-indigo-500" :value="s.id" />
            {{ s.name || s.id }}
          </label>
        </div>
      </div>
    </div>
    <div class="mt-4 flex items-center justify-between border-t border-[hsl(var(--border))] pt-3">
      <span class="text-xs text-[hsl(var(--muted-foreground))]">已选 {{ selectedIds.length }} 个源</span>
      <div class="flex justify-end gap-2">
        <button class="rounded-lg border border-[hsl(var(--border))] px-3 py-1.5 text-xs" @click="open = false">取消</button>
        <button
          :disabled="saving"
          class="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500 disabled:opacity-50"
          @click="submit"
        >
          应用
        </button>
      </div>
    </div>
  </Modal>
</template>
