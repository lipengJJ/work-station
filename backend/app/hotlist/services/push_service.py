"""主题实时命中推送编排：时段 + 频率 + 暂存汇总，命中即取 → 组内容 → 发送 → 标记已推送。

移植节奏来自 app/xhs/services/tracking.py::notify_task_hits，把「追踪任务」换成「主题」：
- 推送对象是 HotTopic 的 hit_notify_* 字段（实时命中推送，与 report_notify_* 报告推送正交，
  不要合并——两者触发时机、内容都不同）；
- 命中来源不是一次扫描算出的计数，而是 HotSemanticHit.notified=False 的实际行——这样能精确列出
  「新增命中了哪几条」，不只是报个数字；query_hash 必须与当前主题向量一致，需求变更后的旧命中不推；
- 发送统一走 notify_service.send_task_hits_to_channels，不自建 webhook 发送器。
"""
from __future__ import annotations

from datetime import datetime, timezone
import json

from loguru import logger
from sqlalchemy.orm import Session

from app.hotlist.models import HotItem, HotSemanticHit, HotTopic, HotTopicEmbedding

FREQUENCY_MINUTES = {
    "realtime": 0,
    "1h": 60,
    "6h": 360,
    "12h": 720,
    "daily": 1440,
}
MAX_ITEMS_IN_CONTENT = 20


def _in_notify_window(topic: HotTopic) -> bool:
    """当前时间（本地时区）是否在主题的实时命中通知时段内；start/end 为空 = 不限时段。"""
    if not topic.hit_notify_time_start or not topic.hit_notify_time_end:
        return True
    try:
        now = datetime.now().strftime("%H:%M")
        start, end = topic.hit_notify_time_start, topic.hit_notify_time_end
        if end < start:  # 跨天时段（如 22:00-08:00）
            return now >= start or now <= end
        return start <= now <= end
    except Exception:  # noqa: BLE001  时间格式异常时不卡推送
        return True


def _build_content(
    pending_hits: list[HotSemanticHit],
    items_by_id: dict[int, HotItem],
) -> str:
    """按条目列出命中（最多 20 条），附语义相关度。"""
    lines: list[str] = []
    shown = 0
    for hit in pending_hits:
        if shown >= MAX_ITEMS_IN_CONTENT:
            break
        item = items_by_id.get(hit.item_id)
        if not item:
            continue
        lines.append(f"· {item.title}（相关度 {hit.semantic_score:.2f}）\n  {item.url}")
        shown += 1
    remaining = len(pending_hits) - shown
    if remaining > 0:
        lines.append(f"（还有 {remaining} 条，前往「热点聚合」查看）")
    return "\n".join(lines) if lines else "本次无新增命中"


def notify_topic_hits(db: Session, topic_id: int) -> None:
    """单主题的实时命中推送评估。异常不外抛——推送失败不该影响调用方（抓取流程 / 定时任务）。"""
    try:
        topic = db.get(HotTopic, topic_id)
        if not topic or not topic.hit_notify_enabled:
            return
        channel_ids = json.loads(topic.hit_notify_channel_ids or "[]")
        if not channel_ids:
            return

        from app.common.services.notify_service import (
            send_task_hits_to_channels,
        )

        # 待推送命中：语义命中且未推送；query_hash 必须与当前主题向量一致（需求变更后旧命中不推）
        te = (
            db.query(HotTopicEmbedding)
            .filter(
                HotTopicEmbedding.topic_id == topic_id,
                HotTopicEmbedding.status == "success",
            )
            .first()
        )
        pending_q = (
            db.query(HotSemanticHit)
            .filter(HotSemanticHit.topic_id == topic_id, HotSemanticHit.notified.is_(False))
            .order_by(HotSemanticHit.matched_at.asc())
        )
        if te is not None:
            pending_q = pending_q.filter(HotSemanticHit.query_hash == te.query_hash)
        pending_hits = pending_q.all()
        hit_count = len(pending_hits)
        title = f"【{topic.name}】新增 {hit_count} 条命中"
        in_window = _in_notify_window(topic)
        freq = FREQUENCY_MINUTES.get(topic.hit_notify_frequency, 0)

        # 时段外：命中暂存（不清 HotSemanticHit.notified，等进入时段后一起推）
        if not in_window:
            if hit_count > 0:
                topic.hit_notify_pending_hits = (
                    (topic.hit_notify_pending_hits or 0) + hit_count
                )
                if not topic.hit_notify_pending_since:
                    topic.hit_notify_pending_since = datetime.now(timezone.utc)
                db.commit()
            return

        pending = topic.hit_notify_pending_hits or 0
        total = pending + hit_count

        if total == 0:
            if topic.hit_notify_only_on_hit:
                return
            send_task_hits_to_channels(db, channel_ids, title, "本次无新增命中")
            return

        # 频率判断：realtime 立即推；汇总类看距首次暂存是否达到间隔
        if freq > 0 and topic.hit_notify_pending_since:
            elapsed = (
                datetime.now(timezone.utc) - topic.hit_notify_pending_since
            ).total_seconds() / 60
            if elapsed < freq:
                topic.hit_notify_pending_hits = total
                db.commit()
                return

        item_ids = [h.item_id for h in pending_hits]
        items = (
            db.query(HotItem).filter(HotItem.id.in_(item_ids)).all()
            if item_ids
            else []
        )
        items_by_id = {item.id: item for item in items}
        content = _build_content(pending_hits, items_by_id)

        send_task_hits_to_channels(db, channel_ids, title, content)

        for hit in pending_hits:
            hit.notified = True
        topic.hit_notify_pending_hits = 0
        topic.hit_notify_pending_since = None
        db.commit()
    except Exception:  # noqa: BLE001  推送评估失败不阻塞抓取/调用方
        logger.exception(f"hotlist 主题 {topic_id} 实时命中推送评估失败")


def notify_all_enabled_topics(db: Session) -> None:
    """遍历全部 hit_notify_enabled=True 的主题逐个评估推送。供定时 job 做补推扫描
    ——即使没有新抓取触发，时段外暂存的命中到点后也能补推。"""
    topic_ids = [
        row[0]
        for row in db.query(HotTopic.id)
        .filter(HotTopic.hit_notify_enabled.is_(True))
        .all()
    ]
    for topic_id in topic_ids:
        notify_topic_hits(db, topic_id)
