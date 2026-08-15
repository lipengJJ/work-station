"""APScheduler 定时任务注册：每源独立 cron job + 每日保留策略 job。

- job id 前缀 ai_trending_，全部 replace_existing=True（重启幂等）；
- 每源 job 独立，任一源失败不阻塞其他源；
- job 内 SessionLocal() 自开自关（调度器线程不能跨线程共享 Session）。
"""
from __future__ import annotations

from apscheduler.jobstores.base import JobLookupError
from loguru import logger

from app.ai_trending.services.collector import collector
from app.ai_trending.services.push_service import push_service
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
PUSH_JOB_ID = "ai_trending_push"


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


# ------------------------------------------------------------ 定时推送 ----
def _parse_push_time(push_time: str) -> tuple[int, int]:
    """把 HH:MM 配置串解析成 (hour, minute)；非法时回退默认 09:00。"""
    try:
        hour = int(push_time[:2])
        minute = int(push_time[3:5])
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    except (ValueError, IndexError):
        pass
    return 9, 0


def _run_push_job() -> None:
    """定时推送 job 执行体：SessionLocal() 自开自关，异常 logger.exception 兜底。"""
    db = SessionLocal()
    try:
        push_service.run_push(db)
    except Exception:  # noqa: BLE001  job 内兜底，避免异常打到调度器线程
        logger.exception("ai_trending 定时推送任务异常")
    finally:
        db.close()


def register_push_job() -> None:
    """注册/移除定时推送 cron job（幂等，replace_existing=True）。

    读配置：enabled 且 webhook_url 非空 → 按 push_time 注册；否则 unregister（确保不残留）。
    """
    scheduler = get_scheduler()
    db = SessionLocal()
    try:
        cfg = push_service.get_config(db)
        if cfg.enabled and (cfg.webhook_url or "").strip():
            hour, minute = _parse_push_time(cfg.push_time)
            scheduler.add_job(
                func=_run_push_job,
                trigger="cron",
                id=PUSH_JOB_ID,
                hour=hour,
                minute=minute,
                replace_existing=True,
            )
            logger.info(f"AI 热点定时推送已注册: 每天 {cfg.push_time}（本地时区）")
        else:
            unregister_push_job()
    except Exception:  # noqa: BLE001  注册失败不影响其他 job
        logger.exception("注册 AI 热点定时推送 job 失败")
    finally:
        db.close()


def unregister_push_job() -> None:
    """移除定时推送 job；不存在时 JobLookupError 兜底。"""
    scheduler = get_scheduler()
    try:
        job = scheduler.get_job(PUSH_JOB_ID)
        if job:
            job.remove()
            logger.info("AI 热点定时推送 job 已移除")
    except JobLookupError:
        pass


def reschedule_push_job(db) -> None:
    """配置保存后重调度（controller 先 commit + expire_all 确保读到最新配置）。

    读最新配置：enabled 且 webhook_url 非空 → add_job(replace_existing=True)；否则移除。
    """
    cfg = push_service.get_config(db)
    if cfg.enabled and (cfg.webhook_url or "").strip():
        hour, minute = _parse_push_time(cfg.push_time)
        get_scheduler().add_job(
            func=_run_push_job,
            trigger="cron",
            id=PUSH_JOB_ID,
            hour=hour,
            minute=minute,
            replace_existing=True,
        )
        logger.info(f"AI 热点定时推送已重调度: 每天 {cfg.push_time}（本地时区）")
    else:
        unregister_push_job()


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
    """进程启动时注册全部热点源 job + 每日清理 job + 定时推送 job + enabled 主题 job（main.py lifespan 调用）。"""
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
    register_push_job()
    # 主题跟踪：把 enabled 主题按 interval 挂上定时器（幂等 replace_existing=True）
    _register_all_enabled_topic_jobs()
    logger.info(
        f"ai_trending 定时任务已注册：{len(registry.list())} 个来源 + 每日清理 + 定时推送 + 主题"
    )


# ------------------------------------------------------------ 主题 job ----
TOPIC_JOB_PREFIX = "ai_trending_topic_"


def _topic_job_id(topic_id: int) -> str:
    return f"{TOPIC_JOB_PREFIX}{topic_id}"


def _run_topic_job(topic_id: int) -> None:
    """主题定时扫描 job 执行体：topic_service 内部 SessionLocal() 自开自关，异常不外抛。"""
    from app.ai_trending.services.topic_service import run_topic_scan

    try:
        run_topic_scan(topic_id)
    except Exception:  # noqa: BLE001  job 内兜底，避免异常打到调度器线程
        logger.exception(f"ai_trending 主题 {topic_id} 定时任务异常")


def register_topic_job(topic) -> None:
    """注册/更新主题 interval job（enabled=False 时注销；replace_existing=True 幂等）。"""
    if not topic.enabled:
        unregister_topic_job(topic.id)
        return
    scheduler = get_scheduler()
    scheduler.add_job(
        func=_run_topic_job,
        trigger="interval",
        minutes=topic.interval_minutes,
        id=_topic_job_id(topic.id),
        args=[topic.id],
        replace_existing=True,
    )
    logger.info(f"AI 热点主题 {topic.id}「{topic.name}」job 已注册: 每 {topic.interval_minutes} 分钟")


def unregister_topic_job(topic_id: int) -> None:
    """注销主题 job；不存在时 JobLookupError 兜底。"""
    scheduler = get_scheduler()
    try:
        job = scheduler.get_job(_topic_job_id(topic_id))
        if job:
            job.remove()
            logger.info(f"AI 热点主题 {topic_id} job 已移除")
    except JobLookupError:
        pass


def _register_all_enabled_topic_jobs() -> None:
    """启动兜底：把所有 enabled=True 的主题挂上定时器（读库不抛错，失败不影响其他 job）。"""
    from app.ai_trending.models import AiTrendingTopic

    db = SessionLocal()
    try:
        topics = (
            db.query(AiTrendingTopic)
            .filter(AiTrendingTopic.enabled.is_(True))
            .all()
        )
        for topic in topics:
            register_topic_job(topic)
    except Exception:  # noqa: BLE001  表不存在等场景兜底
        logger.exception("注册 AI 热点主题 job 失败")
    finally:
        db.close()
