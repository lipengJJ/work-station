"""源管理：/api/hotlist/sources/* + /api/hotlist/source-groups/*（全部需要登录）。

- GET/PUT/POST/DELETE /sources            源列表（可按分组筛）/ 更新 / 新建 / 删除
- POST /sources/batch                     批量：移组（group_id，null=移出）+ 启停（enabled）
- POST /sources/import-opml               批量导入 OPML 到分组（不依赖主题）
- GET/POST /source-groups                 分组列表 / 新建
- PUT/DELETE /source-groups/{group_id}    分组更新 / 删除（内置分组拒删）

只做参数校验与编排，业务逻辑在 source_service；更新/新建/删除后同步重调度对应 cron job，
不用重启进程就能生效（cron_expr 入库就是为了这个）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.hotlist.schemas.source import (
    SourceBatchIn,
    SourceCreateIn,
    SourceImportOpmlIn,
    SourceIn,
    SourceOut,
)
from app.hotlist.schemas.source_group import (
    SourceGroupIn,
    SourceGroupOut,
    SourceGroupUpdateIn,
)
from app.hotlist.services import opml_service, scheduler_jobs, source_service

router = APIRouter(prefix="/api/hotlist/sources", tags=["hotlist"])
group_router = APIRouter(
    prefix="/api/hotlist/source-groups", tags=["hotlist-source-groups"]
)


@router.get("")
def list_sources(
    group_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> list[SourceOut]:
    return [
        SourceOut.model_validate(row)
        for row in source_service.list_sources(db, group_id=group_id)
    ]


@router.put("/{source_id}")
def update_source(
    source_id: str,
    payload: SourceIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> SourceOut:
    try:
        source = source_service.update_source(
            db, source_id, **payload.model_dump(exclude_unset=True)
        )
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
        source = source_service.create_source(
            db, **payload.model_dump(exclude_unset=True)
        )
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


# ------------------------------------------------------------ 批量操作 ----

@router.post("/batch")
def batch_sources(
    payload: SourceBatchIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> dict:
    """批量：先移组（group_id 显式传 null = 移出分组），再启停。两者可同时给、可只给其一。"""
    updates = payload.model_dump(exclude_unset=True)
    source_ids = updates.get("source_ids") or []
    if not source_ids:
        raise HTTPException(400, "source_ids 不能为空")
    try:
        moved = 0
        if "group_id" in updates:
            moved = source_service.batch_move_sources(
                db, source_ids, updates["group_id"]
            )
        enabled_changed = 0
        if "enabled" in updates:
            enabled_changed = source_service.batch_set_enabled(
                db, source_ids, bool(updates["enabled"])
            )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "moved": moved, "enabled_changed": enabled_changed}


@router.post("/import-opml")
def import_opml(
    payload: SourceImportOpmlIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> dict:
    """批量导入 OPML 到分组（content 优先；给了 opml_url 先拉文本）。不依赖主题。"""
    try:
        content = payload.content
        if not (content or "").strip() and payload.opml_url:
            content = opml_service.fetch_opml(payload.opml_url)
        if not (content or "").strip():
            raise ValueError("请提供 OPML 文本或 URL")
        filename = (
            payload.opml_url.rstrip("/").split("/")[-1][:100]
            if payload.opml_url
            else ""
        )
        imported_from = f"opml:{filename}" if filename else "opml:paste"
        result = opml_service.import_opml(
            db,
            content,
            group_id=payload.group_id,
            topic_id=None,
            imported_from=imported_from,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return result.model_dump()


# ------------------------------------------------------------ 分组 ----

@group_router.get("")
def list_groups(
    db: Session = Depends(get_db), _=Depends(get_current_user)
) -> list[SourceGroupOut]:
    out = []
    for group in source_service.list_groups(db):
        item = SourceGroupOut.model_validate(group)
        item.source_count = source_service.source_count_for_group(db, group.id)
        out.append(item)
    return out


@group_router.post("")
def create_group(
    payload: SourceGroupIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> SourceGroupOut:
    try:
        group = source_service.create_group(db, payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return SourceGroupOut.model_validate(group)


@group_router.put("/{group_id}")
def update_group(
    group_id: int,
    payload: SourceGroupUpdateIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> SourceGroupOut:
    try:
        group = source_service.update_group(db, group_id, payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return SourceGroupOut.model_validate(group)


@group_router.delete("/{group_id}")
def delete_group(
    group_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)
) -> dict:
    try:
        source_service.delete_group(db, group_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True}
