from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.database import get_db
from app.xhs.schemas.xhs import TrackingTaskIn
from app.xhs.services import tracking
from app.xhs.services.tasks import enqueue_tracking_scan

router = APIRouter(prefix="/api/xhs", tags=["xhs-tracking"])


@router.get("/tracking-tasks")
def list_tracking_tasks(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return tracking.list_tracking_tasks(db)


@router.post("/tracking-tasks")
def create_tracking_task(body: TrackingTaskIn, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return tracking.create_tracking_task(db, body.model_dump())


@router.get("/tracking-tasks/{tracking_task_id}")
def get_tracking_task(tracking_task_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    task = tracking.get_tracking_task(db, tracking_task_id)
    if not task:
        raise HTTPException(404, "追踪任务不存在")
    return tracking.serialize_task(db, task)


@router.put("/tracking-tasks/{tracking_task_id}")
def update_tracking_task(
    tracking_task_id: int, body: TrackingTaskIn, db: Session = Depends(get_db), _=Depends(get_current_user)
):
    updated = tracking.update_tracking_task(db, tracking_task_id, body.model_dump())
    if not updated:
        raise HTTPException(404, "追踪任务不存在")
    return updated


@router.delete("/tracking-tasks/{tracking_task_id}")
def delete_tracking_task(tracking_task_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    ok = tracking.delete_tracking_task(db, tracking_task_id)
    if not ok:
        raise HTTPException(404, "追踪任务不存在")
    return {"success": True}


@router.post("/tracking-tasks/{tracking_task_id}/ai-try-run")
def ai_try_run_tracking_task(
    tracking_task_id: int,
    body: dict | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """AI 筛选试跑：用当前 Prompt 对最近一次采集的笔记（最多 5 条）试跑，不写库不通知。"""
    from app.xhs.services import ai_filter, tracking as tracking_service

    task = tracking_service.get_tracking_task(db, tracking_task_id)
    if not task:
        raise HTTPException(404, "追踪任务不存在")
    prompt = (body or {}).get("prompt") or task.ai_filter_prompt or ""
    if not prompt.strip():
        raise HTTPException(400, "请先填写筛选 Prompt")

    from app.common.services.zhipu_config import get_zhipu_config

    api_key, model = get_zhipu_config(db)
    if not api_key:
        raise HTTPException(400, "需先在系统设置中配置数据处理模型")

    from app.xhs.models import XhsTrackingHit

    hits = (
        db.query(XhsTrackingHit)
        .filter(
            XhsTrackingHit.tracking_task_id == tracking_task_id,
            XhsTrackingHit.matched.is_(True),
            XhsTrackingHit.note_json.isnot(None),
        )
        .order_by(XhsTrackingHit.created_at.desc())
        .limit(5)
        .all()
    )
    if not hits:
        return {"items": [], "summary": "该任务还没有采集数据，请先运行一次"}

    structured_map = {}
    try:
        from app.xhs.services import note_structurer

        structured_map = note_structurer.get_structured_map(
            db, [h.note_id for h in hits]
        )
    except Exception:
        pass

    results = []
    for h in hits:
        r = ai_filter.filter_one(
            db, h, prompt, api_key, model,
            task_name=task.name, keyword=task.keyword,
            structured=structured_map.get(h.note_id),
        )
        note = {}
        try:
            note = json.loads(h.note_json or "{}")
        except (ValueError, TypeError):
            pass
        results.append({
            "note_id": h.note_id,
            "title": note.get("title") or f"笔记 {h.note_id}",
            "ok": r.get("ok"),
            "is_match": r.get("is_match"),
            "match_reason": r.get("match_reason"),
            "confidence": r.get("confidence"),
            "elapsed": round(r.get("elapsed", 0), 1),
            "error": r.get("error"),
            "raw": r.get("raw"),
        })
    matched = sum(1 for r in results if r.get("ok") and r.get("is_match"))
    return {"items": results, "summary": f"{len(results)} 条中判定符合 {matched} 条"}


@router.post("/tracking-tasks/{tracking_task_id}/run-now")
def run_tracking_task_now(
    tracking_task_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)
):
    task = tracking.get_tracking_task(db, tracking_task_id)
    if not task:
        raise HTTPException(404, "追踪任务不存在")
    enqueue_tracking_scan(tracking_task_id)
    return {"success": True}


@router.get("/tracking-tasks/{tracking_task_id}/hits")
def list_tracking_hits(tracking_task_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    task = tracking.get_tracking_task(db, tracking_task_id)
    if not task:
        raise HTTPException(404, "追踪任务不存在")
    return tracking.list_hits(db, tracking_task_id)


@router.delete("/tracking-tasks/{tracking_task_id}/hits/{hit_id}")
def delete_tracking_hit(
    tracking_task_id: int, hit_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)
):
    ok = tracking.delete_hit(db, tracking_task_id, hit_id)
    if not ok:
        raise HTTPException(404, "命中记录不存在")
    return {"success": True}
