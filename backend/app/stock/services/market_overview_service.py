"""
大盘行情：主要美股指数快照/走势 + 近期大事件（美联储议息会议、"七姐妹"财报、CPI）。

指数和财报日期是 yfinance 实时数据（免费、不需要 Key），和自选股/K线用的是同一套
fast_info/history/calendar 接口。FOMC 会议日期、CPI 发布日期这类"未来公开日程"yfinance
不提供，也没有免费的经济日历接口（Finnhub 的 /calendar/economic 实测是付费功能，403），
所以这部分用美联储官网（federalreserve.gov）和 BLS 官方公布的日程整理成静态参考数据——
都是已经正式公布的公开日期，不是编的，但需要每年手动更新一次（美联储每年年中公布下一年
的会议日程），过期后要记得刷新 _FOMC_MEETINGS_2026 / _CONFIRMED_CPI_RELEASES。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

import yfinance as yf
from loguru import logger
from sqlalchemy.orm import Session

from app.stock.services import cache_service

_INDEX_DEFINITIONS = [
    {"symbol": "^GSPC", "name": "S&P 500", "name_cn": "标普500"},
    {"symbol": "^IXIC", "name": "Nasdaq Composite", "name_cn": "纳斯达克综合指数"},
    {"symbol": "^NDX", "name": "Nasdaq 100", "name_cn": "纳斯达克100"},
    {"symbol": "^DJI", "name": "Dow Jones", "name_cn": "道琼斯工业指数"},
    {"symbol": "^RUT", "name": "Russell 2000", "name_cn": "罗素2000"},
    {"symbol": "^VIX", "name": "VIX", "name_cn": "恐慌指数"},
]

_MAG7 = [
    {"symbol": "AAPL", "name_cn": "苹果"},
    {"symbol": "MSFT", "name_cn": "微软"},
    {"symbol": "GOOGL", "name_cn": "谷歌"},
    {"symbol": "AMZN", "name_cn": "亚马逊"},
    {"symbol": "NVDA", "name_cn": "英伟达"},
    {"symbol": "META", "name_cn": "Meta"},
    {"symbol": "TSLA", "name_cn": "特斯拉"},
]

# 来源：federalreserve.gov 2026-08 公布的 2026 年 FOMC 会议日程（monetary20240809a.htm 及
# 各次会议页面 fomcpresconf2026****.htm），逐条核对过。有 dot_plot=True 的是 3/6/9/12 月，
# 会公布经济预测摘要（SEP，含点阵图），历来对市场影响更大。
_FOMC_MEETINGS_2026 = [
    {"start": "2026-01-27", "end": "2026-01-28", "dot_plot": False},
    {"start": "2026-03-17", "end": "2026-03-18", "dot_plot": True},
    {"start": "2026-04-28", "end": "2026-04-29", "dot_plot": False},
    {"start": "2026-06-16", "end": "2026-06-17", "dot_plot": True},
    {"start": "2026-07-28", "end": "2026-07-29", "dot_plot": False},
    {"start": "2026-09-15", "end": "2026-09-16", "dot_plot": True},
    {"start": "2026-10-27", "end": "2026-10-28", "dot_plot": False},
    {"start": "2026-12-08", "end": "2026-12-09", "dot_plot": True},
]

# 只放确认过的具体日期，不去推算"每月第二周大概是哪天"这种近似值——CPI 完整全年日程
# 需要去 bls.gov 官方日历核对，这里先放下一期确认过的，其余标"预计"引导用户自己查
_CONFIRMED_CPI_RELEASES = [
    {"date": "2026-08-12", "covers": "2026-07", "confirmed": True},
]

_ECONOMIC_CALENDAR_SOURCE_URL = "https://www.bls.gov/schedule/news_release/cpi.htm"
_FOMC_CALENDAR_SOURCE_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"


class MarketOverviewError(Exception):
    pass


def _quote_for(symbol: str) -> Optional[dict]:
    try:
        fast_info = yf.Ticker(symbol).fast_info
        last_price = fast_info.get("lastPrice")
    except Exception as e:
        logger.warning(f"获取指数 {symbol} 行情失败: {e}")
        return None
    if not last_price:
        return None
    prev_close = fast_info.get("previousClose") or last_price
    change = last_price - prev_close
    change_percent = round((change / prev_close) * 100, 2) if prev_close else None
    return {
        "price": round(last_price, 2),
        "change": round(change, 2),
        "change_percent": change_percent,
        "day_high": fast_info.get("dayHigh"),
        "day_low": fast_info.get("dayLow"),
        "year_high": fast_info.get("yearHigh"),
        "year_low": fast_info.get("yearLow"),
    }


def get_index_quotes(db: Session, force_refresh: bool = False) -> dict:
    dataset = "market_indices"
    cache_key = "US_MARKET"
    if not force_refresh:
        cached = cache_service.get_cached(db, cache_key, dataset)
        if cached:
            return cached["data"]

    indices = []
    for definition in _INDEX_DEFINITIONS:
        quote = _quote_for(definition["symbol"])
        indices.append({**definition, **(quote or {}), "available": quote is not None})

    data = {"indices": indices}
    cache_service.save_cache(db, cache_key, dataset, data, sources=["Yahoo Finance"])
    return data


_PERIOD_TO_YF = {"1M": "1mo", "3M": "3mo", "6M": "6mo", "YTD": "ytd", "1Y": "1y"}


def get_index_history(db: Session, symbol: str, period: str = "6M") -> list[dict]:
    yf_period = _PERIOD_TO_YF.get(period)
    if not yf_period:
        raise MarketOverviewError(f"不支持的周期: {period}")

    dataset = f"market_index_history_{period}"
    cached = cache_service.get_cached(db, symbol, dataset)
    if cached:
        return cached["data"]["points"]

    try:
        hist = yf.Ticker(symbol).history(period=yf_period, interval="1d")
    except Exception as e:
        raise MarketOverviewError(f"获取 {symbol} 历史走势失败: {e}") from e
    if hist.empty:
        raise MarketOverviewError(f"Yahoo Finance 查不到 {symbol} 的历史走势")

    points = [{"date": d.strftime("%Y-%m-%d"), "close": round(float(row["Close"]), 4)} for d, row in hist.iterrows()]
    cache_service.save_cache(db, symbol, dataset, {"points": points}, sources=["Yahoo Finance"])
    return points


def get_mag7_earnings(db: Session, force_refresh: bool = False) -> dict:
    dataset = "mag7_earnings"
    cache_key = "US_MARKET"
    if not force_refresh:
        cached = cache_service.get_cached(db, cache_key, dataset)
        if cached:
            return cached["data"]

    companies = []
    for company in _MAG7:
        entry = {**company}
        try:
            calendar = yf.Ticker(company["symbol"]).calendar or {}
            earnings_dates = calendar.get("Earnings Date") or []
            entry["next_earnings_date"] = earnings_dates[0].isoformat() if earnings_dates else None
            entry["eps_estimate"] = calendar.get("Earnings Average")
            entry["revenue_estimate"] = calendar.get("Revenue Average")
            entry["available"] = True
        except Exception as e:
            logger.warning(f"获取 {company['symbol']} 财报日期失败: {e}")
            entry["next_earnings_date"] = None
            entry["available"] = False
        companies.append(entry)

    data = {"companies": companies}
    cache_service.save_cache(db, cache_key, dataset, data, sources=["Yahoo Finance"])
    return data


def get_upcoming_events(db: Session, window_days_past: int = 14, window_days_future: int = 120) -> dict:
    """把 FOMC 会议、"七姐妹"财报、CPI 发布合并成一条时间线，按日期排序，只保留
    [今天-window_days_past, 今天+window_days_future] 窗口内的，避免列表里塞满明年的日期。"""
    today = datetime.now(timezone.utc).date()
    window_start = today - timedelta(days=window_days_past)
    window_end = today + timedelta(days=window_days_future)

    events: list[dict] = []

    for meeting in _FOMC_MEETINGS_2026:
        meeting_date = date.fromisoformat(meeting["end"])
        if window_start <= meeting_date <= window_end:
            events.append(
                {
                    "type": "fomc",
                    "date": meeting["end"],
                    "date_range": f"{meeting['start']} ~ {meeting['end']}",
                    "title": "美联储 FOMC 议息会议",
                    "detail": "公布利率决议和经济预测摘要（点阵图）" if meeting["dot_plot"] else "公布利率决议",
                    "importance": "high" if meeting["dot_plot"] else "medium",
                    "source_url": _FOMC_CALENDAR_SOURCE_URL,
                    "confirmed": True,
                }
            )

    for release in _CONFIRMED_CPI_RELEASES:
        release_date = date.fromisoformat(release["date"])
        if window_start <= release_date <= window_end:
            events.append(
                {
                    "type": "cpi",
                    "date": release["date"],
                    "date_range": release["date"],
                    "title": "美国 CPI 消费者物价指数",
                    "detail": f"公布 {release['covers']} 通胀数据",
                    "importance": "high",
                    "source_url": _ECONOMIC_CALENDAR_SOURCE_URL,
                    "confirmed": release["confirmed"],
                }
            )

    earnings_data = get_mag7_earnings(db)
    for company in earnings_data["companies"]:
        if not company.get("next_earnings_date"):
            continue
        earnings_date = date.fromisoformat(company["next_earnings_date"])
        if window_start <= earnings_date <= window_end:
            events.append(
                {
                    "type": "earnings",
                    "date": company["next_earnings_date"],
                    "date_range": company["next_earnings_date"],
                    "title": f"{company['name_cn']} ({company['symbol']}) 财报",
                    "detail": f"EPS 一致预期 {round(company['eps_estimate'], 2)}" if company.get("eps_estimate") else "财报发布",
                    "importance": "medium",
                    "source_url": None,
                    "confirmed": True,
                    "symbol": company["symbol"],
                }
            )

    events.sort(key=lambda e: e["date"])
    return {
        "events": events,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "reference_note": "美联储会议日期来自 federalreserve.gov 官方公布日程；CPI 发布日期来自 BLS，"
        "只收录已经确认过的具体日期；完整经济日历请以官方网站为准。",
    }
