"""APScheduler 定时任务注册：每源按 cron_expr 独立 job。

移植自旧 ai_trending/services/scheduler_jobs.py 的写法，改动：
  - job id 前缀 ai_trending_ → hotlist_；
  - cron 配置从 JOB_CRON 常量改为读每个 HotSource.cron_expr（CronTrigger.from_crontab），
    抓取频率可以在前端改，不用改代码重启；
  - register_all_enabled_jobs() 遍历全部源（不只 enabled）并对 enabled=False 的源
    做 remove_job 兜底——否则前端关掉一个源、重启前 job 还在跑。
"""
from __future__ import annotations

from apscheduler.jobstores.base import JobLookupError
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from app.core.database import SessionLocal
from app.core.scheduler import get_scheduler
from app.hotlist.models import HotSource
from app.hotlist.services import crawl_service, push_service

JOB_ID_PREFIX = "hotlist_"
CLEANUP_JOB_ID = "hotlist_cleanup"
PUSH_SWEEP_JOB_ID = "hotlist_push_sweep"


def _job_id(source_id: str) -> str:
    return f"{JOB_ID_PREFIX}{source_id}"


def _run_source_job(source_id: str) -> None:
    """单个源的 job 执行体：自开自关 Session（调度器线程不能跨线程共享 Session），
    异常不外抛，避免打到调度器线程。"""
    db = SessionLocal()
    try:
        crawl_service.run_crawl(db, source_ids=[source_id], trigger="cron")
    except Exception:  # noqa: BLE001
        logger.exception(f"hotlist 定时任务 {source_id} 异常")
    finally:
        db.close()


def _cleanup_job() -> None:
    db = SessionLocal()
    try:
        deleted = crawl_service.cleanup_old_items(db)
        logger.info(f"hotlist 清理完成，删除 {deleted} 条过期条目")
    except Exception:  # noqa: BLE001
        logger.exception("hotlist 清理任务异常")
    finally:
        db.close()


def _push_sweep_job() -> None:
    """补推扫描：抓取完成时已经即时评估过一次推送，这个 job 是兜底——
    规则命中发生在通知时段外时会先暂存，只有定期重新评估才能在进入时段/达到频率间隔后补推出去。"""
    db = SessionLocal()
    try:
        push_service.notify_all_enabled_rules(db)
    except Exception:  # noqa: BLE001
        logger.exception("hotlist 推送补推扫描异常")
    finally:
        db.close()


def register_job(source: HotSource) -> None:
    """注册/更新单个源的 cron job（幂等，replace_existing=True）；enabled=False 则注销。"""
    if not source.enabled:
        unregister_job(source.id)
        return
    scheduler = get_scheduler()
    try:
        trigger = CronTrigger.from_crontab(source.cron_expr or "*/30 * * * *")
    except ValueError:
        logger.warning(f"hotlist 源 {source.id} cron 表达式非法: {source.cron_expr!r}，跳过注册")
        return
    scheduler.add_job(
        func=_run_source_job,
        trigger=trigger,
        id=_job_id(source.id),
        args=[source.id],
        replace_existing=True,
    )


def unregister_job(source_id: str) -> None:
    scheduler = get_scheduler()
    try:
        job = scheduler.get_job(_job_id(source_id))
        if job:
            job.remove()
    except JobLookupError:
        pass


def register_all_enabled_jobs() -> None:
    """进程启动时按当前 hot_sources 表状态注册全部 job（main.py lifespan 调用）。"""
    db = SessionLocal()
    try:
        sources = db.query(HotSource).all()
        for source in sources:
            register_job(source)
        enabled_count = sum(1 for s in sources if s.enabled)
        logger.info(f"hotlist 定时任务已注册：{enabled_count}/{len(sources)} 个源")
    except Exception:  # noqa: BLE001  表不存在等场景兜底，不阻塞启动
        logger.exception("注册 hotlist 定时任务失败")
    finally:
        db.close()

    scheduler = get_scheduler()
    scheduler.add_job(
        func=_cleanup_job,
        trigger="cron",
        id=CLEANUP_JOB_ID,
        replace_existing=True,
        hour=3,
        minute=30,
    )
    scheduler.add_job(
        func=_push_sweep_job,
        trigger="interval",
        id=PUSH_SWEEP_JOB_ID,
        replace_existing=True,
        minutes=15,
    )
