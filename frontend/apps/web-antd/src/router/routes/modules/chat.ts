import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    meta: {
      icon: 'lucide:bot',
      order: -2,
      title: 'AI 助手',
    },
    name: 'Chat',
    path: '/chat',
    component: () => import('#/views/chat/index.vue'),
  },
];

export default routes;
