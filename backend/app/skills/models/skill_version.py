from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SkillVersion(Base):
    """
    Skill 内容的一次不可变快照：storage_path 是相对路径（相对哪个根目录由 skill.source_type
    决定，builtin 相对内置 skills 根目录，第二阶段的 upload 相对受控的 storage/skills 根目录），
    不存绝对路径，避免请求方拼接任意文件系统位置。manifest_json/validation_json 和别的域一样
    用 Text 存 JSON 字符串（参考 XhsAnalysisReport 的 source_notes_json），不用 SQLAlchemy 的
    JSON 类型，跟仓库里已有的 JSON 存储方式保持一致。
    """

    __tablename__ = "skill_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id"), index=True)
    version: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(80))
    manifest_json: Mapped[str] = mapped_column(Text, default="{}")
    validation_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
