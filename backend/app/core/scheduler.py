"""
进程内单例调度器。Phase 2 只负责启动/关闭；具体业务定时任务（跑股票分析、定时采集小红书）
在 Phase 3 接入 stock-report/collector 与 Spider_XHS/webapp 的逻辑时再注册 job。
"""
from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler

_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
    return _scheduler


def start_scheduler() -> None:
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()


def shutdown_scheduler() -> None:
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
