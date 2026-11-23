"""数据源分组 AI 总结表。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HotGroupSummary(Base):
    """一次「数据源分组 AI 总结」的结果。

    非对话：固定指令、一键生成，不像 XhsNoteAnalysis 那样挂一问一答历史，所以没有
    question 字段；每次点击都新插一行（而不是覆盖），前端默认只看最新一条，
    但保留历史方便回看"上次总结说了什么"。

    group_filter 跟榜单页 GET /items?group= 的取值同义：''=全部，'ungrouped'=未分组，
    其余是 hot_source_groups.id 的字符串形式——保证"总结的范围"和"页面上正在看的范围"
    严格一致（见 group_summary_service 直接复用 source_service.resolve_group_source_ids）。
    """

    __tablename__ = "hot_group_summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_filter: Mapped[str] = mapped_column(String(64), default="", index=True)
    status: Mapped[str] = mapped_column(String(16), default="running")
    """running / success / failed"""
    content: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
