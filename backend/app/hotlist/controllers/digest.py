"""热点摘要：/api/hotlist/digest（需要登录）。

GET /api/hotlist/digest?mode=daily|incremental|current
&stat_date=YYYY-MM-DD&source_ids=a,b
三种模式条数关系：incremental <= current <= daily（同一天里，新增是当前榜单的子集，
当前榜单又是当天全部条目的子集）。
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.hotlist.schemas.digest import DigestOut
from app.hotlist.services import digest_service, source_service

router = APIRouter(prefix="/api/hotlist", tags=["hotlist"])

VALID_MODES = {"daily", "incremental", "current"}


@router.get("/digest")
def get_digest(
    mode: str = Query("daily"),
    stat_date: str = Query("", max_length=10),
    group: str = Query("", description="分组过滤：空=全部；'ungrouped'=未分组；其余为分组 id"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> DigestOut:
    if mode not in VALID_MODES:
        raise HTTPException(400, f"未知模式: {mode}（可选：daily/incremental/current）")
    date_str = stat_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        ids = source_service.resolve_group_source_ids(db, group)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    result = digest_service.build_digest(db, mode, date_str, ids)
    return DigestOut.model_validate(result)
