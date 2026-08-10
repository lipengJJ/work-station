import type { StockItem } from './types';

import { ref } from 'vue';

import { INITIAL_STOCKS } from './mock-stocks';

/**
 * 参考的原型项目里这几个页面是同一个 App.vue 内用 v-if 切换的"视图"，靠 props/emit 共享
 * stocks 列表和当前选中的股票。workbench 里这几个页面是真正的路由，各自独立加载，用一个
 * 模块级单例状态替代那套 props/emit——纯前端 mock 数据，没有持久化诉求，不需要上 Pinia。
 */
export const stocks = ref<StockItem[]>(INITIAL_STOCKS);
export const selectedStock = ref<StockItem>(INITIAL_STOCKS[0]!);

export function selectStock(stock: StockItem) {
  selectedStock.value = stock;
}

export function toggleFavorite(stock: StockItem) {
  stock.isFavorite = !stock.isFavorite;
}
