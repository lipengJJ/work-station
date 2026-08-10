"""
股票域通用的"按 symbol+dataset 查缓存，没有或过期了才真的发外部请求"读写层，落在
FundamentalsCache 表（表名是历史遗留，实际不止基本面在用——K线、历史股价这些同样走
这一套，因为已有的 (symbol, dataset) -> JSON 缓存机制本来就是通用的，没必要另开一张表）。

这里其实是两种不同性质的数据，对应两套读写方式：

1. 整份数据一起过期的（financials/valuation/earnings/... 这些 fundamentals dataset，
   还有行情快照类）：过期之前直接返回旧的，过期之后整份重新拉、整份覆盖。用 get_cached /
   save_cache，TTL 在 _TTL_SECONDS 里配置。财务/SEC 类数据变化很慢给到 12 小时，行情
   快照类给到 60 秒。

2. K线、历史股价这类"时间序列"数据：已经收盘的历史K线/历史交易日不会再变，只有最近这
   一小段（当前还在走的这根K线）会变——如果还是整份过期整份重拉，等于每次都把已经确定
   不变的大部分历史也白白重新请求一遍。这类用 get_or_refresh_time_series：完全没缓存过
   就整段拉一次；已有缓存但过了刷新间隔，只拉最近一小段，按时间字段把新的合并进历史里
   （新覆盖旧，同时也能捡漏 Yahoo 偶尔对最近几根做的数据修正），不用重新请求整个历史窗口。
"""
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.stock.models import FundamentalsCache

_TTL_SECONDS: dict[str, int] = {
    "overview": 60,
    "financials": 12 * 3600,
    "valuation": 12 * 3600,
    "earnings": 6 * 3600,
    "filings": 6 * 3600,
    "institutions": 24 * 3600,
    "insiders": 6 * 3600,
    "risks": 6 * 3600,
    "ai_analysis": 24 * 3600,
    "market_indices": 60,
    "market_index_history_1M": 30 * 60,
    "market_index_history_3M": 30 * 60,
    "market_index_history_6M": 3600,
    "market_index_history_YTD": 3600,
    "market_index_history_1Y": 3600,
    "mag7_earnings": 6 * 3600,
}


def _get_row(db: Session, symbol: str, dataset: str) -> Optional[FundamentalsCache]:
    return db.query(FundamentalsCache).filter(FundamentalsCache.symbol == symbol, FundamentalsCache.dataset == dataset).first()


def get_cached(db: Session, symbol: str, dataset: str) -> Optional[dict]:
    row = _get_row(db, symbol, dataset)
    if not row:
        return None
    ttl = _TTL_SECONDS.get(dataset, 3600)
    fetched_at = row.fetched_at if row.fetched_at.tzinfo else row.fetched_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - fetched_at > timedelta(seconds=ttl):
        return None
    return {
        "data": json.loads(row.payload_json),
        "sources": json.loads(row.sources_json),
        "partial_failures": json.loads(row.partial_failures_json),
        "fetched_at": row.fetched_at.isoformat(),
        "from_cache": True,
    }


def save_cache(db: Session, symbol: str, dataset: str, data: dict, sources: list[str], partial_failures: Optional[list[str]] = None) -> None:
    row = _get_row(db, symbol, dataset)
    payload_json = json.dumps(data, ensure_ascii=False, default=str)
    sources_json = json.dumps(sources, ensure_ascii=False)
    partial_failures_json = json.dumps(partial_failures or [], ensure_ascii=False)
    if row:
        row.payload_json = payload_json
        row.sources_json = sources_json
        row.partial_failures_json = partial_failures_json
        row.fetched_at = datetime.now(timezone.utc)
    else:
        db.add(
            FundamentalsCache(
                symbol=symbol, dataset=dataset, payload_json=payload_json,
                sources_json=sources_json, partial_failures_json=partial_failures_json,
            )
        )
    db.commit()


def invalidate(db: Session, symbol: str, dataset: Optional[str] = None) -> None:
    query = db.query(FundamentalsCache).filter(FundamentalsCache.symbol == symbol)
    if dataset:
        query = query.filter(FundamentalsCache.dataset == dataset)
    query.delete()
    db.commit()


def get_or_refresh_time_series(
    db: Session,
    symbol: str,
    dataset: str,
    *,
    time_key: str,
    refresh_ttl_seconds: int,
    fetch_full: Callable[[], list[dict]],
    fetch_recent: Callable[[], list[dict]],
    postprocess: Optional[Callable[[list[dict]], list[dict]]] = None,
) -> list[dict]:
    """
    给 K线、历史股价这类"越早的数据越不会变，只有最近一小段会变"的时间序列用。

    - 完全没缓存过（冷启动）：调 fetch_full 拉一次足够长的完整历史，存起来。
    - 已有缓存、且距上次刷新还在 refresh_ttl_seconds 内：直接返回缓存，不发任何请求。
    - 已有缓存但过了刷新间隔：只调 fetch_recent 拉最近一小段（足够覆盖新收盘的几根 +
      当前还在走的这一根），按 time_key 字段和历史部分合并——recent 里的每一条都覆盖
      history 里 time_key 相同的旧值，不管是补上新收盘的、刷新当前这根的最新值，还是
      Yahoo 偶尔对最近几根做的数据修正，统一按"更新的覆盖旧的"处理，不用特殊区分这几种
      情况，也不用把整段历史重新拉一遍。

    postprocess（可选）：合并后的完整序列如果还需要算均线/MACD/RSI 这类衍生指标，必须在
    这里统一对合并后的完整序列算一遍，不能指望 fetch_recent 单独对那一小段自己算——数据
    不够长，rolling/ewm 这类需要历史打底的指标会算出 NaN 或者不准。fetch_full/fetch_recent
    只管返回原始数据，postprocess 负责在合并之后的完整序列上补上这些字段。
    """
    row = _get_row(db, symbol, dataset)
    if row is None:
        items = fetch_full()
        if postprocess:
            items = postprocess(items)
        save_cache(db, symbol, dataset, {"items": items}, sources=["Yahoo Finance"])
        return items

    fetched_at = row.fetched_at if row.fetched_at.tzinfo else row.fetched_at.replace(tzinfo=timezone.utc)
    cached_items = json.loads(row.payload_json)["items"]
    if datetime.now(timezone.utc) - fetched_at <= timedelta(seconds=refresh_ttl_seconds):
        return cached_items

    recent_items = fetch_recent()
    merged = _merge_series_by_key(cached_items, recent_items, time_key)
    if postprocess:
        merged = postprocess(merged)
    save_cache(db, symbol, dataset, {"items": merged}, sources=["Yahoo Finance"])
    return merged


def _merge_series_by_key(history: list[dict], recent: list[dict], key: str) -> list[dict]:
    by_key = {item[key]: item for item in history}
    by_key.update({item[key]: item for item in recent})
    return sorted(by_key.values(), key=lambda item: item[key])
