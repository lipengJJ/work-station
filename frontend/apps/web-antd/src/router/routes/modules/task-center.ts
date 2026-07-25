import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    meta: {
      icon: 'lucide:clock',
      order: 3,
      title: '任务中心',
    },
    name: 'TaskCenter',
    path: '/task-center',
    component: () => import('#/views/task-center/index.vue'),
  },
];

export default routes;
