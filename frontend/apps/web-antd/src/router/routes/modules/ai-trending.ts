import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    meta: {
      icon: 'lucide:flame',
      order: 1.7,
      title: 'AI 开发热点',
    },
    name: 'AiTrending',
    path: '/ai-trending',
    component: () => import('#/views/ai-trending/index.vue'),
  },
];

export default routes;
