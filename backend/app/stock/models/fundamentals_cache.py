from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FundamentalsCache(Base):
    """
    基本面模块的通用缓存表：一支股票的 overview/financials/valuation/earnings/filings/
    institutions/insiders/risks/ai_analysis 各是一个 dataset，(symbol, dataset) 唯一。

    不像自选股行情缓存（WatchlistStock）那样每个字段单独开列——基本面每个 dataset 的
    数据形状差异很大且还在演进，这里统一存 payload_json（TEXT），各 dataset 各自的
    Pydantic schema 负责解释里面的结构，不在数据库层面强约束。sources_json 记录这份数据
    实际来自哪些数据源（SEC EDGAR / yfinance / gemini 等），前端展示"数据来源"用得上。
    """

    __tablename__ = "fundamentals_cache"
    __table_args__ = (UniqueConstraint("symbol", "dataset", name="uq_fundamentals_cache_symbol_dataset"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    dataset: Mapped[str] = mapped_column(String(32), index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    sources_json: Mapped[str] = mapped_column(Text, default="[]")
    partial_failures_json: Mapped[str] = mapped_column(Text, default="[]")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
