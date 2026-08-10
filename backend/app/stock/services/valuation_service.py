"""
估值分析：当前估值直接来自 market_service 的快照（yfinance 现成算好的倍数）；历史估值
自己拿 SEC 的季度财务数据算 TTM（滚动四个季度）指标，再配上对应时点的股价算出历史 PE/PS/
PB/EV-EBITDA 序列，取中位数和当前值所处的百分位。

计算历史倍数时，价格要用"财报实际披露之后"的股价，不能用财报所属期间结束当天的股价——
后者是那个时间点投资者根本还看不到的数字（10-Q/10-K 一般滞后期末 3~6 周才披露），用期末价
会造成"未来数据"提前泄漏进历史估值序列，参见十三节要求。所以这里按 filed（披露日）去找
最近的交易日收盘价，不是按 end（期末日）。

估值区间（悲观/基准/乐观）是研究模型，不是目标价预测：三档只是把"历史倍数的低/中/高分位"
乘上"未来一年市场一致预期 EPS"得到一个参考区间，所有输入假设都原样返回给前端展示，不包装成
确定性结论。
"""
from __future__ import annotations

from typing import Optional

import yfinance as yf
from loguru import logger
from sqlalchemy.orm import Session

from app.stock.services import cache_service

_PRICE_HISTORY_FULL_PERIOD = "5y"  # 冷启动时用
_PRICE_HISTORY_REFRESH_PERIOD = "1mo"  # 已有缓存时，增量刷新只拉最近一个月去补上新交易日
_PRICE_HISTORY_REFRESH_TTL_SECONDS = 3 * 3600
_PRICE_HISTORY_DATASET = "price_history_5y"


class ValuationError(Exception):
    pass


def get_price_history(db: Session, symbol: str) -> list[dict]:
    """valuation（历史估值分位）和 earnings（财报后价格反应）两个 dataset 都要用到同一份
    5 年日线收盘价，之前各拉各的——同一支股票短时间内先后打开这两个 tab，会对 Yahoo
    Finance 发两次一模一样的请求。这里缓存共享一份，谁先请求谁把缓存填上，另一个直接读。

    已经收盘的历史交易日不会再变，所以不是整份过期整份重拉：冷启动拉 5 年完整历史，
    之后每次只拉最近一个月去补上新增的交易日，跟历史合并，不用把 5 年的窗口重新请求
    一遍。"""

    def _fetch(period: str) -> list[dict]:
        try:
            hist = yf.Ticker(symbol).history(period=period, interval="1d")
        except Exception as e:
            raise ValuationError(f"获取 {symbol} 历史股价失败: {e}") from e
        if hist.empty:
            raise ValuationError(f"Yahoo Finance 查不到 {symbol} 的历史股价")
        return [{"date": d.strftime("%Y-%m-%d"), "close": round(float(row["Close"]), 4)} for d, row in hist.iterrows()]

    return cache_service.get_or_refresh_time_series(
        db, symbol, _PRICE_HISTORY_DATASET,
        time_key="date",
        refresh_ttl_seconds=_PRICE_HISTORY_REFRESH_TTL_SECONDS,
        fetch_full=lambda: _fetch(_PRICE_HISTORY_FULL_PERIOD),
        fetch_recent=lambda: _fetch(_PRICE_HISTORY_REFRESH_PERIOD),
    )


def _nearest_close_on_or_after(price_history: list[dict], target_date: str) -> Optional[float]:
    for p in price_history:
        if p["date"] >= target_date:
            return p["close"]
    return None


def _rolling_ttm(points: list[dict]) -> list[dict]:
    """points 是按 end 升序的季度点位，返回每个窗口(4 个连续季度)的 TTM 累计值，
    带上这个窗口里最新一季的 end/filed（决定用哪天的股价去对齐）。"""
    ttm = []
    for i in range(3, len(points)):
        window = points[i - 3 : i + 1]
        total = sum(p["val"] for p in window)
        ttm.append({"end": window[-1]["end"], "filed": window[-1]["filed"], "val": total})
    return ttm


def _percentile_rank(values: list[float], current: float) -> Optional[float]:
    if not values:
        return None
    below = sum(1 for v in values if v <= current)
    return round(below / len(values) * 100, 1)


def build_historical_multiples(financials_series: dict, price_history: list[dict], shares_outstanding_now: Optional[float]) -> dict:
    q = financials_series["quarterly"]
    instant = financials_series["instant"]

    revenue_ttm = _rolling_ttm(q["revenue"]) if q["revenue"] else []
    net_income_ttm = _rolling_ttm(q["net_income"]) if q["net_income"] else []

    diluted_shares_by_end = {p["end"]: p["val"] for p in q["diluted_shares"]}
    equity_by_end = {p["end"]: p["val"] for p in instant.get("stockholders_equity", [])}
    debt_by_end: dict[str, float] = {}
    for p in instant.get("long_term_debt", []):
        debt_by_end[p["end"]] = debt_by_end.get(p["end"], 0) + p["val"]
    for p in instant.get("short_term_debt", []):
        debt_by_end[p["end"]] = debt_by_end.get(p["end"], 0) + p["val"]
    cash_by_end = {p["end"]: p["val"] for p in instant.get("cash_and_equivalents", [])}

    def shares_at(end: str) -> Optional[float]:
        return diluted_shares_by_end.get(end) or shares_outstanding_now

    pe_series, ps_series, pb_series = [], [], []

    for point in net_income_ttm:
        price = _nearest_close_on_or_after(price_history, point["filed"])
        shares = shares_at(point["end"])
        if not price or not shares or point["val"] <= 0:
            continue
        eps_ttm = point["val"] / shares
        pe_series.append({"end": point["end"], "val": round(price / eps_ttm, 2)})

    for point in revenue_ttm:
        price = _nearest_close_on_or_after(price_history, point["filed"])
        shares = shares_at(point["end"])
        if not price or not shares or point["val"] <= 0:
            continue
        market_cap = price * shares
        ps_series.append({"end": point["end"], "val": round(market_cap / point["val"], 2)})

    for end, equity in equity_by_end.items():
        # 用披露 stockholders equity 的那一期财报的 filed 日期找股价——瞬时科目直接找同一
        # end 对应的原始条目里的 filed，为了简单这里退化成用 revenue 序列里同 end 的 filed
        filed = next((p["filed"] for p in q["revenue"] if p["end"] == end), None)
        if not filed or equity <= 0:
            continue
        price = _nearest_close_on_or_after(price_history, filed)
        shares = shares_at(end)
        if not price or not shares:
            continue
        book_value_per_share = equity / shares
        if book_value_per_share <= 0:
            continue
        pb_series.append({"end": end, "val": round(price / book_value_per_share, 2)})
    pb_series.sort(key=lambda p: p["end"])

    def summarize(series: list[dict]) -> dict:
        if not series:
            return {"series": [], "current": None, "median": None, "percentile": None, "min": None, "max": None}
        values = [p["val"] for p in series]
        current = series[-1]["val"]
        sorted_vals = sorted(values)
        median = sorted_vals[len(sorted_vals) // 2]
        return {
            "series": series,
            "current": current,
            "median": round(median, 2),
            "percentile": _percentile_rank(values, current),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
        }

    return {
        "pe": summarize(pe_series),
        "ps": summarize(ps_series),
        "pb": summarize(pb_series),
    }


def build_valuation_scenarios(pe_history: dict, next_year_eps_estimate: Optional[float], current_price: Optional[float]) -> Optional[dict]:
    """
    这只是一个透明的研究模型：拿历史 PE 的低/中/高分位（P25/中位数/P75）乘上市场对未来
    一年 EPS 的一致预期，得到一个参考价值区间——不是目标价，也不保证会兑现，所有输入
    （用的哪个分位、哪个 EPS 预期）原样带给前端展示。
    """
    series = pe_history.get("series") or []
    if len(series) < 8 or not next_year_eps_estimate or not current_price:
        return None
    values = sorted(p["val"] for p in series)
    n = len(values)
    p25 = values[int(n * 0.25)]
    p50 = values[n // 2]
    p75 = values[min(int(n * 0.75), n - 1)]

    def scenario(multiple: float, growth_note: str) -> dict:
        implied_price = round(multiple * next_year_eps_estimate, 2)
        return {
            "pe_multiple": round(multiple, 2),
            "eps_assumption": next_year_eps_estimate,
            "implied_price": implied_price,
            "vs_current_percent": round((implied_price - current_price) / current_price * 100, 2),
            "growth_assumption_note": growth_note,
        }

    return {
        "bear": scenario(p25, "历史 PE 25 分位，对应偏悲观的估值收缩情景"),
        "base": scenario(p50, "历史 PE 中位数，对应估值维持历史中枢情景"),
        "bull": scenario(p75, "历史 PE 75 分位，对应估值扩张情景"),
        "disclaimer": "这是基于历史估值区间和市场一致预期 EPS 的研究模型推导，不构成目标价或收益承诺，所有假设已在上方列出。",
    }
