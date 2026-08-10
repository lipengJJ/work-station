"""
分析报告：把某条成功的 XhsNoteAnalysis 问答"保存"为一份持久化报告。不引用当时项目的笔记
关联表（那张表会随用户增删笔记变化），而是把生成时用到的笔记详情原样快照进
XhsAnalysisReport.source_notes_json，报告内容和证据不随之后的项目笔记增删、原分析记录
删除而失真。
"""
from __future__ import annotations

import json
from typing import Optional

from sqlalchemy.orm import Session

from app.xhs.models import XhsAnalysisProject, XhsAnalysisReport
from app.xhs.services import analysis_project, note_analysis

_NOTE_SNAPSHOT_KEYS = [
    "note_id", "note_url", "note_type", "nickname", "avatar", "title", "desc",
    "liked_count", "collected_count", "comment_count", "video_cover", "image_list",
    "upload_time",
]


class ReportError(Exception):
    """保存报告时的业务校验失败（分析未成功/笔记不在项目里），控制器转成 400。"""


def _snapshot_note(note: dict) -> dict:
    return {k: note.get(k) for k in _NOTE_SNAPSHOT_KEYS}


def save_report(db: Session, project_id: int, analysis_id: int, title: str, note_ids: list[str]) -> dict:
    analysis = note_analysis.get_analysis(db, project_id, analysis_id)
    if not analysis:
        raise ReportError("分析记录不存在")
    if analysis.status != "success" or not analysis.result:
        raise ReportError("只有分析完成的记录才能保存为报告")

    snapshots = _snapshot_current_notes(db, project_id, note_ids)
    if not snapshots:
        raise ReportError("选中的笔记已不在项目里，无法生成证据快照")

    report = XhsAnalysisReport(
        project_id=project_id,
        analysis_id=analysis_id,
        title=title,
        question=analysis.question,
        result=analysis.result,
        template=analysis.template,
        model=analysis.model,
        source_note_ids_json=json.dumps([n["note_id"] for n in snapshots], ensure_ascii=False),
        source_notes_json=json.dumps(snapshots, ensure_ascii=False),
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return _serialize_list_item(db, report)


def _resolve_selected_analyses(db: Session, project_id: int, analysis_ids: list[int]) -> list:
    """按调用方指定的 analysis_ids 取出成功的分析记录，按时间正序排好——多轮对话不是每轮
    都要写进报告，让调用方（前端弹窗里勾选）明确指定要包含哪几轮，而不是默认全选全项目。"""
    id_set = set(analysis_ids)
    analyses = [
        a for a in note_analysis.list_analyses(db, project_id)
        if a.id in id_set and a.status == "success" and a.result
    ]
    analyses.sort(key=lambda a: (a.created_at, a.id))  # list_analyses 是倒序，这里正序拼成一篇文档
    return analyses


def _snapshot_current_notes(db: Session, project_id: int, note_ids: list[str]) -> list[dict]:
    notes_by_id = {n.get("note_id"): n for n in analysis_project.list_project_notes(db, project_id)}
    return [_snapshot_note(notes_by_id[nid]) for nid in note_ids if nid in notes_by_id]


def save_combined_report(
    db: Session, project_id: int, title: str, note_ids: list[str], analysis_ids: list[int]
) -> dict:
    """
    把项目里选中的几轮问答整理成一篇报告——对应"整理为报告"入口，区别于单条问答旁边的
    "保存为报告"。analysis_id 留空（XhsAnalysisReport.analysis_id 本来就是 nullable），
    因为这不对应单一一条 XhsNoteAnalysis 记录。证据快照口径和 save_report 一致：编号顺序
    沿用调用方传入的 note_ids（前端固定传项目当前笔记顺序，和正文里"引用笔记：[N]"一致）。
    """
    analyses = _resolve_selected_analyses(db, project_id, analysis_ids)
    if not analyses:
        raise ReportError("选中的分析记录都不可用，无法整理成报告")

    sections = [f"## {a.question}\n\n{a.result}" for a in analyses]
    combined_result = "\n\n---\n\n".join(sections)

    snapshots = _snapshot_current_notes(db, project_id, note_ids)
    if not snapshots:
        raise ReportError("选中的笔记已不在项目里，无法生成证据快照")

    report = XhsAnalysisReport(
        project_id=project_id,
        analysis_id=None,
        title=title,
        question=f"汇总本项目 {len(analyses)} 轮分析问答",
        result=combined_result,
        template=analyses[-1].template,
        model=analyses[-1].model,
        source_note_ids_json=json.dumps([n["note_id"] for n in snapshots], ensure_ascii=False),
        source_notes_json=json.dumps(snapshots, ensure_ascii=False),
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return _serialize_list_item(db, report)


def append_to_report(db: Session, report_id: int, analysis_ids: list[int], note_ids: list[str]) -> dict:
    """
    把项目里选中的几轮问答追加到一份已有报告后面，而不是新建一份。证据快照直接用调用时刻
    项目的当前笔记顺序整份重新生成（而不是去合并新旧两份笔记列表）——这份报告原本的证据
    快照本来就是按"当时项目笔记顺序"生成的，两次生成用的是同一套约定，正常情况下（项目
    笔记没被增删/重新排序）重新生成出来的顺序和原来完全一致，旧内容里的引用编号不会跑偏；
    如果项目笔记确实变过，旧引用编号本来就只是近似值（报告详情页脚注已经说明这一点），
    不追加额外的合并逻辑去处理这种边缘情况。
    """
    report = db.get(XhsAnalysisReport, report_id)
    if not report:
        raise ReportError("报告不存在")

    analyses = _resolve_selected_analyses(db, report.project_id, analysis_ids)
    if not analyses:
        raise ReportError("选中的分析记录都不可用，无法追加")

    new_sections = [f"## {a.question}\n\n{a.result}" for a in analyses]
    report.result = f"{report.result}\n\n---\n\n" + "\n\n---\n\n".join(new_sections)

    snapshots = _snapshot_current_notes(db, report.project_id, note_ids)
    if snapshots:
        report.source_note_ids_json = json.dumps([n["note_id"] for n in snapshots], ensure_ascii=False)
        report.source_notes_json = json.dumps(snapshots, ensure_ascii=False)

    db.commit()
    db.refresh(report)
    return _serialize_list_item(db, report)


def _serialize_list_item(db: Session, report: XhsAnalysisReport) -> dict:
    project = db.get(XhsAnalysisProject, report.project_id)
    source_note_ids = json.loads(report.source_note_ids_json or "[]")
    return {
        "id": report.id,
        "title": report.title,
        "summary": (report.result or "")[:120],
        "template": report.template,
        "project_id": report.project_id,
        "project_name": project.name if project else "（项目已删除）",
        "source_count": len(source_note_ids),
        "status": "已生成",
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }


def list_reports(
    db: Session,
    query: Optional[str] = None,
    project_id: Optional[int] = None,
    template: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    sort: str = "created_desc",
) -> dict:
    q = db.query(XhsAnalysisReport)
    if project_id is not None:
        q = q.filter(XhsAnalysisReport.project_id == project_id)
    if template:
        q = q.filter(XhsAnalysisReport.template == template)
    if query:
        like = f"%{query.strip()}%"
        q = q.filter(XhsAnalysisReport.title.ilike(like))

    q = q.order_by(
        XhsAnalysisReport.created_at.asc() if sort == "created_asc" else XhsAnalysisReport.created_at.desc()
    )
    total = q.count()
    start = (page - 1) * page_size
    rows = q.offset(start).limit(page_size).all()
    return {
        "items": [_serialize_list_item(db, r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_report(db: Session, report_id: int) -> Optional[dict]:
    report = db.get(XhsAnalysisReport, report_id)
    if not report:
        return None
    project = db.get(XhsAnalysisProject, report.project_id)
    return {
        "id": report.id,
        "title": report.title,
        "question": report.question,
        "result": report.result,
        "template": report.template,
        "model": report.model,
        "project_id": report.project_id,
        "project_name": project.name if project else "（项目已删除）",
        "source_note_ids": json.loads(report.source_note_ids_json or "[]"),
        "source_notes": json.loads(report.source_notes_json or "[]"),
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }


def delete_report(db: Session, report_id: int) -> bool:
    report = db.get(XhsAnalysisReport, report_id)
    if not report:
        return False
    db.delete(report)
    db.commit()
    return True


def delete_reports_for_project(db: Session, project_id: int) -> None:
    db.query(XhsAnalysisReport).filter(XhsAnalysisReport.project_id == project_id).delete()
