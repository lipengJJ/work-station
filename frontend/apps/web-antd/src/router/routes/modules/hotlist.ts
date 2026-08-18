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
        name: 'HotlistRules',
        path: 'rules',
        component: () => import('#/views/hotlist/rules/index.vue'),
        meta: { title: '规则' },
      },
      {
        name: 'HotlistSources',
        path: 'sources',
        component: () => import('#/views/hotlist/sources/index.vue'),
        meta: { title: '源管理' },
      },
    ],
  },
];

export default routes;
