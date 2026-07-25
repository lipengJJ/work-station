from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import Task
from app.schemas.home import DataSourceStatus, HomeResponse, HomeSummary
from app.schemas.task import TaskOut

router = APIRouter(prefix="/api/home", tags=["home"])


@router.get("", response_model=HomeResponse)
def get_home(db: Session = Depends(get_db), _=Depends(get_current_user)):
    modules = [row[0] for row in db.query(Task.module).distinct().all()]
    data_sources = []
    for module in modules:
        latest = db.query(Task).filter(Task.module == module).order_by(Task.created_at.desc()).first()
        total = db.query(func.count(Task.id)).filter(Task.module == module).scalar() or 0
        data_sources.append(
            DataSourceStatus(
                module=module,
                last_run_at=latest.created_at if latest else None,
                last_status=latest.status if latest else None,
                total_tasks=total,
            )
        )

    recent_tasks = db.query(Task).order_by(Task.created_at.desc()).limit(5).all()

    total_tasks = db.query(func.count(Task.id)).scalar() or 0
    success_count = db.query(func.count(Task.id)).filter(Task.status == "success").scalar() or 0
    failed_count = db.query(func.count(Task.id)).filter(Task.status == "failed").scalar() or 0
    running_count = db.query(func.count(Task.id)).filter(Task.status.in_(("pending", "running"))).scalar() or 0

    return HomeResponse(
        data_sources=data_sources,
        recent_tasks=[TaskOut.model_validate(t) for t in recent_tasks],
        summary=HomeSummary(
            total_tasks=total_tasks,
            success_count=success_count,
            failed_count=failed_count,
            running_count=running_count,
        ),
    )
