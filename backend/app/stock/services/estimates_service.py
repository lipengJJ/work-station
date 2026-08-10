"""
财报预期差：yfinance 免费暴露了 Yahoo Finance 网站"Analysis"页背后的同一批数据——
分析师一致预期营收/EPS、EPS 历史 surprise、90 天评级升降级——不需要 Finnhub/FMP 的
付费级接口。

Surprise 按题目给的公式自己算（不是直接信 yfinance 自带的 Surprise(%) 列），公式：
EPS Surprise = (实际EPS - 预期EPS) / abs(预期EPS)
Revenue Surprise = (实际营收 - 预期营收) / abs(预期营收)

盘后涨跌 yfinance 免费接口拿不到分钟级盘后行情，明确标记"数据不可用"，不伪造；下一
交易日和 5 个交易日涨跌用已经在拉的日线收盘价自己算，是可验证的真实计算。
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf
from loguru import logger


class EstimatesError(Exception):
    pass


def get_estimates_and_surprises(symbol: str) -> dict:
    ticker = yf.Ticker(symbol)

    revenue_estimate = _safe_df(lambda: ticker.revenue_estimate, symbol, "revenue_estimate")
    earnings_estimate = _safe_df(lambda: ticker.earnings_estimate, symbol, "earnings_estimate")
    eps_trend = _safe_df(lambda: ticker.eps_trend, symbol, "eps_trend")
    earnings_dates = _safe_df(lambda: ticker.earnings_dates, symbol, "earnings_dates")
    upgrades_downgrades = _safe_df(lambda: ticker.upgrades_downgrades, symbol, "upgrades_downgrades")

    history: list[dict] = []
    if earnings_dates is not None:
        for dt, row in earnings_dates.sort_index().iterrows():
            eps_estimate = row.get("EPS Estimate")
            eps_actual = row.get("Reported EPS")
            eps_surprise_pct = None
            if pd.notna(eps_estimate) and pd.notna(eps_actual) and eps_estimate != 0:
                eps_surprise_pct = round(float((eps_actual - eps_estimate) / abs(eps_estimate) * 100), 2)
            history.append(
                {
                    "report_date": dt.strftime("%Y-%m-%d"),
                    "eps_estimate": _num(eps_estimate),
                    "eps_actual": _num(eps_actual),
                    "eps_surprise_percent": eps_surprise_pct,
                }
            )

    upgrades_count, downgrades_count = _count_recent_grade_changes(upgrades_downgrades)

    return {
        "revenue_estimate": _df_to_records(revenue_estimate),
        "earnings_estimate": _df_to_records(earnings_estimate),
        "eps_trend": _df_to_records(eps_trend),
        "eps_surprise_history": history,
        "recent_90d_upgrades": upgrades_count,
        "recent_90d_downgrades": downgrades_count,
        "recent_grade_changes": _df_to_records(upgrades_downgrades.head(20)) if upgrades_downgrades is not None else [],
    }


def compute_post_earnings_reaction(earnings_dates: list[str], price_history: list[dict]) -> list[dict]:
    """财报发布后下一交易日 / 5个交易日涨跌，用已有的日线收盘价算，可验证、不伪造。
    盘后（当天收盘后到次日开盘前）的涨跌 yfinance 免费接口没有分钟级数据，明确标不可用。"""
    dates = [p["date"] for p in price_history]
    closes = {p["date"]: p["close"] for p in price_history}

    results = []
    for report_date in earnings_dates:
        idx = next((i for i, d in enumerate(dates) if d >= report_date), None)
        if idx is None or idx == 0:
            results.append(
                {
                    "report_date": report_date,
                    "after_hours_change_percent": None,
                    "after_hours_available": False,
                    "next_day_change_percent": None,
                    "five_day_change_percent": None,
                }
            )
            continue
        base_close = closes[dates[idx - 1]]
        next_day_close = closes[dates[idx]] if idx < len(dates) else None
        five_day_idx = idx + 4
        five_day_close = closes[dates[five_day_idx]] if five_day_idx < len(dates) else None

        results.append(
            {
                "report_date": report_date,
                "after_hours_change_percent": None,
                "after_hours_available": False,
                "next_day_change_percent": round((next_day_close - base_close) / base_close * 100, 2) if next_day_close else None,
                "five_day_change_percent": round((five_day_close - base_close) / base_close * 100, 2) if five_day_close else None,
            }
        )
    return results


def _safe_df(fn, symbol: str, label: str):
    try:
        df = fn()
        return df if df is not None and not df.empty else None
    except Exception as e:
        logger.warning(f"获取 {symbol} 的 {label} 失败，忽略: {e}")
        return None


def _num(v) -> Optional[float]:
    """转成原生 Python float——numpy.float64 直接扔给 FastAPI 的 JSON 编码器会报错，
    round() 作用在 numpy 标量上返回的还是 numpy 标量，必须显式 float() 一次。"""
    return None if v is None or pd.isna(v) else float(v)


def _to_native(v):
    if v is None:
        return None
    if isinstance(v, (list, dict)):
        return v
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, np.generic):
        return v.item()
    return v


def _df_to_records(df) -> list[dict]:
    if df is None:
        return []
    records = df.reset_index().to_dict(orient="records")
    return [{str(k): _to_native(v) for k, v in r.items()} for r in records]


def _count_recent_grade_changes(df) -> tuple[Optional[int], Optional[int]]:
    if df is None:
        return None, None
    try:
        cutoff = pd.Timestamp.now(tz=df.index.tz) - pd.Timedelta(days=90)
        recent = df[df.index >= cutoff]
        action_col = recent.get("Action")
        if action_col is None:
            return None, None
        upgrades = int((action_col == "up").sum())
        downgrades = int((action_col == "down").sum())
        return upgrades, downgrades
    except Exception as e:
        logger.warning(f"统计最近90天评级升降级失败: {e}")
        return None, None
