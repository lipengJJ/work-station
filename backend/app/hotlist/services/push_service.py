"""规则命中推送编排：时段 + 频率 + 暂存汇总，命中即取 → 组内容 → 发送 → 标记已推送。

移植节奏来自 app/xhs/services/tracking.py::notify_task_hits，把「追踪任务」换成「频率词规则」：
- 推送对象是 HotKeywordRule 自带的 notify_* 字段（对齐 XhsTrackingTask，Phase 3 建模时就定好了）；
- 命中来源不是一次扫描算出的计数，而是 HotRuleHit.notified=False 的实际行——这样能精确列出
  「新增命中了哪几条」，不只是报个数字；
- 发送统一走 notify_service.send_task_hits_to_channels，不自建 webhook 发送器。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy.orm import Session

from app.hotlist.models import HotItem, HotKeywordRule, HotRuleHit

FREQUENCY_MINUTES = {"realtime": 0, "1h": 60, "6h": 360, "12h": 720, "daily": 1440}
MAX_ITEMS_IN_CONTENT = 20


def _in_notify_window(rule: HotKeywordRule) -> bool:
    """当前时间（本地时区）是否在规则的通知时段内；start/end 为空 = 不限时段。"""
    if not rule.notify_time_start or not rule.notify_time_end:
        return True
    try:
        now = datetime.now().strftime("%H:%M")
        start, end = rule.notify_time_start, rule.notify_time_end
        if end < start:  # 跨天时段（如 22:00-08:00）
            return now >= start or now <= end
        return start <= now <= end
    except Exception:  # noqa: BLE001  时间格式异常时不卡推送
        return True


def _build_content(pending_hits: list[HotRuleHit], items_by_id: dict[int, HotItem]) -> str:
    lines: list[str] = []
    for hit in pending_hits[:MAX_ITEMS_IN_CONTENT]:
        item = items_by_id.get(hit.item_id)
        if not item:
            continue
        lines.append(f"· {item.title}\n  {item.url}")
    remaining = len(pending_hits) - MAX_ITEMS_IN_CONTENT
    if remaining > 0:
        lines.append(f"（还有 {remaining} 条，前往「热点聚合」查看）")
    return "\n".join(lines) if lines else "本次无新增命中"


def notify_rule_hits(db: Session, rule_id: int) -> None:
    """单条规则的推送评估。异常不外抛——推送失败不该影响调用方（抓取流程 / 定时任务）。"""
    try:
        rule = db.get(HotKeywordRule, rule_id)
        if not rule or not rule.notify_enabled:
            return
        channel_ids = json.loads(rule.notify_channel_ids or "[]")
        if not channel_ids:
            return

        from app.common.services.notify_service import send_task_hits_to_channels

        pending_hits = (
            db.query(HotRuleHit)
            .filter(HotRuleHit.rule_id == rule_id, HotRuleHit.notified.is_(False))
            .order_by(HotRuleHit.matched_at.asc())
            .all()
        )
        hit_count = len(pending_hits)
        title = f"【热点规则】{rule.display_name or '未命名规则'} 新增 {hit_count} 条命中"
        in_window = _in_notify_window(rule)
        freq = FREQUENCY_MINUTES.get(rule.notify_frequency, 0)

        # 时段外：命中暂存（不清 HotRuleHit.notified，等进入时段后一起推）
        if not in_window:
            if hit_count > 0:
                rule.notify_pending_hits = (rule.notify_pending_hits or 0) + hit_count
                if not rule.notify_pending_since:
                    rule.notify_pending_since = datetime.now(timezone.utc)
                db.commit()
            return

        pending = rule.notify_pending_hits or 0
        total = pending + hit_count

        if total == 0:
            if rule.notify_only_on_hit:
                return
            send_task_hits_to_channels(db, channel_ids, title, "本次无新增命中")
            return

        # 频率判断：realtime 立即推；汇总类看距首次暂存是否达到间隔
        if freq > 0 and rule.notify_pending_since:
            elapsed = (datetime.now(timezone.utc) - rule.notify_pending_since).total_seconds() / 60
            if elapsed < freq:
                rule.notify_pending_hits = total
                db.commit()
                return

        item_ids = [h.item_id for h in pending_hits]
        items = db.query(HotItem).filter(HotItem.id.in_(item_ids)).all() if item_ids else []
        items_by_id = {item.id: item for item in items}
        content = _build_content(pending_hits, items_by_id)

        send_task_hits_to_channels(db, channel_ids, title, content)

        for hit in pending_hits:
            hit.notified = True
        rule.notify_pending_hits = 0
        rule.notify_pending_since = None
        db.commit()
    except Exception:  # noqa: BLE001  推送评估失败不阻塞抓取/调用方
        logger.exception(f"hotlist 规则 {rule_id} 推送评估失败")


def notify_all_enabled_rules(db: Session) -> None:
    """遍历全部 notify_enabled=True 的词组规则逐个评估推送。供定时 job 做补推扫描
    ——即使没有新抓取触发，时段外暂存的命中到点后也能补推。"""
    rule_ids = [
        row[0]
        for row in db.query(HotKeywordRule.id)
        .filter(HotKeywordRule.rule_type == "group", HotKeywordRule.notify_enabled.is_(True))
        .all()
    ]
    for rule_id in rule_ids:
        notify_rule_hits(db, rule_id)
