from datetime import datetime

from pydantic import BaseModel

from app.common.schemas.task import TaskOut


class RunningTask(BaseModel):
    """首页"运行中任务"卡片：采集任务 / 补抓评论 / 追踪扫描 统一结构"""
    id: int
    kind: str  # collect | backfill | tracking
    title: str
    status: str
    phase: str | None = None
    progress_current: int | None = None
    progress_total: int | None = None
    started_at: datetime | None = None


class TrendPoint(BaseModel):
    date: str  # YYYY-MM-DD
    created: int
    finished: int


class HomeSummary(BaseModel):
    total_tasks: int
    success_count: int
    failed_count: int
    running_count: int
    today_new: int
    today_done: int
    success_rate: float


class StorageTrendPoint(BaseModel):
    t: str  # HH:MM
    db: int  # 字节
    storage: int  # 字节


class StorageStats(BaseModel):
    """首页存储概览：数据库/素材占用 + 各数据表行数 + 近 24h 趋势"""
    db_size: int  # 字节
    storage_size: int  # 素材/Excel 目录总字节
    note_count: int
    comment_count: int
    structured_count: int
    report_count: int
    task_count: int
    trend: list[StorageTrendPoint]


class HomeResponse(BaseModel):
    recent_tasks: list[TaskOut]
    running_tasks: list[RunningTask]
    trend: list[TrendPoint]
    status_distribution: dict[str, int]
    summary: HomeSummary
