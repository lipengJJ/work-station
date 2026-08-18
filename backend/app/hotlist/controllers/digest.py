"""热点摘要：/api/hotlist/digest（需要登录）。

GET /api/hotlist/digest?mode=daily|incremental|current&stat_date=YYYY-MM-DD&source_ids=a,b
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
from app.hotlist.services import digest_service

router = APIRouter(prefix="/api/hotlist", tags=["hotlist"])

VALID_MODES = {"daily", "incremental", "current"}


@router.get("/digest")
def get_digest(
    mode: str = Query("daily"),
    stat_date: str = Query("", max_length=10),
    source_ids: str = Query("", description="逗号分隔的源 id 列表，空 = 全部源"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> DigestOut:
    if mode not in VALID_MODES:
        raise HTTPException(400, f"未知模式: {mode}（可选：daily/incremental/current）")
    date_str = stat_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ids = [s.strip() for s in source_ids.split(",") if s.strip()] if source_ids else []
    result = digest_service.build_digest(db, mode, date_str, ids or None)
    return DigestOut.model_validate(result)
