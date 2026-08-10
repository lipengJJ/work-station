import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    meta: {
      icon: 'lucide:folder-search',
      order: 1.6,
      title: '资源搜索',
    },
    name: 'Resource',
    path: '/resource',
    redirect: '/resource/search',
    children: [
      {
        name: 'ResourceSearch',
        path: 'search',
        component: () => import('#/views/resource/search/index.vue'),
        meta: { title: '资源搜索' },
      },
      {
        name: 'ResourceTransfer',
        path: 'transfer',
        component: () => import('#/views/resource/transfer/index.vue'),
        meta: { title: '转存记录' },
      },
      {
        name: 'ResourceSettings',
        path: 'settings',
        component: () => import('#/views/resource/settings/index.vue'),
        meta: { title: '网盘设置' },
      },
    ],
  },
];

export default routes;
