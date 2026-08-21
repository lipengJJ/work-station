"""条目全文缓存表。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HotItemContent(Base):
    """条目全文缓存（L2 全文放大用），按需抓取、独立成表。

    独立不并进 HotItem 的原因：全文动辄几十 KB，而列表页查询只要标题和摘要——
    并表会让每次列表查询都把大字段拖出来（SQLite 没有列级惰性加载）。
    """

    __tablename__ = "hot_item_contents"

    item_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # strip_html 后的纯文本
    content: Mapped[str] = mapped_column(Text, default="")
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="success")
    """success / failed / skipped(robots 禁止或明显是付费墙)"""
    error: Mapped[str] = mapped_column(Text, default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
