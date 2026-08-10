import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    meta: {
      icon: 'lucide:tags',
      order: 1,
      title: '小红书分析',
    },
    name: 'Xhs',
    path: '/xhs',
    redirect: '/xhs/notes',
    children: [
      {
        name: 'XhsNotes',
        path: 'notes',
        component: () => import('#/views/xhs/notes/index.vue'),
        meta: { title: '笔记管理' },
      },
      {
        name: 'XhsAiAnalysis',
        path: 'ai-analysis',
        component: () => import('#/views/xhs/ai-analysis/index.vue'),
        meta: { title: 'AI 分析' },
      },
      {
        name: 'XhsAnalysisReports',
        path: 'analysis-reports',
        component: () => import('#/views/xhs/analysis-reports/index.vue'),
        meta: { title: '分析报告' },
      },
      {
        name: 'XhsAnalysisReportDetail',
        path: 'analysis-reports/:id',
        component: () => import('#/views/xhs/analysis-reports/detail.vue'),
        meta: { title: '报告详情', hideInMenu: true },
      },
      {
        name: 'XhsTracking',
        path: 'tracking',
        component: () => import('#/views/xhs/tracking/index.vue'),
        meta: { title: '追踪任务' },
      },
    ],
  },
];

export default routes;
