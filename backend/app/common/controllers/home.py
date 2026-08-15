from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.database import get_db
from app.common.models import Task
from app.common.schemas.home import (
    HomeResponse,
    HomeSummary,
    RunningTask,
    StorageStats,
    StorageTrendPoint,
    TrendPoint,
)
from app.common.schemas.task import TaskOut

router = APIRouter(prefix="/api/home", tags=["home"])


def _as_utc(dt: datetime | None) -> datetime | None:
    """SQLite 读出的 datetime 是 naive 的，统一补上 UTC 时区再比较"""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


@router.get("", response_model=HomeResponse)
def get_home(db: Session = Depends(get_db), _=Depends(get_current_user)):
    recent_tasks = db.query(Task).order_by(Task.created_at.desc()).limit(5).all()

    # ---- 运行中任务（首页实时卡片，聚合所有模块）----
    running_tasks: list[RunningTask] = []
    # 1) 通用采集/分析任务（排队中/运行中）
    for t in (
        db.query(Task)
        .filter(Task.status.in_(("pending", "running")))
        .order_by(Task.created_at.desc())
        .all()
    ):
        extra = None
        if t.module == "xhs":
            from app.xhs.models import XhsTaskExtra
            extra = db.get(XhsTaskExtra, t.id)
        running_tasks.append(
            RunningTask(
                id=t.id,
                kind="collect",
                title=(t.params or {}).get("keyword") or f"{t.module} 任务",
                status=t.status,
                phase=extra.phase if extra else None,
                progress_current=extra.progress_current if extra else None,
                progress_total=extra.progress_total if extra else None,
                started_at=t.started_at,
            )
        )
    # 2) 补抓评论中（独立后台线程，status 保持 success，phase 标记进行中）
    from app.xhs.models import XhsTaskExtra
    for extra in (
        db.query(XhsTaskExtra)
        .filter(XhsTaskExtra.phase == "fetching_missing_comments")
        .all()
    ):
        t = db.get(Task, extra.task_id)
        if t:
            running_tasks.append(
                RunningTask(
                    id=t.id,
                    kind="backfill",
                    title=(t.params or {}).get("keyword", "采集任务"),
                    status=t.status,
                    phase=extra.phase,
                    progress_current=extra.progress_current,
                    progress_total=extra.progress_total,
                    started_at=t.started_at,
                )
            )
    # 3) 追踪任务扫描中
    from app.xhs.models import XhsTrackingTask
    for tt in (
        db.query(XhsTrackingTask)
        .filter(XhsTrackingTask.status == "running")
        .order_by(XhsTrackingTask.last_run_at.desc())
        .all()
    ):
        running_tasks.append(
            RunningTask(
                id=tt.id,
                kind="tracking",
                title=tt.keyword,
                status="running",
                phase="scanning",
                started_at=tt.last_run_at,
            )
        )

    total_tasks = db.query(func.count(Task.id)).scalar() or 0
    success_count = db.query(func.count(Task.id)).filter(Task.status == "success").scalar() or 0
    failed_count = db.query(func.count(Task.id)).filter(Task.status == "failed").scalar() or 0
    running_count = db.query(func.count(Task.id)).filter(Task.status.in_(("pending", "running"))).scalar() or 0

    # ---- 监控看板统计：近 7 天趋势 / 状态分布 / 今日新增完成 / 成功率 ----
    all_tasks = db.query(Task).all()
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    status_distribution = {"pending": 0, "running": 0, "success": 0, "failed": 0}
    today_new = 0
    today_done = 0
    trend_map: dict[str, dict] = {}
    for i in range(6, -1, -1):
        d = (now - timedelta(days=i)).date()
        trend_map[d.isoformat()] = {"created": 0, "finished": 0}

    for t in all_tasks:
        status_distribution[t.status] = status_distribution.get(t.status, 0) + 1
        created_utc = _as_utc(t.created_at)
        finished_utc = _as_utc(t.finished_at)
        if created_utc and created_utc >= today_start:
            today_new += 1
        if finished_utc and finished_utc >= today_start:
            today_done += 1
        if created_utc:
            day = created_utc.date().isoformat()
            if day in trend_map:
                trend_map[day]["created"] += 1
        if finished_utc:
            day = finished_utc.date().isoformat()
            if day in trend_map:
                trend_map[day]["finished"] += 1

    trend = [
        TrendPoint(date=day, created=v["created"], finished=v["finished"])
        for day, v in trend_map.items()
    ]
    done_total = success_count + failed_count
    success_rate = round(success_count / done_total * 100, 1) if done_total else 0.0

    return HomeResponse(
        recent_tasks=[TaskOut.model_validate(t) for t in recent_tasks],
        running_tasks=running_tasks,
        trend=trend,
        status_distribution=status_distribution,
        summary=HomeSummary(
            total_tasks=total_tasks,
            success_count=success_count,
            failed_count=failed_count,
            running_count=running_count,
            today_new=today_new,
            today_done=today_done,
            success_rate=success_rate,
        ),
    )


# ------------------------------------------------------------ 存储概览 ----
# 首页"存储概览"：数据库文件 + 素材/Excel 目录占用 + 各数据表行数 + 近 24h 趋势折线。
# 独立接口 + 前端低频轮询（30s）；惰性采样（距上次 ≥ 5 分钟插一条快照），
# 不用常驻定时任务，接口有人看才采样。

STORAGE_SAMPLE_INTERVAL_MINUTES = 5
STORAGE_TREND_HOURS = 24


def _dir_size(path: str) -> int:
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    except OSError:
        pass
    return total


@router.get("/storage", response_model=StorageStats)
def get_storage_stats(db: Session = Depends(get_db), _=Depends(get_current_user)):
    from app.common.models import StorageSnapshot

    # 数据库文件：从 engine URL 解析 sqlite 路径（docker 里是 /app/data/workbench.db）
    db_path = ""
    url = str(db.get_bind().engine.url)
    if url.startswith("sqlite:///"):
        db_path = url[len("sqlite:///"):]
    db_size = os.path.getsize(db_path) if db_path and os.path.exists(db_path) else 0

    # 素材/Excel 存储目录（backend/storage，docker 里 /app/storage）
    from app.core.config import BASE_DIR
    storage_dir = str(BASE_DIR / "storage")
    storage_size = _dir_size(storage_dir) if os.path.isdir(storage_dir) else 0

    from app.xhs.models import XhsNote, XhsNoteComment, XhsNoteStructured, XhsAnalysisReport
    note_count = db.query(func.count(XhsNote.note_id)).scalar() or 0
    comment_count = db.query(func.count(XhsNoteComment.comment_id)).scalar() or 0
    structured_count = db.query(func.count(XhsNoteStructured.note_id)).scalar() or 0
    report_count = db.query(func.count(XhsAnalysisReport.id)).scalar() or 0
    task_count = db.query(func.count(Task.id)).scalar() or 0

    # ---- 惰性采样：距上次采样 ≥ 5 分钟才插一条快照（并清理超 24h 的旧数据）----
    now = datetime.now(timezone.utc)
    last = (
        db.query(StorageSnapshot)
        .order_by(StorageSnapshot.sampled_at.desc())
        .first()
    )
    if last is None or (_as_utc(last.sampled_at) is not None
                        and (now - _as_utc(last.sampled_at)).total_seconds() >= STORAGE_SAMPLE_INTERVAL_MINUTES * 60):
        db.add(StorageSnapshot(
            db_size=db_size,
            storage_size=storage_size,
            note_count=note_count,
            comment_count=comment_count,
        ))
        cutoff = now - timedelta(hours=STORAGE_TREND_HOURS)
        db.query(StorageSnapshot).filter(StorageSnapshot.sampled_at < cutoff.replace(tzinfo=None)).delete()
        db.commit()

    # ---- 近 24h 趋势（最多 288 点）----
    cutoff = now - timedelta(hours=STORAGE_TREND_HOURS)
    snapshots = (
        db.query(StorageSnapshot)
        .filter(StorageSnapshot.sampled_at >= cutoff.replace(tzinfo=None))
        .order_by(StorageSnapshot.sampled_at.asc())
        .all()
    )
    trend = [
        StorageTrendPoint(
            t=_as_utc(s.sampled_at).strftime("%H:%M") if _as_utc(s.sampled_at) else "",
            db=s.db_size,
            storage=s.storage_size,
        )
        for s in snapshots
    ]

    return StorageStats(
        db_size=db_size,
        storage_size=storage_size,
        note_count=note_count,
        comment_count=comment_count,
        structured_count=structured_count,
        report_count=report_count,
        task_count=task_count,
        trend=trend,
    )
