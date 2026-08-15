from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StockStrategyReport(Base):
    """
    策略分析的报告记录：每次「选策略 + 选股票 → AI 分析」的结果快照。

    策略和数据都做快照落库（strategy_snapshot_json / context_snapshot_json），保证
    历史报告任何时候都能解释"当时是用什么策略、基于什么数据得出结论的"，策略后续
    被修改或删除都不影响历史记录的可读性。rating 是分级结论（buy/hold/avoid），
    由流式生成结束后从 markdown 末尾的固定 JSON 块提取（失败降级 glm 结构化兜底）。
    """

    __tablename__ = "stock_strategy_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    strategy_id: Mapped[int] = mapped_column(Integer, ForeignKey("stock_strategies.id"))
    strategy_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    context_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    report_markdown: Mapped[str] = mapped_column(Text, default="")
    rating: Mapped[str] = mapped_column(String(16), default="")
    rating_reason: Mapped[str] = mapped_column(Text, default="")
    key_indicators_json: Mapped[str] = mapped_column(Text, default="[]")
    provider: Mapped[str] = mapped_column(String(32), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(32), default="running")  # running/completed/failed
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
