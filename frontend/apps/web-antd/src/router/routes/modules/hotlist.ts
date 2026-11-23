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
        name: 'HotlistDigestLegacyRedirect',
        path: 'digest',
        redirect: '/hotlist/board',
        meta: { hideInMenu: true, title: '摘要' },
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
        meta: { title: '报告', activePath: '/hotlist/topics', hideInMenu: true },
      },
      {
        name: 'HotlistDaily',
        path: 'daily/:reportId?',
        component: () => import('#/views/hotlist/daily/index.vue'),
        meta: { title: '日报' },
      },
      {
        name: 'HotlistRsshub',
        path: 'rsshub',
        component: () => import('#/views/hotlist/rsshub/index.vue'),
        meta: { title: 'RSSHub 路由' },
      },
      {
        name: 'HotlistItemDetail',
        path: 'items/:id',
        component: () => import('#/views/hotlist/items/detail.vue'),
        meta: { title: '文章详情', activePath: '/hotlist/board', hideInMenu: true },
      },
    ],
  },
];

export default routes;
