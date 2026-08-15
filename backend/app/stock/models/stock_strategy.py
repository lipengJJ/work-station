from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StockStrategy(Base):
    """
    策略驱动的 AI 个股分析：用户可复用的策略模板。

    is_preset=True 的是内置预设策略（价值投资/趋势交易/稳健防守），由 seed 逻辑在
    首次访问策略列表时幂等插入；预设策略允许改名称和描述，但不允许改 rules（保持
    内置策略的原始框架）。rules_json 是结构化策略规则（关注因子、风险偏好、买入
    倾向等），渲染进 AI Prompt，同一个 rules 结构也驱动"策略会影响哪些输出小节"。
    """

    __tablename__ = "stock_strategies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="")
    is_preset: Mapped[bool] = mapped_column(Boolean, default=False)
    rules_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
