import { defineConfig } from '@vben/vite-config';

export default defineConfig(async () => {
  return {
    application: {},
    vite: {
      server: {
        proxy: {
          // 代理到 workbench 自己的 FastAPI 后端（backend/README 或根目录 README），
          // 后端路由本身就带 /api 前缀，这里不做 rewrite
          '/api': {
            changeOrigin: true,
            target: 'http://localhost:8010',
            ws: true,
          },
        },
      },
    },
  };
});
