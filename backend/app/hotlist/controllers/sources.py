"""源管理：/api/hotlist/sources/* + /api/hotlist/source-groups/*（全部需要登录）。

- GET/PUT/POST/DELETE /sources            源列表（可按分组筛）/ 更新 / 新建 / 删除
- POST /sources/batch                     批量：移组（group_id，null=移出）+ 启停（enabled）
- POST /sources/{source_id}/crawl         立即抓取单个源（同步，返回该源最新状态）
- POST /sources/crawl                     立即抓取选中的源（后台跑，前端轮询列表看状态）
- POST /sources/import-opml               批量导入 OPML 到分组（不依赖主题）
- GET/POST /source-groups                 分组列表 / 新建
- PUT/DELETE /source-groups/{group_id}    分组更新 / 删除（内置分组拒删）

只做参数校验与编排，业务逻辑在 source_service；更新/新建/删除后同步重调度对应 cron job，
不用重启进程就能生效（cron_expr 入库就是为了这个）。
"""
from __future__ import annotations

import threading
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.core.deps import get_current_user
from app.hotlist.models import HotSource
from app.hotlist.schemas.source import (
    SourceBatchIn,
    SourceCrawlIn,
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
from app.hotlist.services import (
    crawl_service,
    opml_service,
    scheduler_jobs,
    source_service,
)

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


# ------------------------------------------------------------ 立即抓取 ----
# 排障入口：状态列显示的是「上一次抓取」的结果，源的 cron 可能是 4 小时一次，
# 改完配置或网络恢复后不该干等到下一个整点才知道好没好。故意不加限频——
# 它是给人点的排障按钮，不是定时任务。

MAX_MANUAL_CRAWL_SOURCES = 200

# 运行中的手动批量抓取（进程内）。抓取跑在后台线程，前端刷新页面后自己的状态会丢，
# 这里记住「谁在跑、跑到哪了」，前端靠 GET /crawl-status 恢复进度显示。
# 完成后保留一小段时间再清，方便前端拿到「已抓完（含失败/跳过数）」的收尾信息。
_active_crawls: dict[str, dict] = {}
_ACTIVE_CRAWL_TTL_SECONDS = 600


def _prune_finished_crawls() -> None:
    """清掉完成超过 TTL 的批次，避免手动点多了在内存里堆积。"""
    now = time.time()
    stale = [
        jid
        for jid, job in _active_crawls.items()
        if job["finished"] and now - job["finished_at"] > _ACTIVE_CRAWL_TTL_SECONDS
    ]
    for jid in stale:
        _active_crawls.pop(jid, None)


@router.post("/crawl")
def crawl_sources(
    payload: SourceCrawlIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> dict:
    """立即抓取选中的源（source_ids 为空 = 全部启用中的源）。

    后台线程跑、立即返回：几十个源即使有熔断也要十几秒，同步等会顶到网关超时。
    返回 job_id，前端拿它轮询 GET /crawl-status 看进度；页面刷新也能靠 job_id 恢复。
    """
    source_ids = payload.source_ids or [
        row[0]
        for row in db.query(HotSource.id)
        .filter(HotSource.enabled.is_(True))
        .order_by(HotSource.sort_order.asc())
        .all()
    ]
    if not source_ids:
        raise HTTPException(400, "没有可抓取的源")
    if len(source_ids) > MAX_MANUAL_CRAWL_SOURCES:
        raise HTTPException(
            400, f"一次最多抓取 {MAX_MANUAL_CRAWL_SOURCES} 个源，请分批"
        )

    # 记录这批源开跑前的 last_fetched_at 作为基线：抓取时无论成败都会刷新
    # last_fetched_at，进度 = 与基线不同的源数量。
    before = {
        row[0]: row[1]
        for row in db.query(HotSource.id, HotSource.last_fetched_at)
        .filter(HotSource.id.in_(source_ids))
        .all()
    }
    job_id = uuid.uuid4().hex
    _active_crawls[job_id] = {
        "source_ids": list(source_ids),
        "total": len(source_ids),
        "before": before,
        "finished": False,
        "finished_at": None,
        "skipped": False,
        "failed": 0,
    }
    _prune_finished_crawls()

    def _worker(ids: list[str]) -> None:
        worker_db = SessionLocal()
        try:
            result = crawl_service.run_crawl(
                worker_db, source_ids=ids, trigger="manual"
            )
            _active_crawls[job_id].update(
                finished=True,
                finished_at=time.time(),
                skipped=result.skipped,
                failed=result.failed_count,
            )
        except Exception:  # noqa: BLE001  后台线程兜底
            logger.exception("手动抓取选中源失败")
            _active_crawls[job_id].update(
                finished=True, finished_at=time.time()
            )
        finally:
            worker_db.close()

    threading.Thread(target=_worker, args=(list(source_ids),), daemon=True).start()
    return {"triggered": True, "count": len(source_ids), "job_id": job_id}


@router.get("/crawl-status")
def crawl_status(
    job_id: str = Query(...),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> dict:
    """查询一次手动批量抓取的进度。页面刷新后靠 job_id 恢复「正在抓取」的显示。

    - 未知 job_id：返回 running=False（可能早就抓完被清理了）。
    - 进行中：返回 running=True + done/total。
    - 已结束：返回 running=False + finished=True + skipped/failed 收尾信息。
    """
    job = _active_crawls.get(job_id)
    if job is None:
        return {"running": False}

    if job["finished"]:
        return {
            "running": False,
            "finished": True,
            "total": job["total"],
            "done": job["total"],
            "skipped": job["skipped"],
            "failed": job["failed"],
        }

    current = {
        row[0]: row[1]
        for row in db.query(HotSource.id, HotSource.last_fetched_at)
        .filter(HotSource.id.in_(job["source_ids"]))
        .all()
    }
    done = sum(
        1
        for sid in job["source_ids"]
        if current.get(sid) != job["before"].get(sid)
    )
    return {
        "running": True,
        "total": job["total"],
        "done": done,
        "source_ids": job["source_ids"],
    }


@router.post("/{source_id}/crawl")
def crawl_one_source(
    source_id: str,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> SourceOut:
    """立即抓取单个源，**同步**执行并返回该源抓完后的最新状态。

    单个源最多几秒，同步返回的好处是前端点完直接就能看到这一行变成「正常」
    或者变成带具体原因的失败（域名解析失败 / 地址失效 404 / …）。
    """
    source = db.get(HotSource, source_id)
    if source is None:
        raise HTTPException(404, "源不存在")
    if not source.enabled:
        raise HTTPException(400, "源已停用，请先启用再抓取")
    result = crawl_service.run_crawl(
        db, source_ids=[source_id], trigger="manual"
    )
    if result.skipped:
        raise HTTPException(503, "本机网络当前不可用（DNS 解析失败），未执行抓取")
    db.expire_all()
    return SourceOut.model_validate(db.get(HotSource, source_id))


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
