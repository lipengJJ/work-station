"""AI 热点主题服务层：主题 CRUD + run_topic_scan 扫描编排 + 命中记录 + 推送配置。

仿 xhs services/tracking.py：控制器只做参数校验与编排，扫描逻辑（各源 search() 定向
检索 → upsert items（url_hash 去重）→ 记 topic_hit（Unique 去重）→ 更新主题状态）
都在这一层；调度器线程 / run-now 线程用 SessionLocal() 自开自关，不跨线程共享 Session。

主题命中只来自各源 search() 结果（或 RSS 源 fetch+关键词过滤的降级），不做「全局池过滤」；
命中引用 ai_trending_items.id 不复制数据，与全局热榜共享同一数据底座。
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.ai_trending.models import AiTrendingItem, AiTrendingTopic, AiTrendingTopicHit
from app.ai_trending.schemas.trending import TrendingItemOut
from app.ai_trending.services.base import RawItem, url_hash
from app.ai_trending.services.sources import registry
from app.core.database import SessionLocal

JOB_ID_PREFIX = "ai_trending_topic_"  # 与 scheduler_jobs._topic_job_id 一致
ALLOWED_INTERVALS = (15, 30, 60, 180, 360, 720, 1440)
ALLOWED_CHANNELS = ("wecom", "dingtalk", "feishu", "email")
ALLOWED_FREQUENCIES = ("daily",)  # P0 仅 daily
SEARCH_PAGE_SIZE = 30

# run-now 限频（与 controllers/topic.py 共用同一把锁 + 时间戳表，避免两边各记一份）
_RUN_NOW_LOCK = threading.Lock()
_last_run_now: dict[int, float] = {}
RUN_NOW_COOLDOWN_SECONDS = 60


def _parse_keywords(topic: AiTrendingTopic) -> list[str]:
    """读取主题关键词 JSON 数组；解析失败返回 []。"""
    try:
        data = json.loads(topic.keywords or "[]")
        return [str(k) for k in data if str(k).strip()] if isinstance(data, list) else []
    except (ValueError, TypeError):
        return []


def _next_run_at(topic_id: int) -> str | None:
    """读 APScheduler 里这个主题的真实 job.next_run_time；未注册=None 不硬推算。"""
    try:
        from app.ai_trending.services.scheduler_jobs import _topic_job_id
        from app.core.scheduler import get_scheduler

        job = get_scheduler().get_job(_topic_job_id(topic_id))
        if not job or not job.next_run_time:
            return None
        return job.next_run_time.isoformat()
    except Exception:  # noqa: BLE001  调度器未启动等场景兜底
        return None


def _hit_count(db: Session, topic_id: int) -> int:
    """主题命中总数（matched=True 的 hits 数）。"""
    return (
        db.query(AiTrendingTopicHit)
        .filter(
            AiTrendingTopicHit.topic_id == topic_id,
            AiTrendingTopicHit.matched.is_(True),
        )
        .count()
    )


def serialize_topic(db: Session, topic: AiTrendingTopic) -> dict:
    """ORM → 出参 dict（含计算字段 hit_count / next_run_at，keywords/push 组装）。"""
    return {
        "id": topic.id,
        "name": topic.name,
        "keywords": _parse_keywords(topic),
        "interval_minutes": topic.interval_minutes,
        "enabled": topic.enabled,
        "status": topic.status,
        "last_run_at": topic.last_run_at.isoformat() if topic.last_run_at else None,
        "last_run_message": topic.last_run_message,
        "last_item_count": topic.last_item_count,
        "hit_count": _hit_count(db, topic.id),
        "next_run_at": _next_run_at(topic.id),
        "push": {
            "enabled": topic.push_enabled,
            "channel": topic.push_channel or "wecom",
            "frequency": topic.push_frequency or "daily",
            "time": topic.push_time or "09:00",
        },
        "created_at": topic.created_at.isoformat() if topic.created_at else None,
    }


def list_topics(db: Session) -> list[dict]:
    """主题列表（created_at DESC，每条带 hit_count / next_run_at）。"""
    rows = (
        db.query(AiTrendingTopic)
        .order_by(AiTrendingTopic.created_at.desc())
        .all()
    )
    return [serialize_topic(db, t) for t in rows]


# 别名：控制器 / 前端口径「主题列表带命中数」
list_topic_with_counts = list_topics


def get_topic(db: Session, topic_id: int) -> AiTrendingTopic | None:
    return db.get(AiTrendingTopic, topic_id)


def create_topic(db: Session, params: dict) -> dict:
    """创建主题：校验由 controller/Pydantic 完成；建行后 enabled 则注册 interval job。"""
    push = params.get("push") or {}
    topic = AiTrendingTopic(
        name=params["name"],
        keywords=json.dumps(params["keywords"], ensure_ascii=False),
        interval_minutes=params.get("interval_minutes", 60),
        enabled=params.get("enabled", True),
        push_enabled=bool(push.get("enabled", False)),
        push_channel=push.get("channel") or "wecom",
        push_frequency=push.get("frequency") or "daily",
        push_time=push.get("time") or "09:00",
    )
    db.add(topic)
    db.commit()
    db.refresh(topic)
    if topic.enabled:
        _sync_topic_job(topic)
    logger.info(f"AI 热点主题创建: id={topic.id} name={topic.name!r}")
    return serialize_topic(db, topic)


def update_topic(db: Session, topic_id: int, params: dict) -> dict | None:
    """更新主题：只覆盖传入字段（TopicUpdateIn 全可选）；enabled/interval 变化自动重挂 job。"""
    topic = db.get(AiTrendingTopic, topic_id)
    if not topic:
        return None
    if "name" in params:
        topic.name = params["name"]
    if "keywords" in params:
        topic.keywords = json.dumps(params["keywords"], ensure_ascii=False)
    if "interval_minutes" in params:
        topic.interval_minutes = params["interval_minutes"]
    if "enabled" in params:
        topic.enabled = params["enabled"]
    push = params.get("push")
    if push is not None:
        topic.push_enabled = bool(push.get("enabled", topic.push_enabled))
        if push.get("channel") is not None:
            topic.push_channel = push["channel"]
        if push.get("frequency") is not None:
            topic.push_frequency = push["frequency"]
        if push.get("time") is not None:
            topic.push_time = push["time"]
    topic.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(topic)
    _sync_topic_job(topic)
    return serialize_topic(db, topic)


def delete_topic(db: Session, topic_id: int) -> bool:
    """删除主题：注销 job → 显式删 hits → 删主题（SQLite 外键默认不强制，禁止依赖 CASCADE）。"""
    topic = db.get(AiTrendingTopic, topic_id)
    if not topic:
        return False
    _unregister_topic_job(topic.id)
    deleted_hits = (
        db.query(AiTrendingTopicHit)
        .filter(AiTrendingTopicHit.topic_id == topic_id)
        .delete(synchronize_session=False)
    )
    db.delete(topic)
    db.commit()
    logger.info(
        f"AI 热点主题删除: id={topic_id} name={topic.name!r}，清理命中 {deleted_hits} 条"
    )
    return True


# ------------------------------------------------------------ 扫描编排 ----
def run_topic_scan(topic_id: int) -> None:
    """调度器线程 / run-now 线程执行，SessionLocal() 自开自关（对齐 xhs run_scan）。

    流程：topic 存在且 enabled → status=running → 遍历各源 search()（单源失败 continue
    不阻塞）→ _upsert_item（url_hash 去重）→ 记 hit（Unique 去重）→ 三态状态更新。
    """
    db = SessionLocal()
    try:
        topic = db.get(AiTrendingTopic, topic_id)
        if not topic:
            logger.warning(f"AI 热点主题 {topic_id} 不存在，跳过扫描")
            return
        if not topic.enabled:
            logger.info(f"AI 热点主题 {topic_id} 已停用，跳过扫描")
            return

        topic.status = "running"
        db.commit()

        keywords = _parse_keywords(topic)
        new_hits = 0
        try:
            for source in registry.list():
                try:
                    items = source.search(keywords, SEARCH_PAGE_SIZE)
                except Exception as exc:  # noqa: BLE001  单源失败不阻塞整体
                    logger.warning(
                        f"主题 {topic_id} 源 {source.source_id} 检索失败，跳过: {exc}"
                    )
                    continue
                for raw in items or []:
                    item = _upsert_item(db, raw)
                    if item is None:
                        continue
                    # 先查快速路径（绝大多数已存在）；不存在用 INSERT OR IGNORE 原子插入，
                    # 避免 autoflush=False 下 pending hit 不可见导致的重复 add → UNIQUE 冲突
                    existing = (
                        db.query(AiTrendingTopicHit)
                        .filter(
                            AiTrendingTopicHit.topic_id == topic_id,
                            AiTrendingTopicHit.item_id == item.id,
                        )
                        .first()
                    )
                    if existing is None:
                        stmt = (
                            sqlite_insert(AiTrendingTopicHit)
                            .values(
                                topic_id=topic_id,
                                item_id=item.id,
                                matched=True,
                                first_seen_at=datetime.now(timezone.utc),
                            )
                            .on_conflict_do_nothing(
                                index_elements=["topic_id", "item_id"]
                            )
                        )
                        result = db.execute(stmt)
                        if result.rowcount and result.rowcount > 0:
                            new_hits += 1
            db.commit()
            topic.status = "idle"
            topic.last_run_at = datetime.now(timezone.utc)
            topic.last_item_count = new_hits
            topic.last_run_message = f"扫描完成，本次新增命中 {new_hits} 条"
            db.commit()
            logger.info(
                f"AI 热点主题 {topic_id}「{topic.name}」扫描完成，新增命中 {new_hits} 条"
            )
        except Exception as exc:  # noqa: BLE001  兜底：任何异常都标记 failed 并留痕
            logger.exception(f"AI 热点主题 {topic_id} 扫描失败")
            # 先 rollback 清掉失败事务（否则 commit 会抛 PendingRollbackError，
            # status=failed 永不落库 → 主题永久卡 running → run-now 一律 429 死锁）
            try:
                db.rollback()
            except Exception:  # noqa: BLE001  rollback 本身失败不掩盖原始异常
                pass
            topic.status = "failed"
            topic.last_run_at = datetime.now(timezone.utc)
            topic.last_run_message = str(exc)[:500]
            try:
                db.commit()
            except Exception:  # noqa: BLE001  写 failed 失败也回滚，避免残留失败事务
                db.rollback()
    finally:
        # 兜底：任何未提交/失败事务都回滚后再关会话，避免 PendingRollbackError 泄漏
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        db.close()


def _upsert_item(db: Session, raw: RawItem) -> AiTrendingItem | None:
    """复用 collector 的 url_hash 去重语义：不存在则插入，已存在且热度更高则覆盖。

    返回 ORM 对象（拿 id 记 hit）：热度不更高时也返回现有对象——该条目仍可被主题命中。
    """
    h = url_hash(raw.url)
    if not h:
        return None
    now = datetime.now(timezone.utc)
    existing = (
        db.query(AiTrendingItem)
        .filter(AiTrendingItem.url_hash == h)
        .first()
    )
    if existing is None:
        item = AiTrendingItem(
            source=(raw.source or "")[:32],
            title=(raw.title or "")[:512],
            url=(raw.url or "")[:1024],
            url_hash=h,
            summary=raw.summary or "",
            heat_score=raw.heat_score,
            category=raw.category or "news",
            tags=json.dumps(raw.tags, ensure_ascii=False),
            heat_meta=json.dumps(raw.heat_meta, ensure_ascii=False),
            published_at=raw.published_at or now,
            fetched_at=now,
            created_at=now,
        )
        db.add(item)
        db.flush()  # 立即拿 id 供 hit 引用
        return item
    if raw.heat_score > (existing.heat_score or 0):
        existing.source = (raw.source or "")[:32]
        existing.title = (raw.title or "")[:512]
        existing.url = (raw.url or "")[:1024]
        existing.summary = raw.summary or ""
        existing.heat_score = raw.heat_score
        existing.category = raw.category or "news"
        existing.tags = json.dumps(raw.tags, ensure_ascii=False)
        existing.heat_meta = json.dumps(raw.heat_meta, ensure_ascii=False)
        existing.published_at = raw.published_at or existing.published_at
        existing.fetched_at = now
        db.flush()
    return existing


def list_topic_items(
    db: Session,
    topic_id: int,
    sort: str = "heat",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """主题命中条目分页：join hits(matched=True) + items。

    sort=heat → items.heat_score DESC, items.id DESC；
    sort=time → hit.first_seen_at DESC, items.id DESC。
    """
    q = (
        db.query(AiTrendingTopicHit, AiTrendingItem)
        .join(AiTrendingItem, AiTrendingTopicHit.item_id == AiTrendingItem.id)
        .filter(
            AiTrendingTopicHit.topic_id == topic_id,
            AiTrendingTopicHit.matched.is_(True),
        )
    )
    if sort == "time":
        q = q.order_by(
            AiTrendingTopicHit.first_seen_at.desc(), AiTrendingItem.id.desc()
        )
    else:
        q = q.order_by(AiTrendingItem.heat_score.desc(), AiTrendingItem.id.desc())

    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    items = [TrendingItemOut.model_validate(item) for _, item in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


# ------------------------------------------------------------ 推送配置 ----
def get_push_config(db: Session, topic_id: int) -> dict | None:
    """读取主题内嵌推送配置；主题不存在返回 None。"""
    topic = db.get(AiTrendingTopic, topic_id)
    if not topic:
        return None
    return {
        "enabled": topic.push_enabled,
        "channel": topic.push_channel or "wecom",
        "frequency": topic.push_frequency or "daily",
        "time": topic.push_time or "09:00",
    }


def set_push_config(db: Session, topic_id: int, params: dict) -> dict | None:
    """保存主题推送配置：仅落库 topic 内嵌四字段 + commit（本次不注册推送 job，P1 接入）。"""
    topic = db.get(AiTrendingTopic, topic_id)
    if not topic:
        return None
    topic.push_enabled = bool(params.get("enabled", topic.push_enabled))
    topic.push_channel = params.get("channel") or topic.push_channel or "wecom"
    topic.push_frequency = params.get("frequency") or topic.push_frequency or "daily"
    topic.push_time = params.get("time") or topic.push_time or "09:00"
    topic.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(topic)
    logger.info(f"AI 热点主题 {topic_id} 推送配置已保存（仅落库，未触发发送）")
    return get_push_config(db, topic_id)


# ------------------------------------------------------------ job 联动 ----
def _sync_topic_job(topic: AiTrendingTopic) -> None:
    """创建/更新主题后同步 APScheduler job（懒加载避免循环 import）。"""
    from app.ai_trending.services.scheduler_jobs import (
        register_topic_job,
        unregister_topic_job,
    )

    if topic.enabled:
        register_topic_job(topic)
    else:
        unregister_topic_job(topic.id)


def _unregister_topic_job(topic_id: int) -> None:
    from app.ai_trending.services.scheduler_jobs import unregister_topic_job

    unregister_topic_job(topic_id)


# ------------------------------------------------------------ run-now 限频 ----
def check_run_now_cooldown(topic_id: int) -> tuple[bool, str]:
    """run-now 每主题 60s 内存限频：通过返回 (True, '')，未过冷却返回 (False, 提示)。

    与 controllers/topic.py 共用同一张时间戳表，确保两端口径一致。
    """
    now = datetime.now(timezone.utc).timestamp()
    with _RUN_NOW_LOCK:
        last = _last_run_now.get(topic_id)
        if last is not None:
            remaining = RUN_NOW_COOLDOWN_SECONDS - (now - last)
            if remaining > 0:
                return False, f"抓取过于频繁，请 {int(remaining) + 1} 秒后重试"
        _last_run_now[topic_id] = now
    return True, ""
