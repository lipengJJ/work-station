<script lang="ts" setup>
import type { WorkbenchApi } from '#/api/core/workbench';

import { computed, onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import { Button, Table, Tabs, Tag } from 'ant-design-vue';

import { getTasksCenterApi } from '#/api/core/workbench';

import NotifySenderModal from '#/components/notify-sender/index.vue';
import { useNotifySender } from '#/composables/use-notify-sender';

const { state: notifyState, openNotifySender } = useNotifySender();

const STATUS_COLOR: Record<string, string> = {
  pending: 'default',
  running: 'processing',
  success: 'success',
  failed: 'error',
};

// 任务类型中文名（xhs_tracking 由追踪任务每次扫描写入）
const TASK_TYPE_LABEL: Record<string, string> = {
  xhs_search: '笔记采集',
  xhs_tracking: '追踪扫描',
  analyze: '分析任务',
};

const data = ref<WorkbenchApi.TaskCenterResponse>();
const loading = ref(true);

onMounted(async () => {
  try {
    data.value = await getTasksCenterApi();
  } finally {
    loading.value = false;
  }
});

function orDash(value: null | string) {
  return value ?? '-';
}

const columns = [
  { title: '模块', dataIndex: 'module', key: 'module', width: 100 },
  { title: '类型', dataIndex: 'task_type', key: 'task_type', width: 140 },
  { title: '状态', dataIndex: 'status', key: 'status', width: 100 },
  { title: '创建时间', dataIndex: 'created_at', key: 'created_at' },
  {
    title: '开始时间',
    dataIndex: 'started_at',
    key: 'started_at',
    customRender: ({ text }: { text: null | string }) => orDash(text),
  },
  {
    title: '结束时间',
    dataIndex: 'finished_at',
    key: 'finished_at',
    customRender: ({ text }: { text: null | string }) => orDash(text),
  },
  {
    title: '结果摘要',
    dataIndex: 'result_summary',
    key: 'result_summary',
    customRender: ({ text }: { text: null | string }) => orDash(text),
  },
];

const tabs = computed(() => [
  { key: 'running', label: `运行中 (${data.value?.running.length ?? 0})`, rows: data.value?.running ?? [] },
  { key: 'completed', label: `已完成 (${data.value?.completed.length ?? 0})`, rows: data.value?.completed ?? [] },
  { key: 'failed', label: `失败日志 (${data.value?.failed.length ?? 0})`, rows: data.value?.failed ?? [] },
]);
</script>

<template>
  <Page :auto-content-height="false">
    <div class="mb-3 flex items-center justify-between">
      <div />
      <Button type="primary" size="small" @click="openNotifySender({ context: '任务中心' })">
        通知我
      </Button>
    </div>
    <Tabs default-active-key="running">
      <Tabs.TabPane v-for="tab in tabs" :key="tab.key" :tab="tab.label">
        <Table row-key="id" :loading="loading" :data-source="tab.rows" :columns="columns">
          <template #bodyCell="{ column, text }">
            <Tag v-if="column.key === 'status'" :color="STATUS_COLOR[text as string]">
              {{ text }}
            </Tag>
            <span v-else-if="column.key === 'task_type'" class="text-[hsl(var(--foreground))]">
              {{ TASK_TYPE_LABEL[text as string] ?? text }}
            </span>
          </template>
        </Table>
      </Tabs.TabPane>
    </Tabs>
    <NotifySenderModal v-model:open="notifyState.open" :context="notifyState.context" />
  </Page>
</template>
