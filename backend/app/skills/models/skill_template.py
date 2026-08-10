from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SkillTemplate(Base):
    """
    某个 Skill 版本下声明的分析模板（workbench.yaml 里的 templates 列表），描述"这次执行
    需要收集什么输入、用什么默认提示、输出什么结构"，和 Skill 本身"AI 应当如何工作"的
    核心指令是两个概念（设计文档 2.2 节）。没有 workbench.yaml 的通用 Skill 就没有模板行。
    """

    __tablename__ = "skill_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    skill_version_id: Mapped[int] = mapped_column(ForeignKey("skill_versions.id"), index=True)
    template_key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_template_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_schema_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
