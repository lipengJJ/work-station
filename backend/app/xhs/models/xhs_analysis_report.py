from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class XhsAnalysisReport(Base):
    """
    从一条成功的 XhsNoteAnalysis 问答"保存为报告"时创建的快照记录。刻意不引用
    XhsAnalysisProjectNote（那张表记录的是项目当前的笔记集合，会随用户增删变化），
    而是把生成时用到的笔记详情原样快照进 source_notes_json——报告一旦生成，
    后续项目笔记的增删、原分析记录的删除都不应该影响已保存报告的内容和证据。
    source_note_ids_json 保持和 prompt 里引用编号一致的顺序（build_prompt 里
    "引用笔记：[序号]" 的序号就是这个列表的下标+1），前端点正文里的 [N] 才能定位到
    source_notes_json[N-1]。
    """

    __tablename__ = "xhs_analysis_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("xhs_analysis_projects.id"), index=True)
    analysis_id: Mapped[int | None] = mapped_column(ForeignKey("xhs_note_analyses.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    question: Mapped[str] = mapped_column(Text)
    result: Mapped[str] = mapped_column(Text)
    template: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str] = mapped_column(String(64))
    source_note_ids_json: Mapped[str] = mapped_column(Text)
    source_notes_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
