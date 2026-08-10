import { requestClient } from '#/api/request';

export namespace MarketOverviewApi {
  export interface IndexQuote {
    symbol: string;
    name: string;
    name_cn: string;
    price?: number;
    change?: number;
    change_percent?: number;
    day_high?: number;
    day_low?: number;
    year_high?: number;
    year_low?: number;
    available: boolean;
  }

  export interface IndicesResponse {
    indices: IndexQuote[];
  }

  export interface HistoryPoint {
    date: string;
    close: number;
  }

  export interface Mag7Company {
    symbol: string;
    name_cn: string;
    next_earnings_date: string | null;
    eps_estimate?: number | null;
    revenue_estimate?: number | null;
    available: boolean;
  }

  export interface Mag7EarningsResponse {
    companies: Mag7Company[];
  }

  export interface MarketEvent {
    type: 'cpi' | 'earnings' | 'fomc';
    date: string;
    date_range: string;
    title: string;
    detail: string;
    importance: 'high' | 'medium';
    source_url: string | null;
    confirmed: boolean;
    symbol?: string;
  }

  export interface EventsResponse {
    events: MarketEvent[];
    window_start: string;
    window_end: string;
    reference_note: string;
  }

  export type HistoryPeriod = '1M' | '1Y' | '3M' | '6M' | 'YTD';
}

export async function getMarketIndicesApi() {
  return requestClient.get<MarketOverviewApi.IndicesResponse>('/stock/market-overview/indices');
}

export async function getMarketIndexHistoryApi(
  symbol: string,
  period: MarketOverviewApi.HistoryPeriod = '6M',
) {
  return requestClient.get<MarketOverviewApi.HistoryPoint[]>(
    `/stock/market-overview/indices/${encodeURIComponent(symbol)}/history?period=${period}`,
  );
}

export async function getMag7EarningsApi() {
  return requestClient.get<MarketOverviewApi.Mag7EarningsResponse>(
    '/stock/market-overview/mag7-earnings',
  );
}

export async function getMarketEventsApi() {
  return requestClient.get<MarketOverviewApi.EventsResponse>('/stock/market-overview/events');
}
