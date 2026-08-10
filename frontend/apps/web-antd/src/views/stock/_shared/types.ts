export type ColorMode = 'cn' | 'us'; // 'cn' = 红涨绿跌, 'us' = 绿涨红跌

export interface CandlestickData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  ma5?: number;
  ma20?: number;
  ma60?: number;
  macdDif?: number;
  macdDea?: number;
  macdHist?: number;
  rsi?: number;
  bollUpper?: number;
  bollMid?: number;
  bollLower?: number;
}

export interface OrderBookEntry {
  price: number;
  size: number;
  total: number;
}

export interface TradeTapeEntry {
  id: string;
  time: string;
  price: number;
  size: number;
  type: 'buy' | 'sell';
}

export interface OptionStrike {
  strike: number;
  callPrice: number;
  callChange: number;
  callIV: number;
  callOI: number;
  callVolume: number;
  callDelta: number;
  callGamma: number;
  putPrice: number;
  putChange: number;
  putIV: number;
  putOI: number;
  putVolume: number;
  putDelta: number;
  putGamma: number;
}

export interface StockItem {
  symbol: string;
  // yfinance 真实数据额外带的字段，方便前端在需要"完整代码"的地方使用（比如以后接真实K线）
  code?: string;
  name: string;
  sector: string;
  price: number;
  change: number;
  changePercent: number;
  change1D: number; // 最近一天涨幅 %
  // 自选股列表接口只有当日快照，不提供这两个字段（需要额外算历史涨幅，这次没做），
  // 真实数据下是 null，前端要显示成 "--" 而不是当成 0
  change1W: null | number; // 最近一周涨幅 %
  change1M: null | number; // 最近一个月涨幅 %
  high24h: number;
  low24h: number;
  volume: string;
  pe: null | number;
  marketCap: string;
  // 同上，自选股列表这一级没有算 RSI/MACD 信号（K线里的 CandlestickData.rsi 是另一回事），真实数据下是 null
  rsi: null | number;
  macdSignal: 'Bearish Cross' | 'Bullish Cross' | 'Neutral' | null;
  isFavorite?: boolean;
  tags: string[];
  kline1D: CandlestickData[];
  kline1W?: CandlestickData[];
  kline1M?: CandlestickData[];
  orderBookBids: OrderBookEntry[];
  orderBookAsks: OrderBookEntry[];
  recentTrades: TradeTapeEntry[];
  optionsChain: OptionStrike[];
  financials: {
    metrics: Array<{
      benchmark: string;
      name: string;
      status: 'good' | 'neutral' | 'warn';
      value: string;
    }>;
    radar: Array<{ category: string; value: number }>;
    revenue: Array<{ profit: number; quarter: string; revenue: number; }>;
  };
}

export interface AiResearchReport {
  symbol: string;
  name: string;
  rating: 'BUY' | 'HOLD' | 'SELL' | 'STRONG_BUY' | 'UNDERPERFORM';
  targetPrice: number;
  currentPrice: number;
  upside: string;
  investmentThesis: string;
  keyCatalysts: string[];
  keyRisks: string[];
  financialHighlights: {
    freeCashFlow: string;
    grossMargin: string;
    pegRatio: string;
    peRatio: string;
    revenueGrowthYoY: string;
  };
  institutionalSentiment: string;
  timestamp?: string;
  mode?: string;
}
