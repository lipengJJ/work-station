"""
AI 分析项目：笔记从任意采集任务里挑进来，项目和笔记是多对多关系（XhsAnalysisProjectNote
只存引用，不存笔记内容）。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.xhs.models import XhsAnalysisProject, XhsAnalysisProjectNote, XhsNoteAnalysis
from app.xhs.services import note_cache, tasks


def _note_count(db: Session, project_id: int) -> int:
    return (
        db.query(XhsAnalysisProjectNote)
        .filter(XhsAnalysisProjectNote.project_id == project_id)
        .count()
    )


def _serialize_project(project: XhsAnalysisProject, note_count: int) -> dict:
    return {
        "id": project.id,
        "name": project.name,
        "note_count": note_count,
        "created_at": project.created_at.isoformat() if project.created_at else None,
    }


def list_projects(db: Session) -> list[dict]:
    projects = db.query(XhsAnalysisProject).order_by(XhsAnalysisProject.created_at.desc()).all()
    return [_serialize_project(p, _note_count(db, p.id)) for p in projects]


def get_project(db: Session, project_id: int) -> Optional[XhsAnalysisProject]:
    return db.get(XhsAnalysisProject, project_id)


def create_project(db: Session, name: str) -> dict:
    project = XhsAnalysisProject(name=name)
    db.add(project)
    db.commit()
    db.refresh(project)
    return _serialize_project(project, 0)


def rename_project(db: Session, project_id: int, name: str) -> Optional[dict]:
    project = db.get(XhsAnalysisProject, project_id)
    if not project:
        return None
    project.name = name
    db.commit()
    return _serialize_project(project, _note_count(db, project_id))


def delete_project(db: Session, project_id: int) -> bool:
    project = db.get(XhsAnalysisProject, project_id)
    if not project:
        return False
    # 函数内 import：report_service 反过来会 import 本模块，模块顶层互相 import 会循环引用
    from app.xhs.services import report_service

    # XhsAnalysisProjectNote / XhsNoteAnalysis / XhsAnalysisReport 没配级联，手动清一遍再删项目本身
    db.query(XhsAnalysisProjectNote).filter(XhsAnalysisProjectNote.project_id == project_id).delete()
    db.query(XhsNoteAnalysis).filter(XhsNoteAnalysis.project_id == project_id).delete()
    report_service.delete_reports_for_project(db, project_id)
    db.delete(project)
    db.commit()
    return True


def list_project_notes(db: Session, project_id: int) -> list[dict]:
    """
    按加入项目的时间顺序读笔记内容。优先查全局笔记缓存（note_cache，按 note_id
    直接命中，不用管这篇笔记当初是哪个采集任务抓的——即使原任务的 result_json 后来
    被清空/删过这篇笔记，只要缓存里还有就能读到，比原来"必须回源 task_id"更健壮）。

    缓存里没有的（比如这张全局表刚上线、项目里还是旧数据）才退回旧路径，从笔记
    所属的采集任务里读，并顺手把读到的笔记回填进全局缓存——不需要一次性迁移脚本，
    项目被访问到的笔记会逐步"迁"进新表。
    """
    refs = (
        db.query(XhsAnalysisProjectNote)
        .filter(XhsAnalysisProjectNote.project_id == project_id)
        .order_by(XhsAnalysisProjectNote.added_at, XhsAnalysisProjectNote.id)
        .all()
    )
    if not refs:
        return []

    notes_by_id = note_cache.get_cached_notes_map(db, [r.note_id for r in refs])

    missing_by_task: dict[int, set[str]] = {}
    for ref in refs:
        if ref.note_id not in notes_by_id:
            missing_by_task.setdefault(ref.task_id, set()).add(ref.note_id)

    for task_id, missing_ids in missing_by_task.items():
        preview = tasks.get_preview(db, task_id) or {"notes": []}
        for n in preview["notes"]:
            note_id = n.get("note_id")
            if note_id in missing_ids:
                notes_by_id[note_id] = n
                note_cache.upsert_note(db, n)

    result = []
    for ref in refs:
        note = notes_by_id.get(ref.note_id)
        if note:
            result.append(note)
    return result


def add_notes(db: Session, project_id: int, task_id: int, note_ids: list[str]) -> int:
    existing = {
        row.note_id
        for row in db.query(XhsAnalysisProjectNote.note_id).filter(
            XhsAnalysisProjectNote.project_id == project_id
        )
    }
    added = 0
    for note_id in note_ids:
        if note_id in existing:
            continue
        db.add(XhsAnalysisProjectNote(project_id=project_id, task_id=task_id, note_id=note_id))
        existing.add(note_id)
        added += 1
    db.commit()
    return added


def remove_note(db: Session, project_id: int, note_id: str) -> bool:
    deleted = (
        db.query(XhsAnalysisProjectNote)
        .filter(XhsAnalysisProjectNote.project_id == project_id, XhsAnalysisProjectNote.note_id == note_id)
        .delete()
    )
    db.commit()
    return deleted > 0
