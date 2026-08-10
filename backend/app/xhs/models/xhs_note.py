from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class XhsNote(Base):
    """
    全局笔记缓存：note_id 唯一键，跨采集任务/追踪任务复用同一篇笔记的详情数据，
    不再每次命中都重新调用 spider_note()。字段和 handle_note_info() 的输出一一对应
    （见 app/xhs/services/utils/data_util.py），image_list/tags 是 Python list，
    这里按仓库里 JSON-in-Text 的既有惯例（参考 XhsAnalysisReport.source_notes_json）
    存成 json.dumps 后的字符串，不用 SQLAlchemy 的 JSON 类型。

    last_fetched_at 是 TTL 的锚点：note_cache.py 里超过 N 天允许重新抓取覆盖本行，
    避免点赞/评论数这类会变化的数据被永久冻结。
    """

    __tablename__ = "xhs_notes"

    note_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    note_url: Mapped[str] = mapped_column(Text)
    note_type: Mapped[str] = mapped_column(String(16))
    user_id: Mapped[str] = mapped_column(String(64))
    home_url: Mapped[str] = mapped_column(Text)
    nickname: Mapped[str] = mapped_column(String(128))
    avatar: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(512))
    desc: Mapped[str] = mapped_column(Text)
    liked_count: Mapped[str | None] = mapped_column(String(32), nullable=True)
    collected_count: Mapped[str | None] = mapped_column(String(32), nullable=True)
    comment_count: Mapped[str | None] = mapped_column(String(32), nullable=True)
    share_count: Mapped[str | None] = mapped_column(String(32), nullable=True)
    video_cover: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_addr: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_list_json: Mapped[str] = mapped_column(Text, default="[]")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    upload_time: Mapped[str] = mapped_column(String(32))
    ip_location: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_fetched_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
