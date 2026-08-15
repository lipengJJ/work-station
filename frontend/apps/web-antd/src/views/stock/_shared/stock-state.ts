import type { StockItem } from './types';

import { ref } from 'vue';

/**
 * 股票模块跨页面共享的当前状态（模块级单例，不依赖 Pinia——只有"当前选中股票"这一个
 * 需要跨页共享的轻量状态，没有持久化诉求）。
 *
 * 真实数据流：自选股页从 /api/stock/watchlist 加载真实列表写入 stocks；用户在自选股
 * 列表点击某只股票 → selectStock() 写入 selectedStock → 跳转 K线/指标等页面读取。
 * 不再有任何 mock 数据源：没有选中股票时 selectedStock 为 null，页面各自显示空态。
 */
export const stocks = ref<StockItem[]>([]);
export const selectedStock = ref<StockItem | null>(null);

export function selectStock(stock: StockItem) {
  selectedStock.value = stock;
}
