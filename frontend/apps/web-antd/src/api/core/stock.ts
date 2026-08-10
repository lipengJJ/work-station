import type { CandlestickData, StockItem } from '#/views/stock/_shared/types';

import { requestClient } from '#/api/request';

export async function getStockWatchlistApi() {
  return requestClient.get<StockItem[]>('/stock/watchlist');
}

export async function getStockKlineApi(symbol: string, interval: '1d' | '1mo' | '1wk' = '1d') {
  return requestClient.get<CandlestickData[]>(`/stock/kline/${encodeURIComponent(symbol)}?interval=${interval}`);
}

export async function addStockToWatchlistApi(symbol: string) {
  return requestClient.post<StockItem[]>('/stock/watchlist', { symbol });
}

export async function removeStockFromWatchlistApi(symbol: string) {
  return requestClient.delete<StockItem[]>(`/stock/watchlist/${encodeURIComponent(symbol)}`);
}
