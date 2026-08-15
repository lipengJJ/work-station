"""AI 开发热点聚合控制器：/api/ai-trending/*（全部需要登录）。

只做参数校验与编排，业务逻辑在 services 层：
- GET  /items   分页列表（来源/类型筛选 + 热度/时间排序）
- GET  /sources 来源健康状态
- POST /refresh 手动刷新（10 分钟内存限频 + daemon 线程异步执行）
"""
from __future__ import annotations

import threading
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.ai_trending.models import AiTrendingItem, AiTrendingSourceStatus
from app.ai_trending.schemas.trending import (
    RefreshOut,
    SourceStatusOut,
    TrendingItemOut,
    TrendingItemPage,
)
from app.ai_trending.services.collector import collector
from app.ai_trending.services.sources import registry  # noqa: F401  确保源已注册
from app.core.database import get_db
from app.core.deps import get_current_user

router = APIRouter(prefix="/api/ai-trending", tags=["ai-trending"])

# 合法来源：'' 表示全部；'hf' 是别名，等价 IN(hf_models, hf_papers)
VALID_SOURCES = {"", "hn", "github", "arxiv", "hf_models", "hf_papers", "hf", "infoq", "kr36"}
HF_ALIAS_SOURCES = ("hf_models", "hf_papers")
VALID_CATEGORIES = {"", "news", "project", "paper", "model"}
VALID_SORTS = {"heat", "time"}

# 手动刷新限频：进程内内存锁 + 时间戳（10 分钟 1 次；单进程部署成立）
_REFRESH_LOCK = threading.Lock()
_last_manual_refresh: float | None = None
REFRESH_COOLDOWN_SECONDS = 600


def _ensure_status_rows(db: Session) -> None:
    """确保所有已注册源都有健康状态行（首抓前 /sources 也能返回完整来源列表）。"""
    changed = False
    for source in registry.list():
        if db.get(AiTrendingSourceStatus, source.source_id) is None:
            db.add(
                AiTrendingSourceStatus(
                    source_id=source.source_id,
                    source_name=source.source_name,
                    category_type=source.category_type,
                )
            )
            changed = True
    if changed:
        db.commit()


# ------------------------------------------------------------------ 列表 ----
@router.get("/items")
def list_items(
    source: str = Query("", max_length=32),
    category: str = Query("", max_length=16),
    sort: str = Query("heat", max_length=8),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    if source not in VALID_SOURCES:
        raise HTTPException(400, f"未知来源: {source}（可选：hn/github/arxiv/hf_models/hf_papers/hf/infoq/kr36）")
    if category not in VALID_CATEGORIES:
        raise HTTPException(400, f"未知类型: {category}（可选：news/project/paper/model）")
    if sort not in VALID_SORTS:
        raise HTTPException(400, f"未知排序: {sort}（可选：heat/time）")

    q = db.query(AiTrendingItem)
    if source:
        if source == "hf":
            q = q.filter(AiTrendingItem.source.in_(HF_ALIAS_SOURCES))
        else:
            q = q.filter(AiTrendingItem.source == source)
    if category:
        q = q.filter(AiTrendingItem.category == category)

    if sort == "time":
        q = q.order_by(AiTrendingItem.published_at.desc(), AiTrendingItem.id.desc())
    else:
        q = q.order_by(AiTrendingItem.heat_score.desc(), AiTrendingItem.id.desc())

    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    items = [TrendingItemOut.model_validate(row) for row in rows]
    return TrendingItemPage(items=items, total=total, page=page, page_size=page_size)


# ------------------------------------------------------------------ 来源 ----
@router.get("/sources")
def list_sources(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    _ensure_status_rows(db)
    rows = (
        db.query(AiTrendingSourceStatus)
        .order_by(AiTrendingSourceStatus.source_id.asc())
        .all()
    )
    return [SourceStatusOut.model_validate(row) for row in rows]


# ------------------------------------------------------------------ 刷新 ----
@router.post("/refresh")
def manual_refresh(_=Depends(get_current_user)) -> RefreshOut:
    """手动触发全量抓取：10 分钟限频，daemon 线程异步执行，立即返回。"""
    global _last_manual_refresh
    now = time.time()
    with _REFRESH_LOCK:
        if _last_manual_refresh is not None:
            remaining = REFRESH_COOLDOWN_SECONDS - (now - _last_manual_refresh)
            if remaining > 0:
                raise HTTPException(
                    429, f"刷新过于频繁，请 {int(remaining) + 1} 秒后重试"
                )
        _last_manual_refresh = now

    def _worker() -> None:
        try:
            collector.run_all()
        except Exception:  # noqa: BLE001  后台线程兜底
            from loguru import logger

            logger.exception("手动刷新 ai_trending 失败")

    threading.Thread(target=_worker, daemon=True).start()
    return RefreshOut(triggered=True, message="已触发全量抓取，约 10-30 秒后完成")
