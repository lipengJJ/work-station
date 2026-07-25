import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    meta: {
      icon: 'lucide:line-chart',
      order: 0,
      title: '股票分析',
    },
    name: 'Stock',
    path: '/stock',
    redirect: '/stock/watchlist',
    children: [
      {
        name: 'StockWatchlist',
        path: 'watchlist',
        component: () => import('#/views/stock/watchlist/index.vue'),
        meta: { title: '自选股' },
      },
      {
        name: 'StockQuotes',
        path: 'quotes',
        component: () => import('#/views/stock/quotes/index.vue'),
        meta: { title: '行情与K线' },
      },
      {
        name: 'StockFundamentals',
        path: 'fundamentals',
        component: () => import('#/views/stock/fundamentals/index.vue'),
        meta: { title: '基本面' },
      },
      {
        name: 'StockIndicators',
        path: 'indicators',
        component: () => import('#/views/stock/indicators/index.vue'),
        meta: { title: '技术指标' },
      },
      {
        name: 'StockOptions',
        path: 'options',
        component: () => import('#/views/stock/options/index.vue'),
        meta: { title: '期权分析' },
      },
      {
        name: 'StockAiReport',
        path: 'ai-report',
        component: () => import('#/views/stock/ai-report/index.vue'),
        meta: { title: 'AI研究报告' },
      },
    ],
  },
];

export default routes;
