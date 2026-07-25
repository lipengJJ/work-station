<script lang="ts" setup>
import type { WorkbenchApi } from '#/api/core/workbench';

import { onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import { Card, Col, Row, Statistic, Table, Tag } from 'ant-design-vue';

import { getHomeApi } from '#/api/core/workbench';

const STATUS_COLOR: Record<string, string> = {
  pending: 'default',
  running: 'processing',
  success: 'success',
  failed: 'error',
};

const data = ref<WorkbenchApi.HomeResponse>();
const loading = ref(true);

onMounted(async () => {
  try {
    data.value = await getHomeApi();
  } finally {
    loading.value = false;
  }
});

const dataSourceColumns = [
  { title: '模块', dataIndex: 'module', key: 'module' },
  { title: '最近状态', dataIndex: 'last_status', key: 'last_status' },
  { title: '最近运行时间', dataIndex: 'last_run_at', key: 'last_run_at' },
  { title: '累计任务数', dataIndex: 'total_tasks', key: 'total_tasks' },
];

const recentTaskColumns = [
  { title: '模块', dataIndex: 'module', key: 'module' },
  { title: '类型', dataIndex: 'task_type', key: 'task_type' },
  { title: '状态', dataIndex: 'status', key: 'status' },
  { title: '创建时间', dataIndex: 'created_at', key: 'created_at' },
  { title: '结果摘要', dataIndex: 'result_summary', key: 'result_summary' },
];
</script>

<template>
  <Page :auto-content-height="false">
    <Row :gutter="16" style="margin-bottom: 16px">
      <Col :span="6">
        <Card :loading="loading">
          <Statistic title="任务总数" :value="data?.summary.total_tasks ?? 0" />
        </Card>
      </Col>
      <Col :span="6">
        <Card :loading="loading">
          <Statistic title="运行中" :value="data?.summary.running_count ?? 0" />
        </Card>
      </Col>
      <Col :span="6">
        <Card :loading="loading">
          <Statistic title="成功" :value="data?.summary.success_count ?? 0" />
        </Card>
      </Col>
      <Col :span="6">
        <Card :loading="loading">
          <Statistic title="失败" :value="data?.summary.failed_count ?? 0" />
        </Card>
      </Col>
    </Row>

    <Card title="数据源状态" :loading="loading" style="margin-bottom: 16px">
      <Table
        row-key="module"
        :data-source="data?.data_sources ?? []"
        :columns="dataSourceColumns"
        :pagination="false"
      >
        <template #bodyCell="{ column, text }">
          <template v-if="column.key === 'last_status'">
            <Tag v-if="text" :color="STATUS_COLOR[text as string]">{{ text }}</Tag>
            <span v-else>-</span>
          </template>
        </template>
      </Table>
    </Card>

    <Card title="最近任务" :loading="loading">
      <Table
        row-key="id"
        :data-source="data?.recent_tasks ?? []"
        :columns="recentTaskColumns"
        :pagination="false"
      >
        <template #bodyCell="{ column, text }">
          <template v-if="column.key === 'status'">
            <Tag :color="STATUS_COLOR[text as string]">{{ text }}</Tag>
          </template>
        </template>
      </Table>
    </Card>
  </Page>
</template>
