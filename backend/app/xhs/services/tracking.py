"""
追踪任务：按关键词 + 过滤条件（必须包含/排除的关键词）周期性搜索小红书，命中的笔记存进
XhsTrackingHit。定时靠 APScheduler 按 interval_minutes 往 app/xhs/tasks.py 那个单线程
worker 队列里丢一个扫描任务——不自己开线程/开队列，跟普通采集任务共用同一个串行 worker，
避免和小红书风控冲突（这条约束和 tasks.py 顶部注释是一回事）。

扫描逻辑是"先搜索拿 id 列表、再逐条拉详情"的两段式调用，跟 tasks.py::_run_task 里那段
基本一致，但没有直接复用那个函数——_run_task 是为一次性采集任务写的，裹了进度/媒体下载/
评论抓取一堆逻辑，追踪扫描不需要这些，重新写一个精简版本更清楚。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from apscheduler.job import Job
from loguru import logger
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.scheduler import get_scheduler
from app.common.models import Task
from app.common.services.notify_service import notify_task_result
from app.xhs.models import XhsTrackingHit, XhsTrackingTask
from app.xhs.services.xhs_errors import XhsAuthError
from app.xhs.services import note_cache, note_preprocess, token_store
from app.xhs.services.spider import Data_Spider

_JOB_ID_PREFIX = "xhs_tracking_"


def _record_task(db: Session, tracking_task_id: int, keyword: str, status: str, summary: str) -> int:
    """追踪任务每次执行都记一条 Task——首页监控看板（任务总数/今日新增/趋势图/任务中心）
    就能体现追踪扫描也是一次任务执行。失败也记，方便在任务中心看到失败原因。
    返回新建 Task 的 id，调用方 commit 后用它触发微信通知。"""
    now = datetime.now(timezone.utc)
    row = Task(
        module="xhs",
        task_type="xhs_tracking",
        status=status,
        params={"keyword": keyword, "tracking_task_id": tracking_task_id},
        result_summary=summary,
        created_at=now,
        started_at=now,
        finished_at=now,
    )
    db.add(row)
    db.flush()  # 拿自增 id（在调用方 commit 之前 flush 即可，通知线程在 commit 后才触发）
    return row.id


def _job_id(tracking_task_id: int) -> str:
    return f"{_JOB_ID_PREFIX}{tracking_task_id}"


_FREQUENCY_MINUTES = {"realtime": 0, "1h": 60, "6h": 360, "12h": 720, "daily": 1440}


def _in_notify_window(task) -> bool:
    """当前时间（Asia/Shanghai）是否在任务通知时段内；start/end 为空 = 不限时段。"""
    from datetime import datetime as dt

    if not task.notify_time_start or not task.notify_time_end:
        return True
    try:
        now = dt.now().strftime("%H:%M")
        start, end = task.notify_time_start, task.notify_time_end
        if end < start:  # 跨天时段（如 22:00-08:00）
            return now >= start or now <= end
        return start <= now <= end
    except Exception:
        return True


def notify_task_hits(db: Session, tracking_task_id: int, new_hits: int) -> None:
    """按任务的机器人通知配置评估并推送（渠道/时段/频率/仅新命中），异常不阻塞任务。"""
    try:
        task = db.get(XhsTrackingTask, tracking_task_id)
        if not task or not task.notify_enabled:
            return
        from app.common.services.notify_service import send_task_hits_to_channels

        channel_ids = json.loads(task.notify_channel_ids or "[]")
        if not channel_ids:
            return
        title = f"追踪任务「{task.name}」"
        in_window = _in_notify_window(task)
        freq = _FREQUENCY_MINUTES.get(task.notify_frequency, 0)

        # 时段外：命中暂存，等进入时段后合并推送
        if not in_window:
            if new_hits > 0:
                task.notify_pending_hits = (task.notify_pending_hits or 0) + new_hits
                if not task.notify_pending_since:
                    task.notify_pending_since = datetime.now(timezone.utc)
                db.commit()
            return

        pending = task.notify_pending_hits or 0
        total = pending + new_hits

        # 无新命中（含无暂存）：按「仅新命中」开关决定是否发空消息
        if total == 0:
            if task.notify_only_on_hit:
                return
            content = f"本次无新增结果"
            send_task_hits_to_channels(db, channel_ids, title, content)
            return

        # 频率判断：实时立即推；汇总类看距首次暂存是否达到间隔
        if freq > 0 and task.notify_pending_since:
            elapsed = (datetime.now(timezone.utc) - task.notify_pending_since).total_seconds() / 60
            if elapsed < freq:
                task.notify_pending_hits = total
                db.commit()
                return

        # 推送（合并暂存 + 本次）
        content = (
            f"关键词「{task.keyword}」新增命中 {total} 篇"
            + (f"（含暂存 {pending} 篇）" if pending else "")
            + "\n点击查看：https://www.xiaohongshu.com/search_result?keyword="
            + task.keyword
        )
        send_task_hits_to_channels(db, channel_ids, title, content)
        task.notify_pending_hits = 0
        task.notify_pending_since = None
        db.commit()
    except Exception:
        logger.exception(f"机器人通知评估失败（任务 {tracking_task_id}）")


def _total_hit_count(db: Session, tracking_task_id: int) -> int:
    return (
        db.query(XhsTrackingHit)
        .filter(XhsTrackingHit.tracking_task_id == tracking_task_id, XhsTrackingHit.matched.is_(True))
        .count()
    )


def _next_run_at(tracking_task_id: int) -> Optional[str]:
    """
    读 APScheduler 里这个任务的真实 job.next_run_time——job 只在 enabled 时才注册
    （见 register_job/unregister_job），没注册就是 None，不在前端用 last_run_at +
    interval_minutes 硬推算一个假值。
    """
    job = get_scheduler().get_job(_job_id(tracking_task_id))
    if not job or not job.next_run_time:
        return None
    return job.next_run_time.isoformat()


def serialize_task(db: Session, task: XhsTrackingTask) -> dict:
    return {
        "id": task.id,
        "name": task.name,
        "keyword": task.keyword,
        "require_num": task.require_num,
        "sort_type_choice": task.sort_type_choice,
        "note_type": task.note_type,
        "note_time": task.note_time,
        "note_range": task.note_range,
        "must_include": json.loads(task.must_include or "[]"),
        "must_exclude": json.loads(task.must_exclude or "[]"),
        "interval_minutes": task.interval_minutes,
        "enabled": task.enabled,
        "notify_enabled": task.notify_enabled,
        "notify_channel_ids": json.loads(task.notify_channel_ids or "[]"),
        "notify_time_start": task.notify_time_start,
        "notify_time_end": task.notify_time_end,
        "notify_frequency": task.notify_frequency,
        "notify_only_on_hit": task.notify_only_on_hit,
        "status": task.status,
        "last_run_at": task.last_run_at.isoformat() if task.last_run_at else None,
        "last_run_message": task.last_run_message,
        "last_hit_count": task.last_hit_count,
        "total_hit_count": _total_hit_count(db, task.id),
        "next_run_at": _next_run_at(task.id),
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


def list_tracking_tasks(db: Session) -> list[dict]:
    tasks = db.query(XhsTrackingTask).order_by(XhsTrackingTask.created_at.desc()).all()
    return [serialize_task(db, t) for t in tasks]


def get_tracking_task(db: Session, tracking_task_id: int) -> Optional[XhsTrackingTask]:
    return db.get(XhsTrackingTask, tracking_task_id)


def create_tracking_task(db: Session, params: dict) -> dict:
    task = XhsTrackingTask(
        name=params["name"],
        keyword=params["keyword"],
        require_num=params.get("require_num", 50),
        sort_type_choice=params.get("sort_type_choice", 0),
        note_type=params.get("note_type", 0),
        note_time=params.get("note_time", 0),
        note_range=params.get("note_range", 0),
        must_include=json.dumps(params.get("must_include") or [], ensure_ascii=False),
        must_exclude=json.dumps(params.get("must_exclude") or [], ensure_ascii=False),
        interval_minutes=params.get("interval_minutes", 60),
        enabled=params.get("enabled", True),
        notify_enabled=params.get("notify_enabled", False),
        notify_channel_ids=json.dumps(params.get("notify_channel_ids") or [], ensure_ascii=False),
        notify_time_start=params.get("notify_time_start"),
        notify_time_end=params.get("notify_time_end"),
        notify_frequency=params.get("notify_frequency", "realtime"),
        notify_only_on_hit=params.get("notify_only_on_hit", True),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    if task.enabled:
        register_job(task)
    return serialize_task(db, task)


def update_tracking_task(db: Session, tracking_task_id: int, params: dict) -> Optional[dict]:
    task = db.get(XhsTrackingTask, tracking_task_id)
    if not task:
        return None
    task.name = params["name"]
    task.keyword = params["keyword"]
    task.require_num = params.get("require_num", task.require_num)
    task.sort_type_choice = params.get("sort_type_choice", task.sort_type_choice)
    task.note_type = params.get("note_type", task.note_type)
    task.note_time = params.get("note_time", task.note_time)
    task.note_range = params.get("note_range", task.note_range)
    task.must_include = json.dumps(params.get("must_include") or [], ensure_ascii=False)
    task.must_exclude = json.dumps(params.get("must_exclude") or [], ensure_ascii=False)
    task.interval_minutes = params.get("interval_minutes", task.interval_minutes)
    task.enabled = params.get("enabled", task.enabled)
    task.notify_enabled = params.get("notify_enabled", task.notify_enabled)
    task.notify_channel_ids = json.dumps(params.get("notify_channel_ids") or [], ensure_ascii=False)
    task.notify_time_start = params.get("notify_time_start", task.notify_time_start)
    task.notify_time_end = params.get("notify_time_end", task.notify_time_end)
    task.notify_frequency = params.get("notify_frequency", task.notify_frequency)
    task.notify_only_on_hit = params.get("notify_only_on_hit", task.notify_only_on_hit)
    db.commit()
    db.refresh(task)
    if task.enabled:
        register_job(task)
    else:
        unregister_job(task.id)
    return serialize_task(db, task)


def delete_tracking_task(db: Session, tracking_task_id: int) -> bool:
    task = db.get(XhsTrackingTask, tracking_task_id)
    if not task:
        return False
    unregister_job(tracking_task_id)
    db.query(XhsTrackingHit).filter(XhsTrackingHit.tracking_task_id == tracking_task_id).delete()
    db.delete(task)
    db.commit()
    return True


def list_hits(db: Session, tracking_task_id: int) -> list[dict]:
    rows = (
        db.query(XhsTrackingHit)
        .filter(XhsTrackingHit.tracking_task_id == tracking_task_id, XhsTrackingHit.matched.is_(True))
        .order_by(XhsTrackingHit.created_at.desc())
        .all()
    )
    hits = []
    for row in rows:
        if not row.note_json:
            continue
        note = json.loads(row.note_json)
        note["_hit_id"] = row.id
        hits.append(note)
    return hits


def delete_hit(db: Session, tracking_task_id: int, hit_id: int) -> bool:
    hit = db.get(XhsTrackingHit, hit_id)
    if not hit or hit.tracking_task_id != tracking_task_id:
        return False
    db.delete(hit)
    db.commit()
    return True


def _matches_filter(note_info: dict, must_include: list[str], must_exclude: list[str]) -> bool:
    text = f"{note_info.get('title') or ''} {note_info.get('desc') or ''}".lower()
    if any(kw.lower() in text for kw in must_exclude if kw):
        return False
    return all(kw.lower() in text for kw in must_include if kw)


def run_scan(tracking_task_id: int) -> None:
    """在 xhs worker 线程里执行，自己开关 SessionLocal（和 tasks.py::_run_task 一致）。"""
    db = SessionLocal()
    try:
        task = db.get(XhsTrackingTask, tracking_task_id)
        if not task:
            return

        cookies_str = token_store.get_cookies_str(db)
        if not cookies_str:
            task.status = "failed"
            task.last_run_message = "未配置 token/cookie"
            task.last_run_at = datetime.now(timezone.utc)
            new_task_id = _record_task(db, tracking_task_id, task.keyword, "failed", "追踪扫描失败：未配置 token/cookie")
            db.commit()
            notify_task_result(new_task_id)
            return

        # 登录态心跳探测：失效时本轮扫描直接失败并提示重新登录
        valid, valid_msg = token_store.validate(db)
        if not valid:
            task.status = "failed"
            task.last_run_message = valid_msg
            task.last_run_at = datetime.now(timezone.utc)
            new_task_id = _record_task(db, tracking_task_id, task.keyword, "failed", f"追踪扫描失败：{valid_msg}")
            db.commit()
            notify_task_result(new_task_id)
            return

        task.status = "running"
        db.commit()

        must_include = json.loads(task.must_include or "[]")
        must_exclude = json.loads(task.must_exclude or "[]")

        try:
            data_spider = Data_Spider()
            success, msg, raw_notes = data_spider.xhs_apis.search_some_note(
                task.keyword,
                task.require_num,
                cookies_str,
                task.sort_type_choice,
                task.note_type,
                task.note_time,
                task.note_range,
                0,
                None,
                None,
            )
            if not success:
                raise Exception(msg)

            raw_notes = [n for n in raw_notes if n.get("model_type") == "note"]
            existing_ids = {
                row.note_id
                for row in db.query(XhsTrackingHit.note_id).filter(
                    XhsTrackingHit.tracking_task_id == tracking_task_id
                )
            }

            new_hit_count = 0
            for n in raw_notes:
                note_id = n.get("id")
                if not note_id or note_id in existing_ids:
                    continue
                existing_ids.add(note_id)

                note_url = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={n.get('xsec_token', '')}"
                try:
                    # 全局缓存命中且未过期就直接复用，不重复调用 spider_note()（TODO.md
                    # "小红书笔记数据全局去重缓存"）
                    ok, _note_msg, note_info = note_cache.get_or_fetch_note(
                        db, note_url, note_id, cookies_str, data_spider
                    )
                except Exception as e:
                    logger.warning(f"追踪任务 {tracking_task_id} 笔记 {note_id} 抓取失败，跳过: {e}")
                    continue
                if not ok or not note_info:
                    continue
                # 求攻略/求推荐类没有实质内容的笔记，直接跳过不记入本次追踪命中——规则
                # 判断不花钱，这里不像 tasks.py 那样额外跑 LLM 结构化提炼（追踪任务是
                # 定时自动跑的后台任务，不适合默认产生 LLM 调用开销，结构化预处理留给
                # 用户主动发起的采集任务）。
                if note_preprocess.is_low_content(note_info.get("title", ""), note_info.get("desc", "")):
                    continue

                matched = _matches_filter(note_info, must_include, must_exclude)
                db.add(
                    XhsTrackingHit(
                        tracking_task_id=tracking_task_id,
                        note_id=note_id,
                        matched=matched,
                        note_json=json.dumps(note_info, ensure_ascii=False) if matched else None,
                    )
                )
                if matched:
                    new_hit_count += 1
                db.commit()

            task.status = "idle"
            task.last_run_message = f"扫描完成，本次新增命中 {new_hit_count} 篇"
            task.last_hit_count = new_hit_count
            task.last_run_at = datetime.now(timezone.utc)
            new_task_id = _record_task(
                db, tracking_task_id, task.keyword, "success",
                f"追踪扫描完成：关键词「{task.keyword}」新增命中 {new_hit_count} 篇",
            )
            db.commit()
            notify_task_result(new_task_id)
            notify_task_hits(db, tracking_task_id, new_hit_count)
        except XhsAuthError as e:
            logger.error(f"追踪任务 {tracking_task_id} 因登录态失效终止: {e}")
            task.status = "failed"
            task.last_run_message = f"登录态失效，请重新登录后再试（{e}）"
            task.last_run_at = datetime.now(timezone.utc)
            new_task_id = _record_task(db, tracking_task_id, task.keyword, "failed", f"追踪扫描失败：登录态失效（{e}）")
            db.commit()
            notify_task_result(new_task_id)
        except Exception as e:
            logger.exception(f"追踪任务 {tracking_task_id} 扫描失败")
            task.status = "failed"
            task.last_run_message = str(e)
            task.last_run_at = datetime.now(timezone.utc)
            new_task_id = _record_task(db, tracking_task_id, task.keyword, "failed", f"追踪扫描失败：{str(e)[:120]}")
            db.commit()
            notify_task_result(new_task_id)
    finally:
        db.close()


def register_job(task: XhsTrackingTask) -> None:
    from app.xhs.services.tasks import enqueue_tracking_scan

    scheduler = get_scheduler()
    scheduler.add_job(
        func=enqueue_tracking_scan,
        trigger="interval",
        minutes=task.interval_minutes,
        id=_job_id(task.id),
        args=[task.id],
        replace_existing=True,
    )


def unregister_job(tracking_task_id: int) -> None:
    scheduler = get_scheduler()
    job: Optional[Job] = scheduler.get_job(_job_id(tracking_task_id))
    if job:
        job.remove()


def register_all_enabled_jobs() -> None:
    """进程启动时，把所有 enabled=True 的追踪任务重新挂上定时器。"""
    db = SessionLocal()
    try:
        tasks = db.query(XhsTrackingTask).filter(XhsTrackingTask.enabled.is_(True)).all()
        for task in tasks:
            register_job(task)
    finally:
        db.close()
