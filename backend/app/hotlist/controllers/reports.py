"""主题报告：/api/hotlist/topics/{id}/reports + /api/hotlist/reports/*（全部需要登录）。

- GET  /topics/{id}/reports               历史报告分页
- POST /topics/{id}/reports/generate      手动生成（异步 + 限频）
- GET  /reports/{report_id}               详情（正文 + 条目快照 + 引用覆盖率）
- GET  /reports/{report_id}/candidates    未入选条目（漏检抽查，随机抽 20 条）
- POST /reports/{report_id}/publish       重新发布（发布失败不影响报告）
- POST /reports/{report_id}/notify        重新推送
"""
from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlalchemy.orm import Session

from app.common.utils.rate_limiter import RateLimiter
from app.core.database import SessionLocal, get_db
from app.core.deps import get_current_user
from app.hotlist.models import HotTopic, HotTopicReport
from app.hotlist.schemas.report import (
    GenerateIn,
    ReportDetailOut,
    ReportPage,
)
from app.hotlist.services import (
    publish_service,
    topic_report_service,
    topic_service,
)

router = APIRouter(prefix="/api/hotlist", tags=["hotlist-reports"])

# 手动生成限频：5 分钟 1 次（单进程部署成立；见 common/utils/rate_limiter.py）
_generate_limiter = RateLimiter(cooldown_seconds=300)


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
    return topic_report_service.list_reports(db, topic_id, page, page_size)


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

    remaining = _generate_limiter.check_and_mark()
    if remaining > 0:
        raise HTTPException(429, f"生成过于频繁，请 {int(remaining) + 1} 秒后重试")

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
                    publish_service.apply_publish_result(dbw, report, result)
                if topic and topic.report_notify_enabled:
                    topic_report_service.notify_report(dbw, report)
        except ValueError as exc:
            # 生成失败（如未配 AI Key / 无候选条目）也落一条 failed 报告，
            # 前端报告历史里能看到失败原因，而不是「点了没反应」
            logger.warning(f"手动生成报告失败（topic {topic_id}）: {exc}")
            topic_report_service.record_generation_failure(
                dbw, topic_id, period_key, strategy, str(exc)
            )
        except Exception:  # noqa: BLE001  后台线程兜底
            logger.exception(f"手动生成报告异常（topic {topic_id}）")
            topic_report_service.record_generation_failure(
                dbw, topic_id, period_key, strategy, "内部错误，详见后端日志"
            )
        finally:
            dbw.close()

    threading.Thread(target=_worker, daemon=True).start()
    return {"triggered": True, "message": "已开始生成报告（异步执行，可在报告历史中查看进度）"}


# ------------------------------------------------------------ 详情 ----

@router.get("/reports/{report_id}")
def report_detail(
    report_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)
) -> ReportDetailOut:
    detail = topic_report_service.get_report_detail(db, report_id)
    if detail is None:
        raise HTTPException(404, "报告不存在")
    return detail


@router.get("/reports/{report_id}/candidates")
def report_candidates(
    report_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)
) -> dict:
    """漏检抽查：从本期进入分析但未被引用的条目里随机抽 CANDIDATES_SAMPLE 条。"""
    result = topic_report_service.get_report_candidates(db, report_id)
    if result is None:
        raise HTTPException(404, "报告不存在")
    return result


# ------------------------------------------------------------ 发布 / 通知 ----

@router.post("/reports/{report_id}/publish")
def publish(
    report_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)
) -> dict:
    report = _get_report(db, report_id)
    if report.status != "success":
        raise HTTPException(400, "报告未生成成功，无法发布")
    result = publish_service.publish_report(db, report)
    publish_service.apply_publish_result(db, report, result)
    if result["status"] == "success":
        return {"ok": True, "urls": result["urls"]}
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
