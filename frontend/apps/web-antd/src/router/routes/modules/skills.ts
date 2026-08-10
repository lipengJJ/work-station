import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    meta: {
      icon: 'lucide:puzzle',
      order: 1.5,
      title: 'Skill 管理',
    },
    name: 'Skills',
    path: '/skills',
    redirect: '/skills/list',
    children: [
      {
        name: 'SkillsList',
        path: 'list',
        component: () => import('#/views/skills/index.vue'),
        meta: { title: 'Skill 列表' },
      },
    ],
  },
];

export default routes;
