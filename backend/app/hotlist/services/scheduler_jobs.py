"""APScheduler 定时任务注册：每源按 interval_hours 独立 job + 主题报告 job。

移植自旧 ai_trending/services/scheduler_jobs.py 的写法，改动：
  - job id 前缀 ai_trending_ → hotlist_；
  - register_all_enabled_jobs() 遍历全部源（不只 enabled）并对 enabled=False 的源
    做 remove_job 兜底——否则前端关掉一个源、重启前 job 还在跑。
  - Phase 7：register_topic_job() 按 HotTopic.digest_cron 注册报告生成 job，
    enabled=False 或 digest_cron 为空时注销。
  - 源抓取 job 与清理 job 都改用 IntervalTrigger + misfire_grace_time=None：
    不用用户填 cron 表达式，且「错过精确触发点」时（机器休眠、进程重启）
    调度器醒来后一定会补跑，不会被 misfire 悄悄跳过。digest_cron（主题报告，
    要求「每天固定时间点」）仍用 CronTrigger，语义不同不能一起换。
"""
from __future__ import annotations

from datetime import datetime, timezone
import threading
import time

from apscheduler.jobstores.base import JobLookupError
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger
from sqlalchemy import or_

from app.core.database import SessionLocal
from app.core.scheduler import get_scheduler
from app.hotlist.models import HotItem, HotItemEmbedding, HotSource, HotTopic
from app.hotlist.services import (
    crawl_service,
    embedding_service,
    push_service,
    publish_service,
    topic_report_service,
)

JOB_ID_PREFIX = "hotlist_"
TOPIC_JOB_PREFIX = "hotlist_topic_"
CLEANUP_JOB_ID = "hotlist_cleanup"
PUSH_SWEEP_JOB_ID = "hotlist_push_sweep"
EMBEDDING_BACKFILL_JOB_ID = "hotlist_embedding_backfill"
EMBEDDING_BACKFILL_BATCH = 200


def _job_id(source_id: str) -> str:
    return f"{JOB_ID_PREFIX}{source_id}"


def _run_source_job(source_id: str) -> None:
    """单个源的 job 执行体：自开自关 Session（调度器线程不能跨线程共享 Session），
    异常不外抛，避免打到调度器线程。

    每次源自己的 cron job 触发时才当场判断「现在还有没有资格自动抓」（分组开了
    资讯爬取 或 被启用中的主题订阅）——这样分组开关/主题订阅关系随时变都不用
    去增删 job，注册阶段（register_job）只按 source.enabled 走，不够格的 job
    留着也只是空转 no-op，比到处补 register/unregister 调用简单可靠。
    """
    db = SessionLocal()
    try:
        if not crawl_service.is_source_crawl_eligible(db, source_id):
            return
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
        topic_report_service.notify_pending_reports(db)
    except Exception:  # noqa: BLE001
        logger.exception("hotlist 推送补推扫描异常")
    finally:
        db.close()


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
                publish_service.apply_publish_result(db, report, result)
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
    """注册/更新单个源的抓取 job（幂等，replace_existing=True）；enabled=False 则注销。

    用 IntervalTrigger 而不是 cron 定点，不需要用户填 cron 表达式；
    misfire_grace_time=None 保证错过了精确触发点（机器休眠/进程重启）也一定补跑，
    不会被静默跳过。IntervalTrigger 默认首次触发是「现在 + 一个完整间隔」而不是
    立即触发（实测过，不是想当然），所以显式传 next_run_time=现在，注册这一刻
    就跑一次，之后再按 interval_hours 周期走。
    """
    if not source.enabled:
        unregister_job(source.id)
        return
    scheduler = get_scheduler()
    hours = source.interval_hours or 0.5
    if hours <= 0:
        logger.warning(
            f"hotlist 源 {source.id} interval_hours 非法: {hours!r}，跳过注册"
        )
        return
    scheduler.add_job(
        func=_run_source_job,
        trigger=IntervalTrigger(hours=hours),
        id=_job_id(source.id),
        args=[source.id],
        replace_existing=True,
        misfire_grace_time=None,
        next_run_time=datetime.now(timezone.utc),
    )


def unregister_job(source_id: str) -> None:
    scheduler = get_scheduler()
    try:
        job = scheduler.get_job(_job_id(source_id))
        if job:
            job.remove()
    except JobLookupError:
        pass


def _fetch_missing_embedding_items(
    db, limit: int, source_ids: list[str] | None = None
) -> list[HotItem]:
    """指定源范围内缺向量/非成功状态的文章；None 表示全库。"""
    query = (
        db.query(HotItem)
        .outerjoin(HotItemEmbedding, HotItemEmbedding.item_id == HotItem.id)
        .filter(
            or_(
                HotItemEmbedding.item_id.is_(None),
                HotItemEmbedding.status != "success",
            )
        )
    )
    if source_ids is not None:
        if not source_ids:
            return []
        query = query.filter(HotItem.source_id.in_(source_ids))
    return query.order_by(HotItem.last_crawl_time.desc()).limit(limit).all()


def _embedding_backfill_job() -> None:
    """低频补偿任务：补算缺失/pending/failed 的文章向量。每轮最多 200 条。

    正常启动不做同步全量计算，避免启动过程依赖外部模型；初次抓取实时建立索引，
    历史缺索引的文章由本任务逐步补齐。
    """
    db = SessionLocal()
    try:
        items = _fetch_missing_embedding_items(db, EMBEDDING_BACKFILL_BATCH)
        if not items:
            logger.debug("hotlist 语义向量补偿任务：本轮无缺索引文章，跳过")
            return
        logger.info(f"hotlist 语义向量补偿任务开始：本轮 {len(items)} 篇待补算")
        stat = embedding_service.ensure_item_embeddings(db, items, best_effort=True)
        progress = embedding_service.get_embedding_progress(db)
        logger.info(
            f"hotlist 语义向量补偿任务完成: {stat}，"
            f"全库已成功索引 {progress['indexed']}/{progress['total']}（剩余 {progress['pending']} 篇）"
        )
    except Exception:  # noqa: BLE001
        logger.exception("hotlist 语义向量补偿任务失败")
    finally:
        db.close()


# ---------------------------------------------------------- 手动全量补算 ----
# 与上面的定时补偿共用同一套查询/补算逻辑，区别只是不限批次、不受 30 分钟节流，
# 用于用户在「热点聚合 → 榜单」页主动点「补算索引」时一次性清空存量缺索引文章。
# 进程内锁防重复触发；已处理成功（status=success 且 hash 未变）的文章
# ensure_item_embeddings 内部会直接跳过，不会重复计算。

_manual_backfill_lock = threading.Lock()
_manual_backfill_running = False


def is_manual_backfill_running() -> bool:
    return _manual_backfill_running


def start_manual_embedding_backfill(source_ids: list[str] | None = None) -> bool:
    """尝试启动手动补算后台线程；已在运行则返回 False（不重复启动）。"""
    global _manual_backfill_running
    with _manual_backfill_lock:
        if _manual_backfill_running:
            return False
        _manual_backfill_running = True
    threading.Thread(
        target=_run_manual_embedding_backfill,
        args=(source_ids,),
        daemon=True,
    ).start()
    return True


def _run_manual_embedding_backfill(source_ids: list[str] | None = None) -> None:
    global _manual_backfill_running
    total_stat = {"generated": 0, "skipped": 0, "failed": 0, "missing_config": 0, "batches": 0}
    db = SessionLocal()
    started_at = time.time()
    try:
        progress = embedding_service.get_embedding_progress(db, source_ids)
        scope_label = "全库" if source_ids is None else f"选中分组 {len(source_ids)} 个源"
        logger.info(
            f"hotlist 语义向量手动补算开始：{scope_label} {progress['indexed']}/{progress['total']} "
            f"已索引，待处理 {progress['pending']} 篇（失败 {progress['failed']} 篇）"
        )
        while True:
            items = _fetch_missing_embedding_items(
                db, EMBEDDING_BACKFILL_BATCH, source_ids
            )
            if not items:
                break
            total_stat["batches"] += 1
            stat = embedding_service.ensure_item_embeddings(db, items, best_effort=True)
            for key in ("generated", "skipped", "failed", "missing_config"):
                total_stat[key] += stat.get(key, 0)
            progress = embedding_service.get_embedding_progress(db, source_ids)
            logger.info(
                f"hotlist 语义向量手动补算进度：第 {total_stat['batches']} 批"
                f"（{len(items)} 篇），本轮累计 {total_stat}，"
                f"全库已成功索引 {progress['indexed']}/{progress['total']}"
                f"（剩余 {progress['pending']} 篇）"
            )
            if stat.get("missing_config"):
                logger.warning("hotlist 语义向量手动补算中止：未配置 Embedding API Key")
                break
        elapsed = time.time() - started_at
        progress = embedding_service.get_embedding_progress(db, source_ids)
        logger.info(
            f"hotlist 语义向量手动补算完成，耗时 {elapsed:.1f}s，本轮结果 {total_stat}，"
            f"全库已成功索引 {progress['indexed']}/{progress['total']}"
            f"（剩余 {progress['pending']} 篇，失败 {progress['failed']} 篇）"
        )
    except Exception:  # noqa: BLE001
        logger.exception("hotlist 语义向量手动补算失败")
    finally:
        db.close()
        _manual_backfill_running = False


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
    # interval 而不是「每天 03:30」定点：之后每 2 天补一次；misfire_grace_time=None
    # 保证机器休眠跨过这个点也不会被跳过——此前用 cron 定点时，日志里这个 job
    # 天天被标记 "missed"，清理实际从未真正跑过。IntervalTrigger 默认首次触发是
    # 「现在 + 一个完整间隔」而非立即触发，显式传 next_run_time=现在，让它在
    # 进程启动这一刻就先跑一次（开发机经常重启/休眠，等 2 天后才第一次跑等于没用）。
    scheduler.add_job(
        func=_cleanup_job,
        trigger="interval",
        days=2,
        id=CLEANUP_JOB_ID,
        replace_existing=True,
        misfire_grace_time=None,
        next_run_time=datetime.now(timezone.utc),
    )
    scheduler.add_job(
        func=_push_sweep_job,
        trigger="interval",
        id=PUSH_SWEEP_JOB_ID,
        replace_existing=True,
        minutes=15,
    )
    # 语义向量低频补偿：每 30 分钟扫描缺索引的文章，分批补算
    scheduler.add_job(
        func=_embedding_backfill_job,
        trigger="interval",
        id=EMBEDDING_BACKFILL_JOB_ID,
        replace_existing=True,
        minutes=30,
    )
