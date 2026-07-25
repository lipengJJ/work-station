import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    meta: {
      icon: 'lucide:settings',
      order: 4,
      title: '系统设置',
    },
    name: 'Settings',
    path: '/settings',
    redirect: '/settings/users',
    children: [
      {
        name: 'SettingsUsers',
        path: 'users',
        component: () => import('#/views/settings/users/index.vue'),
        meta: { title: '用户与权限' },
      },
      {
        name: 'SettingsApiConfig',
        path: 'api-config',
        component: () => import('#/views/settings/api-config/index.vue'),
        meta: { title: 'API配置' },
      },
      {
        name: 'SettingsSchedules',
        path: 'schedules',
        component: () => import('#/views/settings/schedules/index.vue'),
        meta: { title: '定时任务' },
      },
    ],
  },
];

export default routes;
