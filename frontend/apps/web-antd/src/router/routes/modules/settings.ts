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
    redirect: '/settings/api-config',
    children: [
      {
        name: 'SettingsApiConfig',
        path: 'api-config',
        component: () => import('#/views/settings/api-config/index.vue'),
        meta: { title: 'API配置' },
      },
      {
        name: 'SettingsTaskCenter',
        path: 'task-center',
        component: () => import('#/views/task-center/index.vue'),
        meta: { title: '任务中心' },
      },
      {
        name: 'SettingsLogs',
        path: 'logs',
        component: () => import('#/views/settings/logs/index.vue'),
        meta: { title: '系统日志' },
      },
    ],
  },
];

export default routes;
