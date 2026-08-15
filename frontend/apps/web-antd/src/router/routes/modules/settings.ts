import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    meta: {
      icon: 'lucide:settings',
      order: 4,
      title: '系统设置',
    },
    name: 'Settings',
    path: '/system',
    redirect: '/system/settings',
    children: [
      {
        name: 'SettingsSystem',
        path: 'settings',
        component: () => import('#/views/settings/system/index.vue'),
        meta: { title: '系统设置' },
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
