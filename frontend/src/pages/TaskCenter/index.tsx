import { PageContainer } from '@ant-design/pro-components';
import { Table, Tabs, Tag } from 'antd';
import React, { useEffect, useState } from 'react';
import { getTasksCenter } from '@/services/workbench/api';

const STATUS_COLOR: Record<string, string> = {
  pending: 'default',
  running: 'processing',
  success: 'success',
  failed: 'error',
};

const columns = [
  { title: '模块', dataIndex: 'module', width: 100 },
  { title: '类型', dataIndex: 'task_type', width: 140 },
  {
    title: '状态',
    dataIndex: 'status',
    width: 100,
    render: (status: string) => <Tag color={STATUS_COLOR[status]}>{status}</Tag>,
  },
  { title: '创建时间', dataIndex: 'created_at' },
  { title: '开始时间', dataIndex: 'started_at', render: (v: string | null) => v ?? '-' },
  { title: '结束时间', dataIndex: 'finished_at', render: (v: string | null) => v ?? '-' },
  { title: '结果摘要', dataIndex: 'result_summary', render: (v: string | null) => v ?? '-' },
];

const TaskCenter: React.FC = () => {
  const [data, setData] = useState<WB.TaskCenterResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getTasksCenter()
      .then(setData)
      .finally(() => setLoading(false));
  }, []);

  return (
    <PageContainer title={false}>
      <Tabs
        defaultActiveKey="running"
        items={[
          {
            key: 'running',
            label: `运行中 (${data?.running.length ?? 0})`,
            children: (
              <Table rowKey="id" loading={loading} dataSource={data?.running ?? []} columns={columns} />
            ),
          },
          {
            key: 'completed',
            label: `已完成 (${data?.completed.length ?? 0})`,
            children: (
              <Table rowKey="id" loading={loading} dataSource={data?.completed ?? []} columns={columns} />
            ),
          },
          {
            key: 'failed',
            label: `失败日志 (${data?.failed.length ?? 0})`,
            children: (
              <Table rowKey="id" loading={loading} dataSource={data?.failed ?? []} columns={columns} />
            ),
          },
        ]}
      />
    </PageContainer>
  );
};

export default TaskCenter;
