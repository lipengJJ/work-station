<script lang="ts" setup>
import type { HotlistApi } from '#/api/core/hotlist';

import { ref, watch } from 'vue';

import { Form, FormItem, Input, message, Modal, Select } from 'ant-design-vue';
import { CheckCircle2, Plus, Upload } from 'lucide-vue-next';

import { createSourceGroupApi, importSourcesOpmlApi } from '#/api/core/hotlist';

const props = defineProps<{ groups: HotlistApi.SourceGroup[] }>();

const open = defineModel<boolean>('open', { default: false });

const emit = defineEmits<{ changed: [] }>();

const localGroups = ref<HotlistApi.SourceGroup[]>([]);
watch(
  () => props.groups,
  (groups) => {
    localGroups.value = [...groups];
  },
  { immediate: true },
);

const fileText = ref('');
const fileName = ref('');
// 一行一个 RSS/Atom 订阅地址；不要求是真正的 OPML 文档——用户手头常有的就是
// 散的 feed 地址，硬要求先包一层 OPML 外壳没有必要。
const feedUrlsText = ref('');
const groupId = ref<number | undefined>(undefined);
const saving = ref(false);
const createGroupOpen = ref(false);
const createGroupName = ref('');
const createGroupSaving = ref(false);

watch(open, (v) => {
  if (v) {
    fileText.value = '';
    fileName.value = '';
    feedUrlsText.value = '';
    groupId.value = undefined;
  }
});

function openCreateGroup() {
  createGroupName.value = '';
  createGroupOpen.value = true;
}

async function createGroup() {
  const name = createGroupName.value.trim();
  if (!name) {
    message.warning('请填写分组名');
    return;
  }
  createGroupSaving.value = true;
  try {
    const group = await createSourceGroupApi({
      name,
      color: '#1677ff',
      sort_order: localGroups.value.length,
      crawl_enabled: false,
    });
    localGroups.value = [...localGroups.value, group];
    groupId.value = group.id;
    createGroupOpen.value = false;
    emit('changed');
    message.success(`已创建分组「${group.name}」并选中`);
  } catch (e: any) {
    message.error(`创建失败：${e.response?.data?.detail || e.message}`);
  } finally {
    createGroupSaving.value = false;
  }
}

function readFile(file?: File) {
  if (!file) return;
  fileName.value = file.name;
  const reader = new FileReader();
  reader.onload = () => {
    fileText.value = String(reader.result || '');
  };
  reader.readAsText(file);
  return false;
}

async function submit() {
  const feedUrls = feedUrlsText.value.split('\n').map((s) => s.trim()).filter(Boolean);
  if (!fileText.value.trim() && feedUrls.length === 0) {
    message.warning('请上传 .opml 文件，或填写至少一个 RSS 订阅地址');
    return;
  }
  saving.value = true;
  try {
    const res = await importSourcesOpmlApi({
      content: fileText.value || undefined,
      feed_urls: feedUrls.length > 0 ? feedUrls : undefined,
      group_id: groupId.value ?? null,
    });
    message.success(`导入完成：新增 ${res.created.length} 个、复用 ${res.reused.length} 个、跳过 ${res.skipped} 个`);
    open.value = false;
    emit('changed');
  } catch (e: any) {
    message.error(`导入失败：${e.response?.data?.detail || e.message}`);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <Modal v-model:open="open" title="批量导入源到分组" :footer="null" width="520px">
    <Form layout="vertical">
      <div class="mx-auto w-full max-w-[400px]">
        <FormItem>
          <template #label>
            <span class="font-medium text-primary">上传 .opml 文件</span>
          </template>
          <label
            class="flex min-h-16 w-full cursor-pointer items-center justify-center gap-3 rounded-2xl border border-dashed border-primary/50 bg-primary/5 px-4 py-3 text-primary transition-all hover:border-primary hover:bg-primary/10"
          >
            <input
              type="file"
              accept=".opml,.xml"
              class="sr-only"
              @change="(e) => readFile((e.target as HTMLInputElement).files?.[0])"
            />
            <CheckCircle2 v-if="fileName" class="size-5 shrink-0" />
            <Upload v-else class="size-5 shrink-0" />
            <span class="min-w-0 text-sm font-medium">
              <span v-if="fileName" class="block truncate">{{ fileName }}</span>
              <span v-else>选择 OPML 文件</span>
              <span class="mt-0.5 block text-xs font-normal text-muted-foreground">
                {{ fileName ? '已选择，点击可重新选择' : '支持 .opml 或 .xml 文件' }}
              </span>
            </span>
          </label>
        </FormItem>
      </div>
      <div class="mx-auto w-full max-w-[400px]">
        <FormItem>
          <template #label>
            <span class="font-medium text-primary">或粘贴 RSS 订阅地址（支持多个，一行一个）</span>
          </template>
          <div class="w-full rounded-2xl border border-primary/30 bg-primary/5 p-2 transition-colors focus-within:border-primary focus-within:bg-primary/10">
            <Input.TextArea
              v-model:value="feedUrlsText"
              :bordered="false"
              :rows="3"
              class="!bg-transparent"
              placeholder="https://openai.com/news/rss.xml&#10;https://example.com/feed"
            />
          </div>
        </FormItem>
      </div>
      <div class="mx-auto w-full max-w-[400px]">
        <FormItem label="归入分组（可选）">
          <Select
            v-model:value="groupId"
            allow-clear
            class="block w-full"
            placeholder="不归组"
            :options="localGroups.map((g) => ({ value: g.id, label: `${g.name}（${g.source_count}）` }))"
          >
            <template #dropdownRender="{ menuNode: menu }">
              <component :is="menu" />
              <div class="mt-1 border-t border-border p-1.5">
                <button
                  type="button"
                  class="flex w-full items-center gap-1.5 rounded-lg px-2.5 py-2 text-left text-xs font-medium text-primary transition-colors hover:bg-primary/10"
                  @mousedown.prevent
                  @click="openCreateGroup"
                >
                  <Plus class="size-3.5" />
                  新建分组
                </button>
              </div>
            </template>
          </Select>
        </FormItem>
      </div>
      <div class="mx-auto flex w-full max-w-[400px] justify-end gap-2">
        <button class="rounded-full border border-border px-4 py-1.5 text-xs" @click="open = false">取消</button>
        <button
          :disabled="saving"
          class="rounded-full bg-primary px-4 py-1.5 text-xs font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
          @click="submit"
        >
          导入
        </button>
      </div>
    </Form>

    <Modal v-model:open="createGroupOpen" title="新建分组" :footer="null" width="400px">
      <Form layout="vertical">
        <FormItem label="分组名称" required>
          <Input
            v-model:value="createGroupName"
            :maxlength="64"
            placeholder="如：AI 工具链"
            @keyup.enter="createGroup"
          />
        </FormItem>
        <div class="flex justify-end gap-2">
          <button
            type="button"
            class="rounded-full border border-border px-4 py-1.5 text-xs"
            @click="createGroupOpen = false"
          >
            取消
          </button>
          <button
            type="button"
            :disabled="createGroupSaving"
            class="rounded-full bg-primary px-4 py-1.5 text-xs font-semibold text-primary-foreground disabled:opacity-50"
            @click="createGroup"
          >
            {{ createGroupSaving ? '创建中…' : '创建并选中' }}
          </button>
        </div>
      </Form>
    </Modal>
  </Modal>
</template>
