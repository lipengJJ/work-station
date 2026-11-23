"""热点榜单：/api/hotlist/*（全部需要登录）。

- GET  /items              分页列表（来源 / 源类型 / 日期筛选 / 关键词 + 权重/榜位/时间排序）
- GET  /items/{id}         详情 + 榜位时间线
- GET  /items/{id}/fulltext 全文（缓存优先，没有就现抓；跟主题报告 L2 共用同一份缓存）
- GET  /embedding-status   文章语义向量索引进度（含手动补算是否在跑）
- POST /embedding-backfill 手动触发存量语义索引补算（后台线程，进程内锁防重复）
- POST /crawl              手动触发（10 分钟限频 + daemon 线程异步执行，逻辑照搬旧
                            ai_trending controllers/trending.py::manual_refresh）
"""
from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlalchemy.orm import Session

from app.common.utils.rate_limiter import RateLimiter
from app.core.database import SessionLocal, get_db
from app.core.deps import get_current_user
from app.hotlist.schemas.item import (
    EmbeddingStatusOut,
    GroupSummaryOut,
    ItemDetailOut,
    ItemFulltextOut,
    ItemPage,
)
from app.hotlist.services import (
    crawl_service,
    embedding_service,
    fulltext_service,
    group_summary_service,
    item_service,
    scheduler_jobs,
    source_service,
)

router = APIRouter(prefix="/api/hotlist", tags=["hotlist"])

# 手动刷新限频：10 分钟 1 次（单进程部署成立；见 common/utils/rate_limiter.py）
_refresh_limiter = RateLimiter(cooldown_seconds=600)


@router.get("/items")
def list_items(
    q: str = Query("", max_length=100, description="关键词：匹配标题 / 摘要 / 来源名称"),
    group: str = Query("", max_length=64, description="分组过滤：空=全部；'ungrouped'=未分组；其余为分组 id"),
    stat_date: str = Query("", max_length=10),
    sort: str = Query("weight", max_length=8),
    hit_only: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> ItemPage:
    try:
        return item_service.list_items(
            db,
            q=q,
            group=group,
            stat_date=stat_date,
            sort=sort,
            hit_only=hit_only,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/items/summary")
def generate_group_summary(
    group: str = Query("", max_length=64, description="分组过滤：空=全部；'ungrouped'=未分组；其余为分组 id"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> GroupSummaryOut:
    """一键生成当前分组的 AI 总结（同步，非流式）：点一下等几秒直接拿结果。

    路由必须排在 GET /items/{item_id} 之前——否则 "/items/summary" 会被
    {item_id} 这个路径参数先匹配掉（"summary" 当字符串解析成 int 直接 422）。
    """
    try:
        return group_summary_service.generate_summary(db, group)
    except group_summary_service.GroupSummaryError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/items/summary")
def get_group_summary(
    group: str = Query("", max_length=64),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> GroupSummaryOut | None:
    """取该分组最近一条成功的总结（刷新页面/切分组后回看上次结果用）。同上，必须排在
    GET /items/{item_id} 之前。"""
    return group_summary_service.get_latest_summary(db, group)


@router.get("/items/{item_id}")
def get_item_detail(
    item_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> ItemDetailOut:
    detail = item_service.get_item_detail(db, item_id)
    if detail is None:
        raise HTTPException(404, "条目不存在")
    return detail


@router.get("/items/{item_id}/fulltext")
def get_item_fulltext(
    item_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> ItemFulltextOut:
    """按需查全文：先查 `HotItemContent` 缓存，没有就现抓一次（跟主题报告 L2
    走的是同一个 `fulltext_service.fetch_fulltext`，同一份缓存）。抓取失败/被
    robots 挡住时返回 status!=success，content 为空，前端退化展示摘要+原文外链。
    """
    item = item_service.get_item(db, item_id)
    if item is None:
        raise HTTPException(404, "条目不存在")
    row = fulltext_service.fetch_fulltext(item)
    return ItemFulltextOut(
        status=row.status,
        content=row.content or "",
        char_count=row.char_count,
        error=row.error,
        fetched_at=row.fetched_at,
    )


@router.get("/embedding-status")
def get_embedding_status(
    group: str = Query("", max_length=64),
    source_ids: str = Query("", max_length=10_000),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> EmbeddingStatusOut:
    """文章语义向量索引进度：低频补偿任务每 30 分钟跑一批，供榜单页展示当前完成度。"""
    explicit_source_ids = [value for value in source_ids.split(",") if value]
    try:
        scoped_source_ids = (
            explicit_source_ids
            if explicit_source_ids
            else (
                source_service.resolve_group_source_ids(db, group)
                if group
                else None
            )
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    progress = embedding_service.get_embedding_progress(db, scoped_source_ids)
    return EmbeddingStatusOut(
        **progress,
        running=scheduler_jobs.is_manual_backfill_running(),
    )


@router.post("/embedding-backfill")
def trigger_embedding_backfill(
    group: str = Query("", max_length=64),
    source_ids: str = Query("", max_length=10_000),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> dict:
    """手动触发存量语义索引补算：已处理成功的文章会被跳过，只补缺失/失败的。"""
    explicit_source_ids = [value for value in source_ids.split(",") if value]
    try:
        scoped_source_ids = (
            explicit_source_ids
            if explicit_source_ids
            else (
                source_service.resolve_group_source_ids(db, group)
                if group
                else None
            )
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if scoped_source_ids == []:
        raise HTTPException(400, "当前分组没有数据源")
    started = scheduler_jobs.start_manual_embedding_backfill(scoped_source_ids)
    if not started:
        raise HTTPException(429, "已有索引补算任务在执行，请稍后再试")
    scope = "全部数据源" if scoped_source_ids is None else "当前分组"
    return {"triggered": True, "message": f"已触发{scope}语义索引补算，后台执行中"}


@router.post("/crawl")
def manual_crawl(_=Depends(get_current_user)) -> dict:
    """手动触发全量抓取：10 分钟限频，daemon 线程异步执行，立即返回。"""
    remaining = _refresh_limiter.check_and_mark()
    if remaining > 0:
        raise HTTPException(429, f"刷新过于频繁，请 {int(remaining) + 1} 秒后重试")

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
