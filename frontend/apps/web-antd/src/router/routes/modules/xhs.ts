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
        name: 'XhsComments',
        path: 'comments',
        component: () => import('#/views/xhs/comments/index.vue'),
        meta: { title: '评论管理' },
      },
      {
        name: 'XhsKeywordStats',
        path: 'keyword-stats',
        component: () => import('#/views/xhs/keyword-stats/index.vue'),
        meta: { title: '关键词统计' },
      },
      {
        name: 'XhsSentiment',
        path: 'sentiment',
        component: () => import('#/views/xhs/sentiment/index.vue'),
        meta: { title: '情绪分析' },
      },
      {
        name: 'XhsBrandRanking',
        path: 'brand-ranking',
        component: () => import('#/views/xhs/brand-ranking/index.vue'),
        meta: { title: '酒店/品牌提及排名' },
      },
      {
        name: 'XhsCollectTasks',
        path: 'collect-tasks',
        component: () => import('#/views/xhs/collect-tasks/index.vue'),
        meta: { title: '采集任务' },
      },
    ],
  },
];

export default routes;
