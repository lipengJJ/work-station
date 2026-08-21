"""APScheduler 定时任务注册：每源按 cron_expr 独立 job + 主题报告 job。

移植自旧 ai_trending/services/scheduler_jobs.py 的写法，改动：
  - job id 前缀 ai_trending_ → hotlist_；
  - cron 配置从 JOB_CRON 常量改为读每个 HotSource.cron_expr（CronTrigger.from_crontab），
    抓取频率可以在前端改，不用改代码重启；
  - register_all_enabled_jobs() 遍历全部源（不只 enabled）并对 enabled=False 的源
    做 remove_job 兜底——否则前端关掉一个源、重启前 job 还在跑。
  - Phase 7：register_topic_job() 按 HotTopic.digest_cron 注册报告生成 job，
    enabled=False 或 digest_cron 为空时注销。
"""
from __future__ import annotations

import json

from apscheduler.jobstores.base import JobLookupError
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from app.core.database import SessionLocal
from app.core.scheduler import get_scheduler
from app.hotlist.models import HotSource, HotTopic
from app.hotlist.services import (
    crawl_service,
    push_service,
    publish_service,
    topic_report_service,
)

JOB_ID_PREFIX = "hotlist_"
TOPIC_JOB_PREFIX = "hotlist_topic_"
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
    规则命中发生在通知时段外时会先暂存，只有定期重新评估才能在进入时段/达到频率间隔后补推出去。
    主题报告的通知同样依赖它：静默时段生成的报告，到点后补推。"""
    db = SessionLocal()
    try:
        push_service.notify_all_enabled_topics(db)
        _notify_pending_topic_reports(db)
    except Exception:  # noqa: BLE001
        logger.exception("hotlist 推送补推扫描异常")
    finally:
        db.close()


def _notify_pending_topic_reports(db) -> None:
    """补推主题报告：遍历近期成功报告，对启用通知且在通知时段内的主题触发补推。"""
    from app.hotlist.models import HotTopicReport

    reports = (
        db.query(HotTopicReport)
        .filter(HotTopicReport.status == "success")
        .order_by(HotTopicReport.period_end.desc())
        .limit(50)
        .all()
    )
    for report in reports:
        topic = db.get(HotTopic, report.topic_id)
        if topic is None or not topic.report_notify_enabled:
            continue
        try:
            channel_ids = json.loads(topic.report_notify_channel_ids or "[]")
        except (ValueError, TypeError):
            continue
        if (
            not channel_ids
            or not topic_report_service._in_notify_window(topic)
        ):
            continue
        topic_report_service.notify_report(db, report)


# ------------------------------------------------------------ 主题报告 job ----

def _topic_job_id(topic_id: int) -> str:
    return f"{TOPIC_JOB_PREFIX}{topic_id}"


def _run_topic_job(topic_id: int) -> None:
    """主题报告生成 job 执行体：生成 → 发布 → 通知。异常不外抛（调度器线程安全）。"""
    db = SessionLocal()
    try:
        topic = db.get(HotTopic, topic_id)
        if topic is None or not topic.enabled:
            return
        report = topic_report_service.generate_report(db, topic_id)
        if report.status == "success":
            if topic.publish_enabled:
                result = publish_service.publish_report(db, report)
                from datetime import datetime, timezone

                if result["status"] == "success":
                    report.publish_status = "success"
                    report.publish_urls = json.dumps(
                        result["urls"], ensure_ascii=False
                    )
                    report.published_at = datetime.now(timezone.utc)
                else:
                    report.publish_status = "failed"
                    report.error = result.get("error", "")[:500]
                db.commit()
            if topic.report_notify_enabled:
                topic_report_service.notify_report(db, report)
    except Exception:  # noqa: BLE001  生成失败已落库（report.status=failed），这里只记日志
        logger.exception(f"hotlist 主题报告定时任务 {topic_id} 异常")
    finally:
        db.close()


def register_topic_job(topic: HotTopic) -> None:
    """注册/更新单个主题的报告 job（幂等，replace_existing=True）；停用则注销。"""
    if not topic.enabled or not topic.digest_cron:
        unregister_topic_job(topic.id)
        return
    scheduler = get_scheduler()
    try:
        trigger = CronTrigger.from_crontab(topic.digest_cron)
    except ValueError:
        logger.warning(
            f"hotlist 主题 {topic.id} cron 表达式非法: "
            f"{topic.digest_cron!r}，跳过注册"
        )
        return
    scheduler.add_job(
        func=_run_topic_job,
        trigger=trigger,
        id=_topic_job_id(topic.id),
        args=[topic.id],
        replace_existing=True,
    )


def unregister_topic_job(topic_id: int) -> None:
    scheduler = get_scheduler()
    try:
        job = scheduler.get_job(_topic_job_id(topic_id))
        if job:
            job.remove()
    except JobLookupError:
        pass


def register_all_topic_jobs() -> None:
    """进程启动时按 hot_topics 表状态注册全部主题报告 job（main.py lifespan 调用）。"""
    db = SessionLocal()
    try:
        topics = db.query(HotTopic).all()
        for topic in topics:
            register_topic_job(topic)
        enabled_count = sum(1 for t in topics if t.enabled and t.digest_cron)
        logger.info(f"hotlist 主题报告定时任务已注册：{enabled_count}/{len(topics)} 个主题")
    except Exception:  # noqa: BLE001  表不存在等场景兜底，不阻塞启动
        logger.exception("注册 hotlist 主题报告定时任务失败")
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
        logger.warning(
            f"hotlist 源 {source.id} cron 表达式非法: "
            f"{source.cron_expr!r}，跳过注册"
        )
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
    register_all_topic_jobs()

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
