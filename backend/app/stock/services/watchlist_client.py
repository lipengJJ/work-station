"""
自选股行情：用 yfinance（Yahoo Finance），不需要任何 API Key。

之前用 Finnhub 免费版，一支股票要 quote + profile2 + metric 三次请求，watchlist 稍微
多几支就顶到免费版每分钟请求上限，后面的股票请求被 429 拒绝后又被 list_watchlist_stocks
静默跳过——表现出来就是"过一会列表只剩一支股票"，具体见这次改动前的 finnhub_client.py。

行情数据缓存进 WatchlistStock 表（见 app/stock/models/watchlist_stock.py），不是每次打开自选股
页面都重新拉一遍 Yahoo Finance：只有缓存过期（超过 _QUOTE_TTL_SECONDS）才真的发请求刷新，
没过期直接用数据库里存的值拼返回。刷新失败时（网络抖动、Yahoo 临时限流）优先保留上一次
缓存的数据而不是把这支股票从列表里删掉，比"直接拿不到就跳过"更稳。

多支过期的股票并发刷新（线程池），单支请求包含 fast_info（实时价格/成交量/市值）+
Ticker.info（公司名称/行业/PE）+ 近 3 个月日线收盘（算 1W/1M 涨幅）。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Optional

import yfinance as yf
from loguru import logger
from sqlalchemy.orm import Session

from app.stock.models import WatchlistStock

_MAX_WORKERS = 8
_QUOTE_TTL_SECONDS = 5 * 60


class WatchlistError(Exception):
    pass


# -------------------------------------------------------------- 自选股代码列表 ----

def list_watchlist_symbols(db: Session) -> list[str]:
    rows = db.query(WatchlistStock).order_by(WatchlistStock.id).all()
    return [r.symbol for r in rows]


def add_watchlist_symbol(db: Session, symbol: str) -> None:
    symbol = symbol.strip().upper()
    if not symbol:
        raise WatchlistError("股票代码不能为空")
    if db.query(WatchlistStock).filter(WatchlistStock.symbol == symbol).first():
        return

    live = _fetch_live(symbol)
    if not live:
        raise WatchlistError(f"Yahoo Finance 查不到 {symbol} 的行情，请确认代码是否正确")

    row = WatchlistStock(symbol=symbol)
    _apply_live(row, live)
    db.add(row)


def remove_watchlist_symbol(db: Session, symbol: str) -> None:
    db.query(WatchlistStock).filter(WatchlistStock.symbol == symbol.strip().upper()).delete()


# ------------------------------------------------------------------- 行情拉取 ----

def _pct_change_from_history(close_values: list[float], live_price: float, trading_days_back: int) -> Optional[float]:
    idx = -(trading_days_back + 1)
    if len(close_values) < trading_days_back + 1:
        return None
    base = close_values[idx]
    if not base:
        return None
    return round((live_price - base) / base * 100, 2)


def _fetch_live(symbol: str) -> Optional[dict]:
    """真的向 Yahoo Finance 发请求拉一支股票的完整行情快照，失败/查不到返回 None。"""
    try:
        ticker = yf.Ticker(symbol)
        fast_info = ticker.fast_info
        last_price = fast_info.get("lastPrice")
    except Exception as e:
        logger.warning(f"获取 {symbol} 行情失败: {e}")
        return None
    if not last_price:
        return None

    prev_close = fast_info.get("previousClose") or last_price
    change = last_price - prev_close
    change_percent = round((change / prev_close) * 100, 2) if prev_close else 0

    change_1w = None
    change_1m = None
    try:
        hist = ticker.history(period="3mo", interval="1d")
        closes = hist["Close"].tolist()
        change_1w = _pct_change_from_history(closes, last_price, 5)
        change_1m = _pct_change_from_history(closes, last_price, 21)
    except Exception as e:
        logger.warning(f"获取 {symbol} 历史涨幅失败，忽略: {e}")

    try:
        info = ticker.info
    except Exception as e:
        logger.warning(f"获取 {symbol} 公司概况失败，忽略: {e}")
        info = {}

    return {
        "name": info.get("longName") or info.get("shortName") or symbol,
        "sector": info.get("sector") or info.get("industry") or "--",
        "price": round(last_price, 2),
        "change": round(change, 2),
        "change_percent": change_percent,
        "change_1w": change_1w,
        "change_1m": change_1m,
        "day_high": fast_info.get("dayHigh") or last_price,
        "day_low": fast_info.get("dayLow") or last_price,
        "volume": fast_info.get("lastVolume"),
        "pe": round(info["trailingPE"], 2) if info.get("trailingPE") else None,
        "market_cap": fast_info.get("marketCap"),
    }


def _apply_live(row: WatchlistStock, live: dict) -> None:
    row.name = live["name"]
    row.sector = live["sector"]
    row.price = live["price"]
    row.change = live["change"]
    row.change_percent = live["change_percent"]
    row.change_1w = live["change_1w"]
    row.change_1m = live["change_1m"]
    row.day_high = live["day_high"]
    row.day_low = live["day_low"]
    row.volume = live["volume"]
    row.pe = live["pe"]
    row.market_cap = live["market_cap"]
    row.quote_updated_at = datetime.now(timezone.utc)


def _is_stale(row: WatchlistStock) -> bool:
    if row.quote_updated_at is None:
        return True
    updated_at = row.quote_updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - updated_at > timedelta(seconds=_QUOTE_TTL_SECONDS)


def _row_to_stock_item(row: WatchlistStock) -> dict:
    return {
        "symbol": row.symbol,
        "code": row.symbol,
        "name": row.name or row.symbol,
        "sector": row.sector or "--",
        "price": row.price or 0,
        "change": row.change or 0,
        "changePercent": row.change_percent or 0,
        "change1D": row.change_percent or 0,
        "change1W": row.change_1w,
        "change1M": row.change_1m,
        "high24h": row.day_high or row.price or 0,
        "low24h": row.day_low or row.price or 0,
        "volume": _format_volume(row.volume),
        "pe": row.pe,
        "marketCap": _format_market_cap(row.market_cap),
        "rsi": None,
        "macdSignal": None,
        "isFavorite": True,
        "tags": [],
        "kline1D": [],
        "kline1W": [],
        "kline1M": [],
        "orderBookBids": [],
        "orderBookAsks": [],
        "recentTrades": [],
        "optionsChain": [],
        "financials": {"revenue": [], "radar": [], "metrics": []},
    }


def list_watchlist_stocks(db: Session) -> list[dict]:
    rows = db.query(WatchlistStock).order_by(WatchlistStock.id).all()
    if not rows:
        return []

    stale_rows = [r for r in rows if _is_stale(r)]
    if stale_rows:
        with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(stale_rows))) as executor:
            live_results = list(executor.map(_fetch_live, [r.symbol for r in stale_rows]))
        for row, live in zip(stale_rows, live_results):
            if live:
                _apply_live(row, live)
            elif row.quote_updated_at is None:
                logger.warning(f"{row.symbol} 从未成功拉到过行情，本次也失败，列表里先不展示")
            # 刷新失败但之前有缓存数据：保留旧数据不动，不因为一次请求失败就把股票从列表里摘掉
        # 这个函数自己就是"写缓存"的地方，写完必须在这里提交，不然调用方一忘记 db.commit()，
        # 刚拉到的数据就白拉了——每次都会因为 quote_updated_at 没真的落盘而判定成"过期"，
        # 变成每次请求都重新打一遍 Yahoo Finance，缓存完全不起作用
        db.commit()

    # 只有从来没成功拉到过任何数据的（刚加进来第一次就失败，理论上不会发生，add 时已校验过）才跳过
    return [_row_to_stock_item(row) for row in rows if row.quote_updated_at is not None]


def _format_volume(volume: Optional[float]) -> str:
    if not volume:
        return "--"
    if volume >= 1_000_000:
        return f"{volume / 1_000_000:.1f}M"
    if volume >= 1_000:
        return f"{volume / 1_000:.1f}K"
    return str(int(volume))


def _format_market_cap(value: Optional[float]) -> str:
    if not value:
        return "--"
    if value >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.2f}T"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    return f"${value:.0f}"
