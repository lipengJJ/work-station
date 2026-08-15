"""
把各个 client/service 拼成 API 路由要的 9 份 dataset。每个 build_* 函数职责一样：
先查缓存，缓存命中直接返回；没命中就分别去请求各个数据源，每个数据源单独 try/except，
一个失败不影响其它——返回的 envelope 里的 partial_failures 记录哪些子数据源
这次没成功，前端据此显示"部分数据获取失败"而不是整页报错。

原始的 SEC submissions / company facts 请求量比较大，这两份本身也作为独立 dataset
缓存起来（sec_submissions / sec_company_facts），financials/valuation/filings/
insiders/risks 这几个上层 dataset 复用同一份缓存，不会重复打 SEC。
"""
from __future__ import annotations

from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from app.stock.services import (
    ai_analysis_service,
    cache_service,
    estimates_service,
    filings_service,
    financials_service,
    insiders_service,
    institutions_service,
    market_service,
    risk_service,
    sec_client,
    valuation_service,
)


class FundamentalsNotFound(Exception):
    pass


def _envelope(data: dict, sources: list[str], partial_failures: list[str], from_cache: bool = False, fetched_at: Optional[str] = None) -> dict:
    import datetime as _dt

    return {
        "data": data,
        "sources": sources,
        "partial_failures": partial_failures,
        "fetched_at": fetched_at or _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "from_cache": from_cache,
    }


def _resolve_cik(db: Session, symbol: str) -> dict:
    """解析 SEC 备案主体（CIK）。找不到代码抛 FundamentalsNotFound；
    SEC 网络失败（SecError）也统一转成 FundamentalsNotFound——各 build_* 都按
    "部分数据源失败、降级 partial_failures"处理，不能让 SEC 超时把整个接口打成 500。"""
    try:
        info = sec_client.get_cik(db, symbol)
    except sec_client.SecError as e:
        logger.warning(f"{symbol} 的 SEC 备案查询失败: {e}")
        raise FundamentalsNotFound(f"SEC 数据源暂时不可用: {e}") from e
    if not info:
        logger.warning(f"找不到股票代码 {symbol} 对应的 SEC 备案主体")
        raise FundamentalsNotFound(f"找不到股票代码 {symbol} 对应的 SEC 备案主体，请确认代码是否正确")
    return info


def _get_submissions(db: Session, symbol: str, cik_str: str) -> tuple[Optional[dict], list[str]]:
    cached = cache_service.get_cached(db, symbol, "sec_submissions")
    if cached:
        return cached["data"], []
    try:
        submissions = sec_client.get_submissions(db, cik_str)
        cache_service.save_cache(db, symbol, "sec_submissions", submissions, ["SEC EDGAR Submissions API"])
        return submissions, []
    except sec_client.SecError as e:
        logger.warning(f"{symbol} 的 SEC submissions 请求失败: {e}")
        return None, [f"SEC submissions 请求失败: {e}"]


def _get_company_facts(db: Session, symbol: str, cik_str: str) -> tuple[Optional[dict], list[str]]:
    cached = cache_service.get_cached(db, symbol, "sec_company_facts")
    if cached:
        return cached["data"], []
    try:
        facts = sec_client.get_company_facts(db, cik_str)
        cache_service.save_cache(db, symbol, "sec_company_facts", facts, ["SEC EDGAR XBRL Company Facts API"])
        return facts, []
    except sec_client.SecError as e:
        logger.warning(f"{symbol} 的 SEC company facts 请求失败: {e}")
        return None, [f"SEC company facts 请求失败: {e}"]


# ---------------------------------------------------------------------- overview ----

def build_overview(db: Session, symbol: str, force_refresh: bool = False) -> dict:
    if not force_refresh:
        cached = cache_service.get_cached(db, symbol, "overview")
        if cached:
            return cached

    sources, failures = [], []
    snapshot: dict = {}
    try:
        snapshot = market_service.get_snapshot(symbol)
        sources.append("Yahoo Finance")
    except market_service.MarketDataError as e:
        failures.append(f"实时行情获取失败: {e}")

    earnings_info: dict = {}
    try:
        earnings_info = market_service.get_next_earnings_info(symbol)
    except Exception as e:
        failures.append(f"财报日历获取失败: {e}")

    cik_info: dict = {}
    try:
        cik_info = _resolve_cik(db, symbol)
        sources.append("SEC EDGAR company_tickers.json")
    except FundamentalsNotFound as e:
        failures.append(str(e))

    if not snapshot and not cik_info:
        raise FundamentalsNotFound(f"找不到 {symbol} 相关的行情或备案数据，请确认代码是否正确")

    data = {**snapshot, **earnings_info, "cik": cik_info.get("cik"), "sec_entity_name": cik_info.get("title")}
    envelope = _envelope(data, sources, failures)
    cache_service.save_cache(db, symbol, "overview", data, sources, failures)
    return envelope


# --------------------------------------------------------------------- financials ----

def _load_financial_series(db: Session, symbol: str) -> tuple[Optional[dict], list[str], list[str]]:
    sources, failures = [], []
    cik_info = _resolve_cik(db, symbol)
    facts, facts_failures = _get_company_facts(db, symbol, cik_info["cik_str"])
    failures.extend(facts_failures)
    if not facts:
        return None, sources, failures
    sources.append("SEC EDGAR XBRL Company Facts API")
    series = financials_service.extract_all_series(facts)
    return series, sources, failures


def build_financials(db: Session, symbol: str, force_refresh: bool = False) -> dict:
    if not force_refresh:
        cached = cache_service.get_cached(db, symbol, "financials")
        if cached:
            return cached

    series, sources, failures = _load_financial_series(db, symbol)
    if series is None:
        raise FundamentalsNotFound(f"暂时无法获取 {symbol} 的 SEC 财务数据")

    growth = financials_service.build_growth_and_margins(series)
    red_flags = financials_service.build_red_flags(series, growth)
    data = {"series": series, "growth_and_margins": growth, "red_flags": red_flags}

    envelope = _envelope(data, sources, failures)
    cache_service.save_cache(db, symbol, "financials", data, sources, failures)
    return envelope


# ---------------------------------------------------------------------- valuation ----

def build_valuation(db: Session, symbol: str, force_refresh: bool = False) -> dict:
    if not force_refresh:
        cached = cache_service.get_cached(db, symbol, "valuation")
        if cached:
            return cached

    sources, failures = [], []
    current: dict = {}
    try:
        current = market_service.get_snapshot(symbol)
        sources.append("Yahoo Finance")
    except market_service.MarketDataError as e:
        failures.append(f"当前估值快照获取失败: {e}")

    historical: dict = {}
    scenarios = None
    try:
        series, fin_sources, fin_failures = _load_financial_series(db, symbol)
        sources.extend(fin_sources)
        failures.extend(fin_failures)
        if series:
            price_history = valuation_service.get_price_history(db, symbol)
            sources.append("Yahoo Finance 历史股价")
            historical = valuation_service.build_historical_multiples(series, price_history, current.get("shares_outstanding"))

            next_year_eps = current.get("eps_forward")
            scenarios = valuation_service.build_valuation_scenarios(historical.get("pe", {}), next_year_eps, current.get("price"))
    except (valuation_service.ValuationError, FundamentalsNotFound) as e:
        failures.append(f"历史估值计算失败: {e}")

    data = {"current": current, "historical": historical, "scenarios": scenarios}
    envelope = _envelope(data, sources, failures)
    cache_service.save_cache(db, symbol, "valuation", data, sources, failures)
    return envelope


# ----------------------------------------------------------------------- earnings ----

def build_earnings(db: Session, symbol: str, force_refresh: bool = False) -> dict:
    if not force_refresh:
        cached = cache_service.get_cached(db, symbol, "earnings")
        if cached:
            return cached

    sources, failures = [], []
    estimates: dict = {}
    try:
        estimates = estimates_service.get_estimates_and_surprises(symbol)
        sources.append("Yahoo Finance 分析师一致预期")
    except Exception as e:
        failures.append(f"分析师预期获取失败: {e}")

    reactions: list[dict] = []
    try:
        price_history = valuation_service.get_price_history(db, symbol)
        report_dates = [h["report_date"] for h in estimates.get("eps_surprise_history", []) if h.get("eps_actual") is not None]
        reactions = estimates_service.compute_post_earnings_reaction(report_dates[-8:], price_history)
        sources.append("Yahoo Finance 历史股价（用于计算财报后价格反应）")
    except Exception as e:
        failures.append(f"财报后价格反应计算失败: {e}")

    data = {**estimates, "post_earnings_reactions": reactions}
    envelope = _envelope(data, sources, failures)
    cache_service.save_cache(db, symbol, "earnings", data, sources, failures)
    return envelope


# ------------------------------------------------------------------------ filings ----

def _load_filings(db: Session, symbol: str) -> tuple[list[dict], dict, list[str], list[str]]:
    sources, failures = [], []
    cik_info = _resolve_cik(db, symbol)
    submissions, sub_failures = _get_submissions(db, symbol, cik_info["cik_str"])
    failures.extend(sub_failures)
    if not submissions:
        return [], cik_info, sources, failures
    sources.append("SEC EDGAR Submissions API")
    filings = filings_service.list_filings(submissions, cik=cik_info["cik"], limit=500)
    return filings, cik_info, sources, failures


def build_filings(db: Session, symbol: str, force_refresh: bool = False) -> dict:
    if not force_refresh:
        cached = cache_service.get_cached(db, symbol, "filings")
        if cached:
            return cached

    filings, _cik_info, sources, failures = _load_filings(db, symbol)
    grouped = filings_service.group_by_category(filings)
    data = {"filings": filings, "grouped": {k: len(v) for k, v in grouped.items()}}
    envelope = _envelope(data, sources, failures)
    cache_service.save_cache(db, symbol, "filings", data, sources, failures)
    return envelope


# -------------------------------------------------------------------- institutions ----

def build_institutions(db: Session, symbol: str, force_refresh: bool = False) -> dict:
    if not force_refresh:
        cached = cache_service.get_cached(db, symbol, "institutions")
        if cached:
            return cached

    data = institutions_service.get_institutional_holdings(db, symbol)
    sources = [data["provider"]] if data.get("provider") else []
    envelope = _envelope(data, sources, [])
    cache_service.save_cache(db, symbol, "institutions", data, sources, [])
    return envelope


# ------------------------------------------------------------------------ insiders ----

def build_insiders(db: Session, symbol: str, force_refresh: bool = False) -> dict:
    if not force_refresh:
        cached = cache_service.get_cached(db, symbol, "insiders")
        if cached:
            return cached

    filings, cik_info, sources, failures = _load_filings(db, symbol)
    form4_filings = [f for f in filings if f["category"] == "Form 4"]
    transactions, parse_failures = insiders_service.get_insider_transactions(
        db, cik=cik_info["cik"], cik_str=cik_info["cik_str"], form4_filings=form4_filings, limit=20
    )
    if transactions:
        sources.append("SEC EDGAR Form 4 原始 XML")
    failures.extend([f"Form 4 解析失败: {f}" for f in parse_failures])

    data = {"transactions": transactions, "total_form4_filings": len(form4_filings)}
    envelope = _envelope(data, sources, failures)
    cache_service.save_cache(db, symbol, "insiders", data, sources, failures)
    return envelope


# --------------------------------------------------------------------------- risks ----

def build_risks(db: Session, symbol: str, force_refresh: bool = False) -> dict:
    if not force_refresh:
        cached = cache_service.get_cached(db, symbol, "risks")
        if cached:
            return cached

    sources, failures = [], []
    red_flags: list = []
    try:
        financials_envelope = build_financials(db, symbol)
        sources.extend(financials_envelope["sources"])
        failures.extend(financials_envelope["partial_failures"])
        red_flags = financials_envelope["data"]["red_flags"]
    except FundamentalsNotFound as e:
        failures.append(f"财务数据获取失败: {e}")

    valuation_envelope = build_valuation(db, symbol)
    sources.extend(valuation_envelope["sources"])
    failures.extend(valuation_envelope["partial_failures"])

    snapshot: dict = {}
    try:
        snapshot = market_service.get_snapshot(symbol)
    except market_service.MarketDataError as e:
        failures.append(f"行情快照获取失败: {e}")

    filings, _cik_info, filings_sources, filings_failures = _load_filings(db, symbol)
    sources.extend(filings_sources)
    failures.extend(filings_failures)

    risk_items = risk_service.build_risk_items(
        red_flags, valuation_envelope["data"]["historical"], snapshot, filings
    )
    data = {"items": risk_items}
    envelope = _envelope(data, list(dict.fromkeys(sources)), failures)
    cache_service.save_cache(db, symbol, "risks", data, list(dict.fromkeys(sources)), failures)
    return envelope


# --------------------------------------------------------------------- ai_analysis ----

def build_ai_analysis(db: Session, symbol: str) -> dict:
    context = {
        "financials": build_financials(db, symbol)["data"],
        "valuation": build_valuation(db, symbol)["data"],
        "earnings": build_earnings(db, symbol)["data"],
        "risks": build_risks(db, symbol)["data"],
    }
    try:
        overview = build_overview(db, symbol)["data"]
        context["overview"] = overview
    except FundamentalsNotFound:
        pass

    try:
        filings = build_filings(db, symbol)["data"]
        # 8-K 太多了，只把最近的和"重大"的给模型，控制 prompt 大小
        recent_filings = [f for f in filings["filings"] if f["category"] in ("8-K", "10-Q", "10-K")][:15]
        context["recent_filings"] = recent_filings
    except Exception:
        pass

    result = ai_analysis_service.generate_ai_analysis(db, symbol, context)
    envelope = _envelope(result, ["Gemini", "SEC EDGAR", "Yahoo Finance"], [])
    cache_service.save_cache(db, symbol, "ai_analysis", result, ["Gemini", "SEC EDGAR", "Yahoo Finance"], [])
    return envelope


def get_cached_ai_analysis(db: Session, symbol: str) -> Optional[dict]:
    return cache_service.get_cached(db, symbol, "ai_analysis")


# ------------------------------------------------------------------------ search ----

def search(db: Session, query: str, limit: int = 10) -> list[dict]:
    return sec_client.search_companies(db, query, limit)


def refresh(db: Session, symbol: str, dataset: Optional[str] = None) -> None:
    cache_service.invalidate(db, symbol, dataset)
