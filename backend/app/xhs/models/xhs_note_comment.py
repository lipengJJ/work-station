from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class XhsNoteComment(Base):
    """
    笔记评论表：评论的"写穿层"（参考 MediaCrawler 的评论落库设计）。

    采集任务边爬评论边批量 upsert 到这里（comment_store.save_comment_batch），
    同时保留 XhsTaskExtra.comments_json（现有 Excel 导出/预览逻辑继续用 JSON），
    行为零变化。收益：崩溃续采不丢已爬评论、可按 note_id 查询、删除笔记时联动删除。

    comment_id 是小红书的评论唯一 ID；parent_comment_id 为 "" 表示一级评论。
    """

    __tablename__ = "xhs_note_comments"

    comment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    note_id: Mapped[str] = mapped_column(String(64), index=True)
    content: Mapped[str] = mapped_column(Text)
    like_count: Mapped[int | None] = mapped_column(default=0)
    nickname: Mapped[str | None] = mapped_column(String(128), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    home_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_comment_id: Mapped[str] = mapped_column(String(64), default="")
    create_time: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_fetched_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
