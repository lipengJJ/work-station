import type { CandlestickData, StockItem } from './types';

// 生成一段贴近真实走势的模拟 OHLCV K 线数据（含 MA/RSI/MACD/BOLL 指标）
function generateCandles(basePrice: number, count = 25, intervalDays = 1): CandlestickData[] {
  const candles: CandlestickData[] = [];
  let price = basePrice;
  const now = new Date();

  for (let i = count; i >= 0; i--) {
    const d = new Date(now.getTime() - i * intervalDays * 24 * 60 * 60 * 1000);
    const dateStr =
      intervalDays === 7
        ? `${d.getMonth() + 1}/${d.getDate()}周`
        : intervalDays === 30
          ? `${d.getFullYear()}/${d.getMonth() + 1}月`
          : `${d.getMonth() + 1}/${d.getDate()}`;
    const volatility = price * (intervalDays === 7 ? 0.045 : intervalDays === 30 ? 0.08 : 0.025);
    const change = (Math.random() - 0.47) * volatility;

    const open = Number(price.toFixed(2));
    const close = Number((price + change).toFixed(2));
    const high = Number((Math.max(open, close) + Math.random() * volatility * 0.7).toFixed(2));
    const low = Number((Math.min(open, close) - Math.random() * volatility * 0.7).toFixed(2));
    const volume = Math.floor(
      (1_000_000 + Math.random() * 5_000_000) * (intervalDays === 7 ? 4.5 : intervalDays === 30 ? 18 : 1),
    );

    price = close;
    candles.push({ time: dateStr, open, high, low, close, volume });
  }

  for (const [i, candle] of candles.entries()) {
    if (i >= 4) {
      const sum5 = candles.slice(i - 4, i + 1).reduce((acc, c) => acc + c.close, 0);
      candle.ma5 = Number((sum5 / 5).toFixed(2));
    }
    if (i >= 19) {
      const sum20 = candles.slice(i - 19, i + 1).reduce((acc, c) => acc + c.close, 0);
      candle.ma20 = Number((sum20 / 20).toFixed(2));
    }

    if (i >= 14) {
      let gains = 0;
      let losses = 0;
      for (let j = i - 13; j <= i; j++) {
        const diff = candles[j]!.close - candles[j - 1]!.close;
        if (diff >= 0) gains += diff;
        else losses -= diff;
      }
      const avgGain = gains / 14;
      const avgLoss = losses / 14;
      const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
      candle.rsi = Number((100 - 100 / (1 + rs)).toFixed(1));
    } else {
      candle.rsi = 55;
    }

    const dif = Number(((candle.ma5 || candle.close) - (candle.ma20 || candle.close)).toFixed(2));
    const dea = Number((dif * 0.8).toFixed(2));
    candle.macdDif = dif;
    candle.macdDea = dea;
    candle.macdHist = Number(((dif - dea) * 2).toFixed(2));

    const ma20 = candle.ma20 || candle.close;
    candle.bollMid = ma20;
    candle.bollUpper = Number((ma20 * 1.05).toFixed(2));
    candle.bollLower = Number((ma20 * 0.95).toFixed(2));
  }

  return candles;
}

export const INITIAL_STOCKS: StockItem[] = [
  {
    symbol: 'NVDA',
    name: '英伟达 (NVIDIA)',
    sector: '半导体/AI芯片',
    price: 138.25,
    change: 4.85,
    changePercent: 3.63,
    change1D: 3.63,
    change1W: 8.42,
    change1M: 18.75,
    high24h: 140.1,
    low24h: 133.5,
    volume: '48.2M',
    pe: 42.5,
    marketCap: '$3.38T',
    rsi: 68.4,
    macdSignal: 'Bullish Cross',
    isFavorite: true,
    tags: ['AI算力龙头', 'Blackwell放量', '机构重仓', '期权高IV'],
    kline1D: generateCandles(138.25, 25, 1),
    kline1W: generateCandles(138.25, 20, 7),
    kline1M: generateCandles(138.25, 15, 30),
    orderBookBids: [
      { price: 138.2, size: 1450, total: 1450 },
      { price: 138.15, size: 3200, total: 4650 },
      { price: 138.1, size: 5100, total: 9750 },
      { price: 138.05, size: 8900, total: 18_650 },
      { price: 138, size: 14_200, total: 32_850 },
    ],
    orderBookAsks: [
      { price: 138.3, size: 1820, total: 1820 },
      { price: 138.35, size: 2900, total: 4720 },
      { price: 138.4, size: 6400, total: 11_120 },
      { price: 138.45, size: 9100, total: 20_220 },
      { price: 138.5, size: 15_800, total: 36_020 },
    ],
    recentTrades: [
      { id: '1', time: '15:59:58', price: 138.25, size: 500, type: 'buy' },
      { id: '2', time: '15:59:55', price: 138.2, size: 200, type: 'sell' },
      { id: '3', time: '15:59:50', price: 138.25, size: 1200, type: 'buy' },
      { id: '4', time: '15:59:42', price: 138.25, size: 850, type: 'buy' },
      { id: '5', time: '15:59:38', price: 138.15, size: 300, type: 'sell' },
    ],
    optionsChain: [
      { strike: 130, callPrice: 10.4, callChange: 1.8, callIV: 44.2, callOI: 18_200, callVolume: 5400, callDelta: 0.82, callGamma: 0.02, putPrice: 1.85, putChange: -0.6, putIV: 45.1, putOI: 12_400, putVolume: 3200, putDelta: -0.18, putGamma: 0.02 },
      { strike: 135, callPrice: 6.8, callChange: 1.4, callIV: 42.8, callOI: 24_500, callVolume: 9800, callDelta: 0.65, callGamma: 0.03, putPrice: 3.1, putChange: -0.9, putIV: 43.5, putOI: 19_800, putVolume: 6100, putDelta: -0.35, putGamma: 0.03 },
      { strike: 140, callPrice: 4.1, callChange: 0.9, callIV: 41.5, callOI: 38_900, callVolume: 14_200, callDelta: 0.48, callGamma: 0.04, putPrice: 5.25, putChange: -1.2, putIV: 42.1, putOI: 22_100, putVolume: 8900, putDelta: -0.52, putGamma: 0.04 },
      { strike: 145, callPrice: 2.25, callChange: 0.5, callIV: 43.2, callOI: 31_200, callVolume: 11_500, callDelta: 0.31, callGamma: 0.03, putPrice: 8.4, putChange: -1.5, putIV: 43.8, putOI: 14_500, putVolume: 4300, putDelta: -0.69, putGamma: 0.03 },
      { strike: 150, callPrice: 1.15, callChange: 0.2, callIV: 46, callOI: 28_400, callVolume: 8200, callDelta: 0.18, callGamma: 0.02, putPrice: 12.1, putChange: -1.8, putIV: 46.5, putOI: 9100, putVolume: 2100, putDelta: -0.82, putGamma: 0.02 },
    ],
    financials: {
      revenue: [
        { quarter: 'Q3 24', revenue: 18.1, profit: 9.2 },
        { quarter: 'Q4 24', revenue: 22.1, profit: 12.3 },
        { quarter: 'Q1 25', revenue: 26, profit: 14.8 },
        { quarter: 'Q2 25', revenue: 30, profit: 16.6 },
      ],
      radar: [
        { category: '营收增长', value: 98 },
        { category: '盈利能力', value: 95 },
        { category: '现金流健康度', value: 90 },
        { category: '估值吸引力', value: 65 },
        { category: '动能趋势', value: 92 },
      ],
      metrics: [
        { name: '市盈率 (P/E TTM)', value: '42.5x', benchmark: '行业均值 28.4x', status: 'neutral' },
        { name: '毛利率 (Gross Margin)', value: '75.4%', benchmark: '行业均值 52.1%', status: 'good' },
        { name: 'ROE (净资产收益率)', value: '68.2%', benchmark: '行业均值 18.5%', status: 'good' },
        { name: '自由现金流 (FCF)', value: '$13.5B', benchmark: '季环比 +18%', status: 'good' },
      ],
    },
  },
  {
    symbol: 'TSLA',
    name: '特斯拉 (Tesla)',
    sector: '新能源车/智驾AI',
    price: 248.6,
    change: -5.4,
    changePercent: -2.13,
    change1D: -2.13,
    change1W: 3.15,
    change1M: -6.8,
    high24h: 256.8,
    low24h: 246.2,
    volume: '36.8M',
    pe: 61.2,
    marketCap: '$792B',
    rsi: 42.1,
    macdSignal: 'Neutral',
    isFavorite: true,
    tags: ['FSD 13落地', 'Optimus量产', '机构看好', '做空比率5.2%'],
    kline1D: generateCandles(248.6, 25, 1),
    kline1W: generateCandles(248.6, 20, 7),
    kline1M: generateCandles(248.6, 15, 30),
    orderBookBids: [
      { price: 248.5, size: 820, total: 820 },
      { price: 248.4, size: 1900, total: 2720 },
      { price: 248.3, size: 3400, total: 6120 },
      { price: 248.2, size: 5200, total: 11_320 },
      { price: 248.1, size: 8900, total: 20_220 },
    ],
    orderBookAsks: [
      { price: 248.7, size: 950, total: 950 },
      { price: 248.8, size: 2100, total: 3050 },
      { price: 248.9, size: 4100, total: 7150 },
      { price: 249, size: 7800, total: 14_950 },
      { price: 249.1, size: 11_200, total: 26_150 },
    ],
    recentTrades: [
      { id: '1', time: '15:59:59', price: 248.6, size: 300, type: 'sell' },
      { id: '2', time: '15:59:51', price: 248.65, size: 500, type: 'buy' },
    ],
    optionsChain: [
      { strike: 240, callPrice: 14.2, callChange: -2.1, callIV: 52.1, callOI: 14_200, callVolume: 4100, callDelta: 0.68, callGamma: 0.02, putPrice: 5.6, putChange: 1.8, putIV: 53, putOI: 18_900, putVolume: 7200, putDelta: -0.32, putGamma: 0.02 },
      { strike: 250, callPrice: 8.5, callChange: -1.8, callIV: 50.4, callOI: 28_900, callVolume: 12_400, callDelta: 0.5, callGamma: 0.03, putPrice: 9.8, putChange: 2.2, putIV: 51.2, putOI: 26_400, putVolume: 11_200, putDelta: -0.5, putGamma: 0.03 },
      { strike: 260, callPrice: 4.6, callChange: -1.2, callIV: 49.8, callOI: 31_200, callVolume: 9800, callDelta: 0.33, callGamma: 0.02, putPrice: 15.9, putChange: 2.9, putIV: 50.5, putOI: 15_200, putVolume: 4800, putDelta: -0.67, putGamma: 0.02 },
    ],
    financials: {
      revenue: [
        { quarter: 'Q3 24', revenue: 23.3, profit: 1.8 },
        { quarter: 'Q4 24', revenue: 25.1, profit: 2.1 },
        { quarter: 'Q1 25', revenue: 21.3, profit: 1.2 },
        { quarter: 'Q2 25', revenue: 25.5, profit: 1.5 },
      ],
      radar: [
        { category: '营收增长', value: 72 },
        { category: '盈利能力', value: 68 },
        { category: '现金流健康度', value: 85 },
        { category: '估值吸引力', value: 45 },
        { category: '动能趋势', value: 78 },
      ],
      metrics: [
        { name: '市盈率 (P/E TTM)', value: '61.2x', benchmark: '行业均值 18.2x', status: 'warn' },
        { name: '汽车毛利率', value: '18.2%', benchmark: '行业均值 14.5%', status: 'good' },
        { name: '自由现金流 (FCF)', value: '$1.3B', benchmark: '季环比 +12%', status: 'good' },
      ],
    },
  },
  {
    symbol: 'BABA',
    name: '阿里巴巴 (Alibaba)',
    sector: '中国互联网/云服务',
    price: 88.4,
    change: 2.15,
    changePercent: 2.49,
    change1D: 2.49,
    change1W: 6.2,
    change1M: 14.3,
    high24h: 89.2,
    low24h: 86.1,
    volume: '28.4M',
    pe: 14.8,
    marketCap: '$212B',
    rsi: 58.2,
    macdSignal: 'Bullish Cross',
    isFavorite: true,
    tags: ['阿里云重回增长', '高股息+回购', '电商业态升级', '北向资金增持'],
    kline1D: generateCandles(88.4, 25, 1),
    kline1W: generateCandles(88.4, 20, 7),
    kline1M: generateCandles(88.4, 15, 30),
    orderBookBids: [
      { price: 88.35, size: 2100, total: 2100 },
      { price: 88.3, size: 4500, total: 6600 },
    ],
    orderBookAsks: [
      { price: 88.45, size: 1800, total: 1800 },
      { price: 88.5, size: 5200, total: 7000 },
    ],
    recentTrades: [{ id: '1', time: '15:59:58', price: 88.4, size: 800, type: 'buy' }],
    optionsChain: [
      { strike: 85, callPrice: 5.2, callChange: 0.8, callIV: 36.2, callOI: 18_200, callVolume: 4200, callDelta: 0.62, callGamma: 0.03, putPrice: 1.8, putChange: -0.4, putIV: 37.1, putOI: 9800, putVolume: 2100, putDelta: -0.38, putGamma: 0.03 },
      { strike: 90, callPrice: 2.8, callChange: 0.5, callIV: 35, callOI: 28_400, callVolume: 8900, callDelta: 0.45, callGamma: 0.04, putPrice: 4.2, putChange: -0.7, putIV: 35.8, putOI: 14_200, putVolume: 3800, putDelta: -0.55, putGamma: 0.04 },
    ],
    financials: {
      revenue: [
        { quarter: 'Q3 24', revenue: 31.2, profit: 4.8 },
        { quarter: 'Q4 24', revenue: 36.5, profit: 5.4 },
      ],
      radar: [
        { category: '营收增长', value: 65 },
        { category: '盈利能力', value: 82 },
        { category: '现金流健康度', value: 92 },
        { category: '估值吸引力', value: 90 },
        { category: '动能趋势', value: 75 },
      ],
      metrics: [
        { name: '市盈率 (P/E TTM)', value: '14.8x', benchmark: '行业均值 22.1x', status: 'good' },
        { name: '股息收益率', value: '3.2%', benchmark: '行业均值 1.1%', status: 'good' },
      ],
    },
  },
  {
    symbol: 'AAPL',
    name: '苹果 (Apple Inc.)',
    sector: '消费电子/Apple Intelligence',
    price: 232.5,
    change: 1.2,
    changePercent: 0.52,
    change1D: 0.52,
    change1W: 1.8,
    change1M: 5.1,
    high24h: 234.1,
    low24h: 231,
    volume: '24.1M',
    pe: 33.4,
    marketCap: '$3.52T',
    rsi: 54.8,
    macdSignal: 'Neutral',
    isFavorite: true,
    tags: ['iPhone 16换机潮', 'Apple Intelligence', '巴菲特持仓', '稳定现金流'],
    kline1D: generateCandles(232.5, 25, 1),
    kline1W: generateCandles(232.5, 20, 7),
    kline1M: generateCandles(232.5, 15, 30),
    orderBookBids: [{ price: 232.4, size: 1100, total: 1100 }],
    orderBookAsks: [{ price: 232.6, size: 1400, total: 1400 }],
    recentTrades: [{ id: '1', time: '15:59:50', price: 232.5, size: 400, type: 'buy' }],
    optionsChain: [],
    financials: {
      revenue: [{ quarter: 'Q3 24', revenue: 85.8, profit: 21.4 }],
      radar: [{ category: '盈利能力', value: 96 }],
      metrics: [{ name: '毛利率', value: '46.2%', benchmark: '高标存量', status: 'good' }],
    },
  },
  {
    symbol: 'BILI',
    name: '哔哩哔哩 (Bilibili)',
    sector: '中国游戏/视频社区',
    price: 18.2,
    change: 0.95,
    changePercent: 5.51,
    change1D: 5.51,
    change1W: 12.4,
    change1M: 28.5,
    high24h: 18.6,
    low24h: 17.1,
    volume: '14.5M',
    pe: 28.1,
    marketCap: '$7.6B',
    rsi: 72.1,
    macdSignal: 'Bullish Cross',
    isFavorite: false,
    tags: ['《三国谋定天下》爆款', '经营现金流转正', '年轻化社区龙头', '做空平仓潮'],
    kline1D: generateCandles(18.2, 25, 1),
    kline1W: generateCandles(18.2, 20, 7),
    kline1M: generateCandles(18.2, 15, 30),
    orderBookBids: [{ price: 18.15, size: 3500, total: 3500 }],
    orderBookAsks: [{ price: 18.25, size: 4100, total: 4100 }],
    recentTrades: [{ id: '1', time: '15:59:45', price: 18.2, size: 1500, type: 'buy' }],
    optionsChain: [],
    financials: {
      revenue: [{ quarter: 'Q3 24', revenue: 7.2, profit: 0.4 }],
      radar: [{ category: '动能趋势', value: 95 }],
      metrics: [{ name: '广告收入增长', value: '+28%', benchmark: '行业顶尖', status: 'good' }],
    },
  },
  {
    symbol: 'TSM',
    name: '台积电 (TSMC)',
    sector: '晶圆代工/3nm龙头',
    price: 186.8,
    change: 3.4,
    changePercent: 1.85,
    change1D: 1.85,
    change1W: 4.2,
    change1M: 11.6,
    high24h: 188.2,
    low24h: 183.9,
    volume: '18.2M',
    pe: 26.5,
    marketCap: '$968B',
    rsi: 61.3,
    macdSignal: 'Bullish Cross',
    isFavorite: true,
    tags: ['CoWoS产能满载', '2nm制程推进', 'AI代工100%份额'],
    kline1D: generateCandles(186.8, 25, 1),
    kline1W: generateCandles(186.8, 20, 7),
    kline1M: generateCandles(186.8, 15, 30),
    orderBookBids: [],
    orderBookAsks: [],
    recentTrades: [],
    optionsChain: [],
    financials: { revenue: [], radar: [], metrics: [] },
  },
];
