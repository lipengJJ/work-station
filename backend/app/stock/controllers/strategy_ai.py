"""
策略驱动的 AI 个股分析 —— 路由层。

- 策略库 CRUD（内置预设首次访问时幂等 seed）
- POST /analyze：SSE 流式分析（选策略 + 选股票 → AI 按策略框架输出 markdown 报告 +
  末尾 JSON 分级结论）。流结束另开 SessionLocal 落库（沿用 xhs controller 的模式：
  SSE 生成器实际执行晚于 FastAPI 依赖的 yield 退出点，请求的 db session 可能已关闭）。
- 报告历史：分页列表 / 详情 / 删除
"""
from __future__ import annotations

import json
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.common.services.ai_config import get_ai_credentials
from app.common.services.ai_gateway import service as ai_gateway_service
from app.common.services.ai_gateway.base import EVENT_DELTA, EVENT_ERROR, AIRequest
from app.core.database import SessionLocal, get_db
from app.core.deps import get_current_user
from app.stock.models.stock_strategy_report import StockStrategyReport
from app.stock.schemas.strategy_ai import AnalyzeIn, StrategyIn
from app.stock.services import strategy_analysis_service, strategy_service

router = APIRouter(prefix="/api/stock/strategy-ai", tags=["stock-strategy-ai"])

_RATING_LABEL = {"buy": "买入", "hold": "观望", "avoid": "回避"}


# -------------------------------------------------------------------- 策略库 CRUD ----

@router.get("/strategies")
def list_strategies(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return strategy_service.list_strategies(db)


@router.post("/strategies")
def create_strategy(body: StrategyIn, db: Session = Depends(get_db), _=Depends(get_current_user)):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "策略名称不能为空")
    return strategy_service.create_strategy(db, name, body.description.strip(), body.rules)


@router.put("/strategies/{strategy_id}")
def update_strategy(strategy_id: int, body: StrategyIn, db: Session = Depends(get_db), _=Depends(get_current_user)):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "策略名称不能为空")
    row = strategy_service.update_strategy(db, strategy_id, name, body.description.strip(), body.rules)
    if not row:
        raise HTTPException(404, "策略不存在")
    return strategy_service._to_dict(row)


@router.delete("/strategies/{strategy_id}")
def delete_strategy(strategy_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    ok, reason = strategy_service.delete_strategy(db, strategy_id)
    if not ok:
        raise HTTPException(400, reason)
    return {"success": True}


# ------------------------------------------------------------------- 策略分析（SSE）----

def _report_to_dict(r: StockStrategyReport, with_body: bool = False) -> dict:
    d = {
        "id": r.id,
        "symbol": r.symbol,
        "strategy_id": r.strategy_id,
        "strategy_name": (json.loads(r.strategy_snapshot_json or "{}")).get("name", ""),
        "rating": r.rating,
        "rating_label": _RATING_LABEL.get(r.rating, ""),
        "rating_reason": r.rating_reason,
        "key_indicators": json.loads(r.key_indicators_json or "[]"),
        "provider": r.provider,
        "model": r.model,
        "status": r.status,
        "error_message": r.error_message,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    }
    if with_body:
        d["report_markdown"] = r.report_markdown
    return d


@router.post("/analyze")
def run_analysis(
    body: AnalyzeIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    symbol = body.symbol.strip().upper()
    if not symbol:
        raise HTTPException(400, "股票代码不能为空")

    strategy = strategy_service.get_strategy(db, body.strategy_id)
    if not strategy:
        raise HTTPException(404, "策略不存在")

    provider, api_key, model, thinking_enabled = get_ai_credentials(db)
    if not api_key:
        raise HTTPException(400, "尚未配置 AI 模型 API Key，请先在系统设置 → API 配置里配置")

    # context 组装走 cache-first，同步阶段执行（此时请求的 db session 还活着）
    built = strategy_analysis_service.build_strategy_context(db, symbol)
    if not built["context"]:
        raise HTTPException(
            400, f"无法获取 {symbol} 的分析数据：{'；'.join(built['errors'][:3]) or '未知错误'}"
        )

    system_instruction = strategy_analysis_service.build_system_instruction(strategy, symbol)
    user_content = json.dumps(built["context"], ensure_ascii=False, indent=2)
    request_id = uuid4().hex
    ai_request = AIRequest(
        provider=provider,
        model=model,
        system_instruction=system_instruction,
        messages=[{"role": "user", "content": user_content}],
        thinking_enabled=thinking_enabled,
        request_id=request_id,
    )

    strategy_snapshot = {
        "id": strategy.id,
        "name": strategy.name,
        "description": strategy.description,
        "rules": json.loads(strategy.rules_json or "{}"),
    }

    def event_stream():
        full_text = ""
        error_message: Optional[str] = None

        for event in ai_gateway_service.stream(ai_request, api_key):
            etype = event["type"]
            if etype == EVENT_DELTA:
                full_text += event["text"]
                yield f"data: {json.dumps({'delta': event['text']}, ensure_ascii=False)}\n\n"
            elif etype == EVENT_ERROR:
                error_message = event["message"]
                yield f"data: {json.dumps({'error': event['message']}, ensure_ascii=False)}\n\n"

        save_db = SessionLocal()
        try:
            if error_message:
                save_db.add(
                    StockStrategyReport(
                        symbol=symbol,
                        strategy_id=strategy.id,
                        strategy_snapshot_json=json.dumps(strategy_snapshot, ensure_ascii=False),
                        status="failed",
                        error_message=error_message,
                        provider=provider,
                        model=model,
                    )
                )
                save_db.commit()
                return

            rating = strategy_analysis_service.extract_rating_block(full_text)
            if not rating:
                rating = strategy_analysis_service.extract_rating_fallback(
                    save_db, system_instruction, user_content
                )

            report = StockStrategyReport(
                symbol=symbol,
                strategy_id=strategy.id,
                strategy_snapshot_json=json.dumps(strategy_snapshot, ensure_ascii=False),
                context_snapshot_json=json.dumps(built["context"], ensure_ascii=False),
                report_markdown=full_text.strip(),
                rating=rating.get("rating", "") if rating else "",
                rating_reason=rating.get("reason", "") if rating else "",
                key_indicators_json=json.dumps(
                    rating.get("key_indicators", []), ensure_ascii=False
                ) if rating else "[]",
                provider=provider,
                model=model,
                status="completed",
            )
            save_db.add(report)
            save_db.commit()
            save_db.refresh(report)
            report_id = report.id
        except Exception as e:  # 落库失败不能让前端卡在"已出文但无记录"
            save_db.rollback()
            report_id = None
            yield f"data: {json.dumps({'error': f'报告保存失败：{e}'}, ensure_ascii=False)}\n\n"
        finally:
            save_db.close()

        if report_id is not None:
            rating_payload = {
                "rating": {
                    "label": _RATING_LABEL.get(rating.get("rating", ""), "") if rating else "",
                    "reason": rating.get("reason", "") if rating else "",
                    "key_indicators": rating.get("key_indicators", []) if rating else [],
                }
            }
            yield f"data: {json.dumps(rating_payload, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# -------------------------------------------------------------------- 报告历史 ----

@router.get("/reports")
def list_reports(
    symbol: Optional[str] = None,
    strategy_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    query = db.query(StockStrategyReport)
    if symbol:
        query = query.filter(StockStrategyReport.symbol == symbol.strip().upper())
    if strategy_id:
        query = query.filter(StockStrategyReport.strategy_id == strategy_id)
    total = query.count()
    rows = (
        query.order_by(StockStrategyReport.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "items": [_report_to_dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/reports/{report_id}")
def get_report(report_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    report = db.get(StockStrategyReport, report_id)
    if not report:
        raise HTTPException(404, "报告不存在")
    return _report_to_dict(report, with_body=True)


@router.delete("/reports/{report_id}")
def delete_report(report_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    report = db.get(StockStrategyReport, report_id)
    if not report:
        raise HTTPException(404, "报告不存在")
    db.delete(report)
    db.commit()
    return {"success": True}
