import { PageContainer } from '@ant-design/pro-components';
import { Empty } from 'antd';
import React from 'react';

/**
 * Phase 2 骨架阶段的占位页面：能导航到、能看到"开发中"提示，不报错白屏。
 * Phase 3 接入 stock-report/collector 与 Spider_XHS/webapp 的真实业务逻辑时，
 * 逐个替换成真实页面。
 */
const ComingSoon: React.FC<{ title: string }> = ({ title }) => (
  <PageContainer title={title}>
    <Empty description={`${title} · 开发中`} style={{ padding: '80px 0' }} />
  </PageContainer>
);

export default ComingSoon;
