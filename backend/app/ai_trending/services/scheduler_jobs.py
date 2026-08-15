"""APScheduler 定时任务注册：每源独立 cron job + 每日保留策略 job。

- job id 前缀 ai_trending_，全部 replace_existing=True（重启幂等）；
- 每源 job 独立，任一源失败不阻塞其他源；
- job 内 SessionLocal() 自开自关（调度器线程不能跨线程共享 Session）。
"""
from __future__ import annotations

from apscheduler.jobstores.base import JobLookupError
from loguru import logger

from app.ai_trending.services.collector import collector
from app.ai_trending.services.sources import registry  # noqa: F401  确保源已注册
from app.core.database import SessionLocal
from app.core.scheduler import get_scheduler

# 各源 cron 配置（APScheduler cron trigger 参数）
JOB_CRON: dict[str, dict[str, str]] = {
    "hn": {"minute": "0"},  # 每小时
    "github": {"hour": "2,14", "minute": "0"},  # 每日 2 次（GitHub 每日更新）
    "arxiv": {"minute": "0"},  # 每小时
    "hf_models": {"minute": "0"},  # 每小时
    "hf_papers": {"minute": "0"},  # 每小时
    "infoq": {"minute": "0"},  # 每小时
    "kr36": {"minute": "0"},  # 每小时
}

CLEANUP_JOB_ID = "ai_trending_cleanup"


def _job_id(source_id: str) -> str:
    return f"ai_trending_{source_id}"


def _run_source_job(source_id: str) -> None:
    """单个源的 job 执行体：自开自关 Session，异常不外抛（调度器线程安全）。"""
    db = SessionLocal()
    try:
        collector.run_source(source_id, db=db)
    except Exception:  # noqa: BLE001  job 内兜底，避免异常打到调度器线程
        logger.exception(f"ai_trending 定时任务 {source_id} 异常")
    finally:
        db.close()


def _cleanup_job() -> None:
    """每日保留策略 job。"""
    db = SessionLocal()
    try:
        deleted = collector.cleanup_old_items(db)
        logger.info(f"ai_trending 清理完成，删除 {deleted} 条过期条目")
    except Exception:  # noqa: BLE001
        logger.exception("ai_trending 清理任务异常")
    finally:
        db.close()


def register_job(source_id: str) -> None:
    """注册单个来源的 cron job（幂等，replace_existing=True）。"""
    scheduler = get_scheduler()
    cron = JOB_CRON[source_id]
    scheduler.add_job(
        func=_run_source_job,
        trigger="cron",
        id=_job_id(source_id),
        args=[source_id],
        replace_existing=True,
        **cron,
    )


def unregister_job(source_id: str) -> None:
    """注销单个来源的 cron job。"""
    scheduler = get_scheduler()
    try:
        job = scheduler.get_job(_job_id(source_id))
        if job:
            job.remove()
    except JobLookupError:
        pass


def register_all_enabled_jobs() -> None:
    """进程启动时注册全部热点源 job + 每日清理 job（在 main.py lifespan 中调用）。"""
    for source in registry.list():
        register_job(source.source_id)
    scheduler = get_scheduler()
    scheduler.add_job(
        func=_cleanup_job,
        trigger="cron",
        id=CLEANUP_JOB_ID,
        replace_existing=True,
        hour=3,
        minute=30,
    )
    logger.info(f"ai_trending 定时任务已注册：{len(registry.list())} 个来源 + 每日清理")
