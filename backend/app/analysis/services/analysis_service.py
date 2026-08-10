"""
AnalysisRun 的增删查改：controller 负责调用 Skill Runtime + AI Gateway 拼出结果，这里只管
记录的落库和读取，不掺杂 Skill 加载/Prompt 拼装逻辑（那些都在 skill_runtime 里）。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.analysis.models import AnalysisRun
from app.skills.models import Skill, SkillTemplate, SkillVersion


def create_run(
    db: Session,
    *,
    request_id: str,
    user_id: int,
    skill_id: int,
    skill_version_id: int,
    template_id: Optional[int],
    model: str,
    inputs: dict[str, Any],
    system_snapshot: str,
    context_refs: Optional[list[dict[str, Any]]] = None,
) -> AnalysisRun:
    run = AnalysisRun(
        request_id=request_id,
        user_id=user_id,
        skill_id=skill_id,
        skill_version_id=skill_version_id,
        template_id=template_id,
        provider="gemini",
        model=model,
        status="running",
        input_json=json.dumps(inputs, ensure_ascii=False),
        context_refs_json=json.dumps(context_refs or [], ensure_ascii=False),
        system_snapshot=system_snapshot,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def mark_completed(
    db: Session, run_id: int, output_text: str, citations: list[dict], usage: dict
) -> None:
    run = db.get(AnalysisRun, run_id)
    if not run:
        return

    run.status = "completed"
    run.output_text = output_text
    run.citations_json = json.dumps(citations, ensure_ascii=False)
    run.usage_json = json.dumps(usage, ensure_ascii=False)
    run.finished_at = datetime.now(timezone.utc)
    db.commit()


def mark_failed(db: Session, run_id: int, error_message: str) -> None:
    run = db.get(AnalysisRun, run_id)
    if not run:
        return

    run.status = "failed"
    run.error_message = error_message
    run.finished_at = datetime.now(timezone.utc)
    db.commit()


def _serialize(db: Session, run: AnalysisRun, *, include_snapshot: bool = False) -> dict[str, Any]:
    skill = db.get(Skill, run.skill_id)
    version = db.get(SkillVersion, run.skill_version_id)
    template = db.get(SkillTemplate, run.template_id) if run.template_id else None
    data = {
        "id": run.id,
        "request_id": run.request_id,
        "skill_key": skill.skill_key if skill else "",
        "skill_version": version.version if version else "",
        "template_key": template.template_key if template else None,
        "provider": run.provider,
        "model": run.model,
        "status": run.status,
        "input": json.loads(run.input_json),
        "output_text": run.output_text,
        "citations": json.loads(run.citations_json),
        "usage": json.loads(run.usage_json),
        "error_message": run.error_message,
        "created_at": run.created_at,
        "finished_at": run.finished_at,
    }
    if include_snapshot:
        data["system_snapshot"] = run.system_snapshot
    return data


def list_runs(db: Session, skill_key: Optional[str] = None) -> list[dict[str, Any]]:
    q = db.query(AnalysisRun)
    if skill_key:
        skill = db.query(Skill).filter(Skill.skill_key == skill_key).first()
        if not skill:
            return []
        q = q.filter(AnalysisRun.skill_id == skill.id)
    runs = q.order_by(AnalysisRun.created_at.desc()).all()
    return [_serialize(db, r) for r in runs]


def get_run_detail(db: Session, run_id: int) -> Optional[dict[str, Any]]:
    run = db.get(AnalysisRun, run_id)
    if not run:
        return None
    return _serialize(db, run, include_snapshot=True)


def delete_run(db: Session, run_id: int) -> bool:
    run = db.get(AnalysisRun, run_id)
    if not run:
        return False
    db.delete(run)
    db.commit()
    return True
