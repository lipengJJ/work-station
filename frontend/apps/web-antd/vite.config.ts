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
            // workbench-notify 分支后端使用独立端口 8012（可被 BACKEND_PROXY 环境变量覆盖）
            target: process.env.BACKEND_PROXY || 'http://localhost:8012',
            ws: true,
          },
        },
      },
    },
  };
});
