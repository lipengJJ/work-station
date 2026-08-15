"""
历史K线（日/周/月）：Finnhub 免费版的 /stock/candle 已经不对普通股票开放（真实测过，返回
no_data/403），换用 yfinance 拉 Yahoo Finance 的历史行情，不需要 API Key。

日K/周K/月K是 yfinance 同一个 history() 接口、只是 interval 参数不同（"1d"/"1wk"/"1mo"），
Yahoo 自己按对应周期聚合好 OHLCV，不需要自己在日线基础上重采样。均线/MACD/RSI 是标准公式，
在拿到的 K 线序列上现算——用的都是"N 根"而不是"N 天"，所以周K的 MA20 就是 20 周均线、
月K的 MA20 就是 20 月均线，这也是各类专业看盘软件的通行做法。

字段形状和 app/views/stock/_shared/types.ts 的 CandlestickData 对齐，前端图表不用改。

结果按 (symbol, "kline_{interval}") 缓存进 cache_service 的通用表。已收盘的历史K线不会
再变，只有当前这根还在走的K线会变——所以不是整份过期整份重拉，而是用 cache_service.
get_or_refresh_time_series 做增量刷新：冷启动整段拉一次，之后每次只拉最近一小段去补上
新收盘的K线 + 刷新当前这根，跟历史部分合并，不用每次都把整个 6mo/2y/5y 的窗口重新请求
一遍（之前的实现就是这么做的，等于每次都把早就确定不变的大部分历史也白白重新拉一遍）。
"""
from __future__ import annotations

import pandas as pd
import yfinance as yf
from loguru import logger
from sqlalchemy.orm import Session

from app.stock.services import cache_service

# 冷启动（缓存里完全没有这支股票这个周期的数据）时用，一次性拉够前端展示窗口
# （quotes/index.vue 的 MAX_VISIBLE_CANDLES=60）之外还留出计算 MA60 需要的历史余量。
# 日K拉 1 年：前端提供"近半年 / 近一年"快捷视窗 + 底部滑块拖动看更早历史，
# 之前只拉 6mo，用户拖两下就到头了。注意：已有 kline_1d 缓存不会自动扩展窗口，
# 改这里后需要清一次缓存（冷启动才会重新拉 full）。
_FULL_PERIOD_BY_INTERVAL = {
    "1d": "1y",
    "1wk": "2y",
    "1mo": "5y",
}

# 已有缓存时，增量刷新只拉这么一小段——留了几倍余量，保证哪怕隔了几天/连续假期没访问，
# 这一小段也能和上次缓存的历史衔接上，不会中间空出一截没有数据
_REFRESH_PERIOD_BY_INTERVAL = {
    "1d": "10d",
    "1wk": "3mo",
    "1mo": "6mo",
}

# 距上次增量刷新多久之内，连这一小段也不用再拉，直接用缓存——日K盘中价格分钟级在变，
# 给短一点；周K/月K基本不怎么变，给长一点
_REFRESH_TTL_SECONDS = {
    "1d": 30 * 60,
    "1wk": 3 * 3600,
    "1mo": 6 * 3600,
}


class KlineError(Exception):
    pass


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def get_kline(db: Session, symbol: str, interval: str = "1d") -> list[dict]:
    if interval not in _FULL_PERIOD_BY_INTERVAL:
        raise KlineError(f"不支持的K线周期: {interval}")

    return cache_service.get_or_refresh_time_series(
        db, symbol, f"kline_{interval}",
        time_key="time",
        refresh_ttl_seconds=_REFRESH_TTL_SECONDS[interval],
        fetch_full=lambda: _fetch_raw_ohlcv(symbol, interval, _FULL_PERIOD_BY_INTERVAL[interval]),
        fetch_recent=lambda: _fetch_raw_ohlcv(symbol, interval, _REFRESH_PERIOD_BY_INTERVAL[interval]),
        postprocess=_compute_indicators,
    )


def _round(v) -> float | None:
    return None if pd.isna(v) else round(float(v), 2)


def _fetch_raw_ohlcv(symbol: str, interval: str, period: str) -> list[dict]:
    """只拉原始 OHLCV，不算均线/MACD/RSI 这些衍生指标——这些指标必须在合并后的完整
    序列上统一算（见 _compute_indicators），单独对增量拉回来的这一小段自己算，会因为
    历史长度不够导致 rolling/ewm 算出来是 NaN 或者不准。"""
    try:
        hist = yf.Ticker(symbol).history(period=period, interval=interval)
    except Exception as e:  # yfinance 底层抛的异常类型不固定，统一收窄成 KlineError
        raise KlineError(f"请求 Yahoo Finance 接口失败: {e}") from e

    if hist.empty:
        raise KlineError(f"Yahoo Finance 查不到 {symbol} 的历史K线，请确认代码是否正确")

    date_format = "%Y-%m-%d" if interval != "1mo" else "%Y-%m"
    candles = [
        {
            "time": date.strftime(date_format),
            "open": _round(row["Open"]),
            "high": _round(row["High"]),
            "low": _round(row["Low"]),
            "close": _round(row["Close"]),
            "volume": int(row["Volume"]) if pd.notna(row["Volume"]) else 0,
        }
        for date, row in hist.iterrows()
    ]
    logger.info(f"拉到 {symbol} {interval} K线原始数据 {len(candles)} 根")
    return candles


def _compute_indicators(candles: list[dict]) -> list[dict]:
    """在完整的（历史 + 增量合并后）K线序列上统一算均线/MACD/RSI。用的都是"N 根"而不是
    "N 天"，所以周K的 MA20 就是 20 周均线、月K的 MA20 就是 20 月均线，这也是各类专业看盘
    软件的通行做法。"""
    if not candles:
        return []

    df = pd.DataFrame(candles).sort_values("time").reset_index(drop=True)
    close = df["close"]

    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_dif = ema12 - ema26
    macd_dea = macd_dif.ewm(span=9, adjust=False).mean()
    macd_hist = (macd_dif - macd_dea) * 2

    rsi = _rsi(close)

    df["ma5"] = ma5
    df["ma20"] = ma20
    df["ma60"] = ma60
    df["macdDif"] = macd_dif
    df["macdDea"] = macd_dea
    df["macdHist"] = macd_hist
    df["rsi"] = rsi

    records = df.to_dict(orient="records")
    for r in records:
        r["volume"] = int(r["volume"])
        for key in ("open", "high", "low", "close", "ma5", "ma20", "ma60", "macdDif", "macdDea", "macdHist", "rsi"):
            r[key] = _round(r[key])
    logger.info(f"重新计算K线指标 {len(records)} 根")
    return records
