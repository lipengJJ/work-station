/**
 * @name umi 的路由配置
 * @doc https://umijs.org/docs/guides/routes
 *
 * 统一工作台侧边栏结构（Phase 2 骨架）：首页 / 股票分析 / 小红书分析 / 数据中心 / 任务中心 / 系统设置。
 * 首页、任务中心接了真实后端数据；其余子页面 Phase 3 逐个替换成真实实现。
 */
export default [
  {
    path: '/user',
    layout: false,
    routes: [
      {
        path: '/user/login',
        name: 'login',
        component: './user/login',
      },
      {
        name: '404',
        component: './exception/404',
        path: '/user/*',
      },
    ],
  },
  {
    path: '/home',
    name: '首页',
    icon: 'home',
    component: './Home',
  },
  {
    path: '/stock',
    name: '股票分析',
    icon: 'lineChart',
    routes: [
      { path: '/stock', redirect: '/stock/watchlist' },
      { path: '/stock/watchlist', name: '自选股', component: './Stock/Watchlist' },
      { path: '/stock/quotes', name: '行情与K线', component: './Stock/Quotes' },
      { path: '/stock/fundamentals', name: '基本面', component: './Stock/Fundamentals' },
      { path: '/stock/indicators', name: '技术指标', component: './Stock/Indicators' },
      { path: '/stock/options', name: '期权分析', component: './Stock/Options' },
      { path: '/stock/ai-report', name: 'AI研究报告', component: './Stock/AiReport' },
    ],
  },
  {
    path: '/xhs',
    name: '小红书分析',
    icon: 'tags',
    routes: [
      { path: '/xhs', redirect: '/xhs/notes' },
      { path: '/xhs/notes', name: '笔记管理', component: './Xhs/Notes' },
      { path: '/xhs/comments', name: '评论管理', component: './Xhs/Comments' },
      { path: '/xhs/keyword-stats', name: '关键词统计', component: './Xhs/KeywordStats' },
      { path: '/xhs/sentiment', name: '情绪分析', component: './Xhs/Sentiment' },
      { path: '/xhs/brand-ranking', name: '酒店/品牌提及排名', component: './Xhs/BrandRanking' },
      { path: '/xhs/collect-tasks', name: '采集任务', component: './Xhs/CollectTasks' },
    ],
  },
  {
    path: '/data-center',
    name: '数据中心',
    icon: 'database',
    routes: [
      { path: '/data-center', redirect: '/data-center/upload' },
      { path: '/data-center/upload', name: 'Excel/CSV上传', component: './DataCenter/Upload' },
      { path: '/data-center/sources', name: '数据源管理', component: './DataCenter/Sources' },
      { path: '/data-center/exports', name: '导出记录', component: './DataCenter/Exports' },
    ],
  },
  {
    path: '/task-center',
    name: '任务中心',
    icon: 'clockCircle',
    component: './TaskCenter',
  },
  {
    path: '/settings',
    name: '系统设置',
    icon: 'setting',
    routes: [
      { path: '/settings', redirect: '/settings/users' },
      { path: '/settings/users', name: '用户与权限', component: './Settings/Users' },
      { path: '/settings/api-config', name: 'API配置', component: './Settings/ApiConfig' },
      { path: '/settings/schedules', name: '定时任务', component: './Settings/Schedules' },
    ],
  },
  {
    path: '/',
    redirect: '/home',
  },
  {
    component: './exception/404',
    layout: false,
    path: '/*',
  },
];
