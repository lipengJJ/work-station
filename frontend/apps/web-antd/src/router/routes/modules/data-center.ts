import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    meta: {
      icon: 'lucide:database',
      order: 2,
      title: '数据中心',
    },
    name: 'DataCenter',
    path: '/data-center',
    redirect: '/data-center/upload',
    children: [
      {
        name: 'DataCenterUpload',
        path: 'upload',
        component: () => import('#/views/data-center/upload/index.vue'),
        meta: { title: 'Excel/CSV上传' },
      },
      {
        name: 'DataCenterSources',
        path: 'sources',
        component: () => import('#/views/data-center/sources/index.vue'),
        meta: { title: '数据源管理' },
      },
      {
        name: 'DataCenterExports',
        path: 'exports',
        component: () => import('#/views/data-center/exports/index.vue'),
        meta: { title: '导出记录' },
      },
    ],
  },
];

export default routes;
