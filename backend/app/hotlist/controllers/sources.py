"""源管理：/api/hotlist/sources/*（全部需要登录）。

只做参数校验与编排，业务逻辑在 source_service；更新/新建/删除后同步重调度对应 cron job，
不用重启进程就能生效（cron_expr 入库就是为了这个）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.hotlist.schemas.source import SourceCreateIn, SourceIn, SourceOut
from app.hotlist.services import scheduler_jobs, source_service

router = APIRouter(prefix="/api/hotlist/sources", tags=["hotlist"])


@router.get("")
def list_sources(db: Session = Depends(get_db), _=Depends(get_current_user)) -> list[SourceOut]:
    return [SourceOut.model_validate(row) for row in source_service.list_sources(db)]


@router.put("/{source_id}")
def update_source(
    source_id: str,
    payload: SourceIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> SourceOut:
    try:
        source = source_service.update_source(db, source_id, **payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    scheduler_jobs.register_job(source)
    return SourceOut.model_validate(source)


@router.post("")
def create_source(
    payload: SourceCreateIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> SourceOut:
    try:
        source = source_service.create_source(db, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    scheduler_jobs.register_job(source)
    return SourceOut.model_validate(source)


@router.delete("/{source_id}")
def delete_source(
    source_id: str,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> dict:
    scheduler_jobs.unregister_job(source_id)
    source_service.delete_source(db, source_id)
    return {"ok": True}
