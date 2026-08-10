from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class XhsNoteStructured(Base):
    """
    笔记结构化预处理结果（《小红书笔记结构化预处理-技术方案.md》），note_id 主键，
    一篇笔记一行。content_hash 是 title+desc 的摘要，用于幂等——原文没变就不重新
    调 LLM（方案 3.5 节 need_process）。

    status='ok' 时，AI 分析应该读这张表里的精简版 summary/key_points 代替原始笔记
    全文（token 能降 80% 左右）；status 是 'failed'（LLM 调用出错）或
    'skipped_low_content'（规则判定为求助/求攻略类低质内容，压根没调 LLM）时，
    调用方要退回读原始笔记（note_cache），保证没处理过的笔记依然能正常参与分析。
    """

    __tablename__ = "xhs_notes_structured"

    note_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(32), index=True)
    category: Mapped[str | None] = mapped_column(String(16), nullable=True)
    city: Mapped[str | None] = mapped_column(String(64), nullable=True)
    area: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    key_points_json: Mapped[str] = mapped_column(Text, default="[]")
    topic_tags_json: Mapped[str] = mapped_column(Text, default="[]")
    ext_json: Mapped[str] = mapped_column(Text, default="{}")
    raw_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24))  # ok | failed | skipped_low_content
    issues_json: Mapped[str] = mapped_column(Text, default="[]")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
