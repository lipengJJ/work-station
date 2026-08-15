<script lang="ts" setup>
import type { ResourceApi } from '#/api/core/resource';

import { onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import { Button, message, Pagination, Popconfirm, Table, Tag } from 'ant-design-vue';
import { RefreshCw, Trash2 } from 'lucide-vue-next';

import {
  deleteSaveTaskApi,
  listSaveTasksApi,
} from '#/api/core/resource';

const STATUS_LABEL: Record<string, string> = {
  pending: '处理中',
  success: '转存成功',
  failed: '失败',
};
const STATUS_COLOR: Record<string, string> = {
  pending: 'processing',
  success: 'success',
  failed: 'error',
};

function formatDateTime(iso: string) {
  if (!iso) return '';
  return iso.slice(0, 16).replace('T', ' ');
}

const items = ref<ResourceApi.SaveTask[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = 20;
const loading = ref(false);

async function fetchTasks() {
  loading.value = true;
  try {
    const data = await listSaveTasksApi({ page: page.value, page_size: pageSize });
    items.value = data.items;
    total.value = data.total;
  } catch (e: any) {
    message.error(`加载失败：${e.message}`);
  } finally {
    loading.value = false;
  }
}

async function onDelete(task: ResourceApi.SaveTask) {
  try {
    await deleteSaveTaskApi(task.id);
    message.success('已删除记录');
    fetchTasks();
  } catch (e: any) {
    message.error(`删除失败：${e.message}`);
  }
}

onMounted(fetchTasks);

const columns = [
  { title: '资源', dataIndex: 'resource_title', key: 'resource_title', ellipsis: true },
  { title: '状态', dataIndex: 'status', key: 'status', width: 110 },
  { title: '转存到', dataIndex: 'target_dir', key: 'target_dir', width: 160 },
  { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 160 },
  { title: '操作', key: 'action', width: 80 },
];
</script>

<template>
  <Page>
    <div class="flex w-full flex-col gap-4">
      <div class="flex items-center justify-between">
        <div class="text-base font-semibold text-[hsl(var(--foreground))]">转存记录</div>
        <Button @click="fetchTasks">
          <RefreshCw class="mr-1 size-4" />
          刷新
        </Button>
      </div>

      <Table
        :columns="columns"
        :data-source="items"
        :loading="loading"
        :pagination="false"
        row-key="id"
        class="rounded-xl border border-slate-700/50 bg-slate-900/60"
        :locale="{ emptyText: '暂无转存记录，去「资源搜索」页试试吧' }"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'resource_title'">
            <div class="flex flex-col gap-0.5">
              <span class="truncate text-[hsl(var(--foreground))]">{{ record.resource_title }}</span>
              <span class="truncate font-mono text-xs text-[hsl(var(--muted-foreground))]">{{ record.share_url }}</span>
              <span v-if="record.message" class="truncate text-xs text-[hsl(var(--muted-foreground))]">
                {{ record.message }}
              </span>
            </div>
          </template>
          <template v-else-if="column.key === 'status'">
            <Tag :color="STATUS_COLOR[record.status]">
              {{ STATUS_LABEL[record.status] || record.status }}
            </Tag>
          </template>
          <template v-else-if="column.key === 'target_dir'">
            <span class="text-[hsl(var(--muted-foreground))]">{{ record.target_dir || '根目录' }}</span>
          </template>
          <template v-else-if="column.key === 'created_at'">
            <span class="text-[hsl(var(--muted-foreground))]">{{ formatDateTime(record.created_at) }}</span>
          </template>
          <template v-else-if="column.key === 'action'">
            <Popconfirm
              title="确定删除这条转存记录吗？"
              ok-text="删除"
              cancel-text="取消"
              @confirm="onDelete(record as ResourceApi.SaveTask)"
            >
              <Button type="text" danger size="small">
                <Trash2 class="size-4" />
              </Button>
            </Popconfirm>
          </template>
        </template>
      </Table>

      <div v-if="total > pageSize" class="flex justify-center">
        <Pagination
          :current="page"
          :page-size="pageSize"
          :total="total"
          :show-size-changer="false"
          @change="(next: number) => { page = next; fetchTasks(); }"
        />
      </div>
    </div>
  </Page>
</template>
