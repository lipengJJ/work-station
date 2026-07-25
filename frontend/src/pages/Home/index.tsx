import { PageContainer, ProCard, StatisticCard } from '@ant-design/pro-components';
import { Table, Tag } from 'antd';
import React, { useEffect, useState } from 'react';
import { getHome } from '@/services/workbench/api';

const STATUS_COLOR: Record<string, string> = {
  pending: 'default',
  running: 'processing',
  success: 'success',
  failed: 'error',
};

const Home: React.FC = () => {
  const [data, setData] = useState<WB.HomeResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getHome()
      .then(setData)
      .finally(() => setLoading(false));
  }, []);

  return (
    <PageContainer title={false}>
      <ProCard gutter={16} ghost style={{ marginBottom: 16 }}>
        <StatisticCard
          statistic={{ title: '任务总数', value: data?.summary.total_tasks ?? 0 }}
          loading={loading}
        />
        <StatisticCard
          statistic={{ title: '运行中', value: data?.summary.running_count ?? 0 }}
          loading={loading}
        />
        <StatisticCard
          statistic={{ title: '成功', value: data?.summary.success_count ?? 0 }}
          loading={loading}
        />
        <StatisticCard
          statistic={{ title: '失败', value: data?.summary.failed_count ?? 0 }}
          loading={loading}
        />
      </ProCard>

      <ProCard title="数据源状态" style={{ marginBottom: 16 }} loading={loading}>
        <Table
          rowKey="module"
          dataSource={data?.data_sources ?? []}
          pagination={false}
          columns={[
            { title: '模块', dataIndex: 'module' },
            {
              title: '最近状态',
              dataIndex: 'last_status',
              render: (status: string | null) =>
                status ? <Tag color={STATUS_COLOR[status]}>{status}</Tag> : '-',
            },
            { title: '最近运行时间', dataIndex: 'last_run_at', render: (v) => v ?? '-' },
            { title: '累计任务数', dataIndex: 'total_tasks' },
          ]}
        />
      </ProCard>

      <ProCard title="最近任务" loading={loading}>
        <Table
          rowKey="id"
          dataSource={data?.recent_tasks ?? []}
          pagination={false}
          columns={[
            { title: '模块', dataIndex: 'module' },
            { title: '类型', dataIndex: 'task_type' },
            {
              title: '状态',
              dataIndex: 'status',
              render: (status: string) => <Tag color={STATUS_COLOR[status]}>{status}</Tag>,
            },
            { title: '创建时间', dataIndex: 'created_at' },
            { title: '结果摘要', dataIndex: 'result_summary', render: (v) => v ?? '-' },
          ]}
        />
      </ProCard>
    </PageContainer>
  );
};

export default Home;
