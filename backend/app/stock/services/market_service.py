"""
公司摘要区 + 核心指标卡用到的"当前快照"数据：价格、涨跌、市值、行业、以及一批估值/
盈利能力/负债率指标。全部来自 yfinance（免费、不需要 API Key），和自选股/K线模块用的
是同一个数据源，行为、字段风格保持一致。

yfinance 的 fast_info 负责价格类字段（实时、快），.info 负责相对静态的公司资料和一批
现成算好的比率（负责慢，单支股票要 2~3 秒）。ROIC 不是 .info 里的现成字段，这里自己用
营业利润和投入资本估算（税后经营利润 / (有息负债 + 股东权益 - 现金)）。
"""
from __future__ import annotations

from typing import Optional

import yfinance as yf
from loguru import logger


class MarketDataError(Exception):
    pass


def get_snapshot(symbol: str) -> dict:
    """返回一个未加工的原始快照 dict，字段可能为 None（yfinance 对应字段没有值）——
    调用方（fundamentals service 层）负责把 None 翻译成"暂无数据"，这里不瞎补默认值。"""
    try:
        ticker = yf.Ticker(symbol)
        fast_info = ticker.fast_info
        last_price = fast_info.get("lastPrice")
    except Exception as e:
        raise MarketDataError(f"获取 {symbol} 实时行情失败: {e}") from e
    if not last_price:
        raise MarketDataError(f"Yahoo Finance 查不到 {symbol} 的行情，请确认代码是否正确")

    prev_close = fast_info.get("previousClose") or last_price
    change = last_price - prev_close
    change_percent = round((change / prev_close) * 100, 2) if prev_close else None

    try:
        info = ticker.info
    except Exception as e:
        logger.warning(f"获取 {symbol} 公司概况失败，只返回价格类字段: {e}")
        info = {}

    total_debt = info.get("totalDebt")
    total_cash = info.get("totalCash")
    net_debt = (total_debt - total_cash) if (total_debt is not None and total_cash is not None) else None

    operating_margin = info.get("operatingMargins")
    ebit = info.get("ebitda")  # yfinance 只给 EBITDA，没有单独 EBIT 字段
    roic = _estimate_roic(info)

    free_cashflow = info.get("freeCashflow")
    market_cap = info.get("marketCap")
    fcf_yield = round(free_cashflow / market_cap * 100, 2) if free_cashflow and market_cap else None

    return {
        "symbol": symbol,
        "name": info.get("longName") or info.get("shortName") or symbol,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "price": round(last_price, 2),
        "change": round(change, 2),
        "change_percent": change_percent,
        "prev_close": prev_close,
        "market_cap": market_cap,
        "enterprise_value": info.get("enterpriseValue"),
        "shares_outstanding": info.get("sharesOutstanding"),
        "beta": info.get("beta"),
        "employees": info.get("fullTimeEmployees"),
        # 估值倍数
        "pe_ttm": info.get("trailingPE"),
        "pe_forward": info.get("forwardPE"),
        "peg_ratio": info.get("pegRatio") or info.get("trailingPegRatio"),
        "ps_ttm": info.get("priceToSalesTrailing12Months"),
        "pb": info.get("priceToBook"),
        "ev_ebitda": info.get("enterpriseToEbitda"),
        "ev_revenue": info.get("enterpriseToRevenue"),
        "dividend_yield": info.get("dividendYield"),
        "earnings_yield": round(1 / info["trailingPE"] * 100, 2) if info.get("trailingPE") else None,
        "fcf_yield": fcf_yield,
        # 盈利能力
        "roe": info.get("returnOnEquity"),
        "roa": info.get("returnOnAssets"),
        "roic": roic,
        "gross_margin": info.get("grossMargins"),
        "operating_margin": operating_margin,
        "net_margin": info.get("profitMargins"),
        "ebitda": ebit,
        # 资产负债
        "debt_to_equity": info.get("debtToEquity"),
        "total_debt": total_debt,
        "total_cash": total_cash,
        "net_debt": net_debt,
        "current_ratio": info.get("currentRatio"),
        "quick_ratio": info.get("quickRatio"),
        # 增长
        "revenue_growth": info.get("revenueGrowth"),
        "earnings_growth": info.get("earningsGrowth"),
        "eps_ttm": info.get("trailingEps"),
        "eps_forward": info.get("forwardEps"),
        "book_value": info.get("bookValue"),
    }


def _estimate_roic(info: dict) -> Optional[float]:
    """ROIC ≈ 税后经营利润 NOPAT / 投入资本 (有息负债 + 股东权益 - 现金)。
    yfinance 没有现成 ROIC 字段，这里用 .info 里已有的字段估算，公式和输入都在这，
    不是黑盒——前端 Tooltip 需要能讲清楚这是"估算值"而不是公司直接披露的数字。"""
    ebit = info.get("ebitda")
    total_debt = info.get("totalDebt")
    total_cash = info.get("totalCash")
    book_value_per_share = info.get("bookValue")
    shares_outstanding = info.get("sharesOutstanding")
    if ebit is None or total_debt is None or total_cash is None or not book_value_per_share or not shares_outstanding:
        return None
    equity_value = book_value_per_share * shares_outstanding
    invested_capital = total_debt + equity_value - total_cash
    if invested_capital <= 0:
        return None
    # 用 21% 的美国联邦法定税率粗略估算税后经营利润；没有更细的分部税率数据，
    # 这是行业内常见的简化处理，不追求和公司实际有效税率完全一致
    assumed_tax_rate = 0.21
    nopat = ebit * (1 - assumed_tax_rate)
    return round(nopat / invested_capital * 100, 2)


def get_next_earnings_info(symbol: str) -> dict:
    """下次财报日期 + 市场一致预期区间，来自 yfinance calendar，免费无 key。"""
    try:
        calendar = yf.Ticker(symbol).calendar
    except Exception as e:
        logger.warning(f"获取 {symbol} 财报日历失败: {e}")
        return {}
    if not calendar:
        return {}
    earnings_dates = calendar.get("Earnings Date") or []
    return {
        "next_earnings_date": earnings_dates[0].isoformat() if earnings_dates else None,
        "eps_estimate_avg": calendar.get("Earnings Average"),
        "eps_estimate_low": calendar.get("Earnings Low"),
        "eps_estimate_high": calendar.get("Earnings High"),
        "revenue_estimate_avg": calendar.get("Revenue Average"),
        "revenue_estimate_low": calendar.get("Revenue Low"),
        "revenue_estimate_high": calendar.get("Revenue High"),
    }
