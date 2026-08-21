import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    meta: {
      icon: 'lucide:flame',
      order: 1.7,
      title: '热点聚合',
    },
    name: 'Hotlist',
    path: '/hotlist',
    redirect: '/hotlist/board',
    children: [
      {
        name: 'HotlistBoard',
        path: 'board',
        component: () => import('#/views/hotlist/board/index.vue'),
        meta: { title: '榜单' },
      },
      {
        name: 'HotlistDigest',
        path: 'digest',
        component: () => import('#/views/hotlist/digest/index.vue'),
        meta: { title: '摘要' },
      },
      {
        name: 'HotlistSources',
        path: 'sources',
        component: () => import('#/views/hotlist/sources/index.vue'),
        meta: { title: '源管理' },
      },
      {
        name: 'HotlistTopics',
        path: 'topics',
        component: () => import('#/views/hotlist/topics/index.vue'),
        meta: { title: '主题订阅' },
      },
      {
        name: 'HotlistTopicReport',
        path: 'topics/:id/reports/:reportId',
        component: () => import('#/views/hotlist/topics/report.vue'),
        meta: { title: '报告', activePath: '/hotlist/topics' },
      },
    ],
  },
];

export default routes;
