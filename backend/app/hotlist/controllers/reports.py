"""主题报告：/api/hotlist/topics/{id}/reports + /api/hotlist/reports/*（全部需要登录）。

- GET  /topics/{id}/reports               历史报告分页
- POST /topics/{id}/reports/generate      手动生成（异步 + 限频）
- GET  /reports/{report_id}               详情（正文 + 条目快照 + 引用覆盖率）
- GET  /reports/{report_id}/candidates    未入选条目（漏检抽查，随机抽 20 条）
- POST /reports/{report_id}/publish       重新发布（发布失败不影响报告）
- POST /reports/{report_id}/notify        重新推送
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import random
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.core.deps import get_current_user
from app.hotlist.models import HotItem, HotSource, HotTopic, HotTopicReport
from app.hotlist.schemas.report import (
    CandidateOut,
    GenerateIn,
    ReportDetailOut,
    ReportItemRefOut,
    ReportOut,
    ReportPage,
)
from app.hotlist.services import (
    publish_service,
    topic_report_service,
    topic_service,
)

router = APIRouter(prefix="/api/hotlist", tags=["hotlist-reports"])

# 手动生成限频：进程内内存锁 + 时间戳（5 分钟 1 次；单进程部署成立）
_GENERATE_LOCK = threading.Lock()
_last_manual_generate: float | None = None
GENERATE_COOLDOWN_SECONDS = 300

CANDIDATES_SAMPLE = 20  # 漏检抽查随机抽 20 条


def _get_report(db: Session, report_id: int) -> HotTopicReport:
    report = db.get(HotTopicReport, report_id)
    if report is None:
        raise HTTPException(404, "报告不存在")
    return report


# ------------------------------------------------------------ 历史 ----

@router.get("/topics/{topic_id}/reports")
def list_reports(
    topic_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> ReportPage:
    if topic_service.get_topic(db, topic_id) is None:
        raise HTTPException(404, "主题不存在")
    q = (
        db.query(HotTopicReport)
        .filter(HotTopicReport.topic_id == topic_id)
        .order_by(HotTopicReport.period_end.desc(), HotTopicReport.id.desc())
    )
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    return ReportPage(
        reports=[ReportOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/topics/{topic_id}/reports/generate")
def generate(
    topic_id: int,
    data: GenerateIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> dict:
    """手动生成：5 分钟限频，daemon 线程异步执行，立即返回。"""
    if topic_service.get_topic(db, topic_id) is None:
        raise HTTPException(404, "主题不存在")

    global _last_manual_generate
    now = time.time()
    with _GENERATE_LOCK:
        if _last_manual_generate is not None:
            remaining = GENERATE_COOLDOWN_SECONDS - (
                now - _last_manual_generate
            )
            if remaining > 0:
                raise HTTPException(429, f"生成过于频繁，请 {int(remaining) + 1} 秒后重试")
        _last_manual_generate = now

    period_key = (data.period_key or "").strip()
    strategy = (data.strategy or "").strip()

    def _worker() -> None:
        dbw = SessionLocal()
        try:
            report = topic_report_service.generate_report(
                dbw,
                topic_id,
                period_key=period_key,
                strategy=strategy,
                max_items=data.max_items,
            )
            # 生成成功 → 发布（若主题配置了）+ 通知（若主题配置了）
            if report.status == "success":
                topic = dbw.get(HotTopic, topic_id)
                if topic and topic.publish_enabled:
                    result = publish_service.publish_report(dbw, report)
                    if result["status"] == "success":
                        report.publish_status = "success"
                        report.publish_urls = json.dumps(
                            result["urls"], ensure_ascii=False
                        )
                        report.published_at = datetime.now(timezone.utc)
                    else:
                        report.publish_status = "failed"
                        report.error = result.get("error", "")[:500]
                    dbw.commit()
                if topic and topic.report_notify_enabled:
                    topic_report_service.notify_report(dbw, report)
        except ValueError as exc:
            # 生成失败（如未配 AI Key / 无候选条目）也落一条 failed 报告，
            # 前端报告历史里能看到失败原因，而不是「点了没反应」
            logger.warning(f"手动生成报告失败（topic {topic_id}）: {exc}")
            _record_generation_failure(
                dbw, topic_id, period_key, strategy, str(exc)
            )
        except Exception:  # noqa: BLE001  后台线程兜底
            logger.exception(f"手动生成报告异常（topic {topic_id}）")
            _record_generation_failure(
                dbw, topic_id, period_key, strategy, "内部错误，详见后端日志"
            )
        finally:
            dbw.close()

    threading.Thread(target=_worker, daemon=True).start()
    return {"triggered": True, "message": "已开始生成报告（异步执行，可在报告历史中查看进度）"}


def _record_generation_failure(
    db: Session, topic_id: int, period_key: str, strategy: str, error: str
) -> None:
    """落一条 failed 报告行（唯一约束按 (topic_id, period_key) 覆盖）。"""
    topic = topic_service.get_topic(db, topic_id)
    if topic is None:
        return
    try:
        key, start, end = topic_report_service.compute_period(
            topic, period_key
        )
    except Exception:  # noqa: BLE001
        key, start, end = period_key or "", None, None
    db.query(HotTopicReport).filter(
        HotTopicReport.topic_id == topic_id, HotTopicReport.period_key == key
    ).delete()
    db.add(
        HotTopicReport(
            topic_id=topic_id,
            period_key=key,
            period_start=start,
            period_end=end,
            status="failed",
            strategy=strategy or topic.digest_strategy,
            skill_key=topic.skill_key or "",
            template_key=topic.template_key,
            model="",
            error=error[:500],
        )
    )
    db.commit()


# ------------------------------------------------------------ 详情 ----

@router.get("/reports/{report_id}")
def report_detail(
    report_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)
) -> ReportDetailOut:
    report = _get_report(db, report_id)
    topic = topic_service.get_topic(db, report.topic_id)

    detail = ReportDetailOut.model_validate(report)
    detail.topic_name = topic.name if topic else ""
    detail.topic_slug = topic.slug if topic else ""

    # 引用条目明细（hot_items 现查；被清理任务删掉的条目跳过）
    item_ids = []
    try:
        item_ids = json.loads(report.item_ids or "[]")
    except (ValueError, TypeError):
        pass
    if item_ids:
        rows = db.query(HotItem).filter(HotItem.id.in_(item_ids)).all()
        sources = {s.id: s.name for s in db.query(HotSource).all()}
        detail.items = [
            ReportItemRefOut(
                id=r.id,
                title=r.title,
                url=r.url,
                source_id=r.source_id,
                source_name=sources.get(r.source_id, r.source_id),
                weight=r.weight,
                published_at=r.published_at,
            )
            for r in rows
        ]
    # 引用覆盖率 = 引用数 / 候选数
    candidate_ids = []
    try:
        candidate_ids = json.loads(report.candidate_ids or "[]")
    except (ValueError, TypeError):
        pass
    detail.coverage = (
        round(len(item_ids) / len(candidate_ids), 4) if candidate_ids else 0.0
    )
    # 上一期引用 id（前端标「新出现/持续/已消退」）
    prev = topic_report_service._previous_report(
        db, report.topic_id, report.period_key, exclude_id=report.id
    )
    if prev is not None:
        detail.prev_item_ids = topic_report_service._prev_item_ids(prev)
    return detail


@router.get("/reports/{report_id}/candidates")
def report_candidates(
    report_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)
) -> dict:
    """漏检抽查：从本期进入分析但未被引用的条目里随机抽 CANDIDATES_SAMPLE 条。"""
    report = _get_report(db, report_id)
    candidate_ids = []
    try:
        candidate_ids = json.loads(report.candidate_ids or "[]")
    except (ValueError, TypeError):
        pass
    item_ids = set()
    try:
        item_ids = set(json.loads(report.item_ids or "[]"))
    except (ValueError, TypeError):
        pass

    not_referenced = [cid for cid in candidate_ids if cid not in item_ids]
    random.shuffle(not_referenced)
    sample_ids = not_referenced[:CANDIDATES_SAMPLE]

    sources = {s.id: s.name for s in db.query(HotSource).all()}
    rows = (
        db.query(HotItem).filter(HotItem.id.in_(sample_ids)).all()
        if sample_ids
        else []
    )
    items = [
        CandidateOut(
            id=r.id,
            title=r.title,
            url=r.url,
            source_id=r.source_id,
            source_name=sources.get(r.source_id, r.source_id),
            weight=r.weight,
            published_at=r.published_at,
        )
        for r in rows
    ]
    return {
        "total_unreferenced": len(not_referenced),
        "sampled": len(items),
        "items": items,
    }


# ------------------------------------------------------------ 发布 / 通知 ----

@router.post("/reports/{report_id}/publish")
def publish(
    report_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)
) -> dict:
    report = _get_report(db, report_id)
    if report.status != "success":
        raise HTTPException(400, "报告未生成成功，无法发布")
    result = publish_service.publish_report(db, report)
    if result["status"] == "success":
        from datetime import datetime, timezone

        report.publish_status = "success"
        report.publish_urls = json.dumps(result["urls"], ensure_ascii=False)
        report.published_at = datetime.now(timezone.utc)
        report.error = ""
        db.commit()
        return {"ok": True, "urls": result["urls"]}
    report.publish_status = "failed"
    report.error = result.get("error", "")[:500]
    db.commit()
    return {"ok": False, "error": result.get("error", "")}


@router.post("/reports/{report_id}/notify")
def notify(
    report_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)
) -> dict:
    report = _get_report(db, report_id)
    if report.status != "success":
        raise HTTPException(400, "报告未生成成功，无法推送")
    result = topic_report_service.notify_report(db, report)
    if result.get("skipped"):
        return {"ok": False, "message": "主题未启用通知 / 未配置渠道 / 当前在静默时段"}
    return {"ok": True, "message": f"已推送 {result.get('sent', 0)} 个渠道"}
