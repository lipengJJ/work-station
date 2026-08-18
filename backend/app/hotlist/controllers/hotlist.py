"""热点榜单：/api/hotlist/*（全部需要登录）。

- GET  /items        分页列表（来源 / 源类型 / 日期筛选 + 权重/榜位/时间排序）
- GET  /items/{id}   详情 + 榜位时间线
- POST /crawl        手动触发（10 分钟限频 + daemon 线程异步执行，逻辑照搬旧
                      ai_trending controllers/trending.py::manual_refresh）
"""
from __future__ import annotations

import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.core.deps import get_current_user
from app.hotlist.models import HotItem, HotKeywordRule, HotRankHistory, HotRuleHit, HotSource
from app.hotlist.schemas.item import ItemDetailOut, ItemOut, ItemPage, RankPointOut
from app.hotlist.services import crawl_service

router = APIRouter(prefix="/api/hotlist", tags=["hotlist"])

VALID_SORTS = {"weight", "rank", "time"}

# 手动刷新限频：进程内内存锁 + 时间戳（10 分钟 1 次；单进程部署成立）
_REFRESH_LOCK = threading.Lock()
_last_manual_refresh: float | None = None
REFRESH_COOLDOWN_SECONDS = 600


def _attach_hit_rules(db: Session, items_out: list[ItemOut]) -> None:
    """批量回填每条条目命中的规则显示名（一次 join 查询，避免逐条查询 N+1）。"""
    if not items_out:
        return
    item_ids = [it.id for it in items_out]
    rows = (
        db.query(HotRuleHit.item_id, HotKeywordRule.display_name)
        .join(HotKeywordRule, HotKeywordRule.id == HotRuleHit.rule_id)
        .filter(HotRuleHit.item_id.in_(item_ids))
        .all()
    )
    names_by_item: dict[int, list[str]] = {}
    for item_id, display_name in rows:
        names_by_item.setdefault(item_id, []).append(display_name or "未命名规则")
    for it in items_out:
        it.hit_rules = names_by_item.get(it.id, [])


@router.get("/items")
def list_items(
    source_id: str = Query("", max_length=64),
    source_kind: str = Query("", max_length=16),
    stat_date: str = Query("", max_length=10),
    sort: str = Query("weight", max_length=8),
    hit_only: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> ItemPage:
    if sort not in VALID_SORTS:
        raise HTTPException(400, f"未知排序: {sort}（可选：weight/rank/time）")

    q = db.query(HotItem)
    if source_id:
        q = q.filter(HotItem.source_id == source_id)
    if source_kind:
        source_ids = [
            row[0]
            for row in db.query(HotSource.id).filter(HotSource.source_kind == source_kind).all()
        ]
        q = q.filter(HotItem.source_id.in_(source_ids))
    if stat_date:
        q = q.filter(HotItem.stat_date == stat_date)
    if hit_only:
        hit_item_ids = [row[0] for row in db.query(HotRuleHit.item_id.distinct()).all()]
        q = q.filter(HotItem.id.in_(hit_item_ids))

    if sort == "time":
        q = q.order_by(HotItem.last_crawl_time.desc(), HotItem.id.desc())
    elif sort == "rank":
        q = q.order_by(HotItem.rank.asc(), HotItem.weight.desc())
    else:
        q = q.order_by(HotItem.weight.desc(), HotItem.id.desc())

    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    items_out = [ItemOut.model_validate(row) for row in rows]
    _attach_hit_rules(db, items_out)
    return ItemPage(
        items=items_out,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/items/{item_id}")
def get_item_detail(
    item_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> ItemDetailOut:
    item = db.get(HotItem, item_id)
    if item is None:
        raise HTTPException(404, "条目不存在")
    history = (
        db.query(HotRankHistory)
        .filter(HotRankHistory.item_id == item_id)
        .order_by(HotRankHistory.crawl_time.asc())
        .all()
    )
    item_out = ItemOut.model_validate(item)
    _attach_hit_rules(db, [item_out])
    return ItemDetailOut(
        item=item_out,
        history=[RankPointOut.model_validate(row) for row in history],
    )


@router.post("/crawl")
def manual_crawl(_=Depends(get_current_user)) -> dict:
    """手动触发全量抓取：10 分钟限频，daemon 线程异步执行，立即返回。"""
    global _last_manual_refresh
    now = time.time()
    with _REFRESH_LOCK:
        if _last_manual_refresh is not None:
            remaining = REFRESH_COOLDOWN_SECONDS - (now - _last_manual_refresh)
            if remaining > 0:
                raise HTTPException(429, f"刷新过于频繁，请 {int(remaining) + 1} 秒后重试")
        _last_manual_refresh = now

    def _worker() -> None:
        db = SessionLocal()
        try:
            crawl_service.run_crawl(db, trigger="manual")
        except Exception:  # noqa: BLE001  后台线程兜底
            logger.exception("手动刷新 hotlist 失败")
        finally:
            db.close()

    threading.Thread(target=_worker, daemon=True).start()
    return {"triggered": True, "message": "已触发全量抓取，约 10-30 秒后完成"}
