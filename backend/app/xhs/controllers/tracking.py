from __future__ import annotations

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
