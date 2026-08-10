from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Skill(Base):
    """
    Skill 资产的登记表：一个 skill_key 对应一个 Skill 目录，具体内容（指令、模板、文件）
    随版本变化，都记在 SkillVersion 里。current_version_id 不设 ForeignKey 约束——它和
    SkillVersion.skill_id 互相指向对方所在的表，真做成外键会在 create_all 时形成循环依赖，
    这里只是语义上的引用，一致性由 registry_service 维护。
    """

    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(primary_key=True)
    skill_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), default="builtin")  # builtin/upload/local/github
    source_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    risk_level: Mapped[str] = mapped_column(String(16), default="low")  # low/medium/high/blocked
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
