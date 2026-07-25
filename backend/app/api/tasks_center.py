from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import Task
from app.schemas.task import TaskCenterResponse, TaskOut

router = APIRouter(prefix="/api/tasks-center", tags=["tasks-center"])


@router.get("", response_model=TaskCenterResponse)
def list_tasks(db: Session = Depends(get_db), _=Depends(get_current_user)):
    tasks = db.query(Task).order_by(Task.created_at.desc()).all()
    running = [t for t in tasks if t.status in ("pending", "running")]
    completed = [t for t in tasks if t.status == "success"]
    failed = [t for t in tasks if t.status == "failed"]
    return TaskCenterResponse(
        running=[TaskOut.model_validate(t) for t in running],
        completed=[TaskOut.model_validate(t) for t in completed],
        failed=[TaskOut.model_validate(t) for t in failed],
    )
