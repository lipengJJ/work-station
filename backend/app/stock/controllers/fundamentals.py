from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.database import get_db
from app.stock.services import ai_analysis_service, orchestrator
from app.stock.services.orchestrator import FundamentalsNotFound
from app.stock.schemas.fundamentals import FundamentalsEnvelope, RefreshRequest, SearchResult

router = APIRouter(prefix="/api/stock/fundamentals", tags=["fundamentals"])


def _handle(build_fn, *args, **kwargs) -> dict:
    try:
        return build_fn(*args, **kwargs)
    except FundamentalsNotFound as e:
        raise HTTPException(404, str(e)) from e


@router.get("/search", response_model=list[SearchResult])
def search(q: str = Query(..., min_length=1), db: Session = Depends(get_db), _=Depends(get_current_user)):
    return orchestrator.search(db, q)


@router.get("/{symbol}/overview", response_model=FundamentalsEnvelope)
def get_overview(symbol: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _handle(orchestrator.build_overview, db, symbol.strip().upper())


@router.get("/{symbol}/financials", response_model=FundamentalsEnvelope)
def get_financials(symbol: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _handle(orchestrator.build_financials, db, symbol.strip().upper())


@router.get("/{symbol}/valuation", response_model=FundamentalsEnvelope)
def get_valuation(symbol: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _handle(orchestrator.build_valuation, db, symbol.strip().upper())


@router.get("/{symbol}/earnings", response_model=FundamentalsEnvelope)
def get_earnings(symbol: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _handle(orchestrator.build_earnings, db, symbol.strip().upper())


@router.get("/{symbol}/filings", response_model=FundamentalsEnvelope)
def get_filings(symbol: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _handle(orchestrator.build_filings, db, symbol.strip().upper())


@router.get("/{symbol}/institutions", response_model=FundamentalsEnvelope)
def get_institutions(symbol: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _handle(orchestrator.build_institutions, db, symbol.strip().upper())


@router.get("/{symbol}/insiders", response_model=FundamentalsEnvelope)
def get_insiders(symbol: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _handle(orchestrator.build_insiders, db, symbol.strip().upper())


@router.get("/{symbol}/risks", response_model=FundamentalsEnvelope)
def get_risks(symbol: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _handle(orchestrator.build_risks, db, symbol.strip().upper())


@router.get("/{symbol}/ai-analysis", response_model=FundamentalsEnvelope | None)
def get_cached_ai_analysis(symbol: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """只读缓存里已经生成过的结果，不触发新的 Gemini 调用——前端切换 tab 再切回来时
    用这个先看看有没有现成的，用户主动点"生成/重新生成"才走下面那个会花钱的 POST。"""
    return orchestrator.get_cached_ai_analysis(db, symbol.strip().upper())


@router.post("/{symbol}/ai-analysis", response_model=FundamentalsEnvelope)
def post_ai_analysis(symbol: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    symbol = symbol.strip().upper()
    try:
        return orchestrator.build_ai_analysis(db, symbol)
    except FundamentalsNotFound as e:
        raise HTTPException(404, str(e)) from e
    except ai_analysis_service.AiAnalysisError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/{symbol}/refresh")
def post_refresh(symbol: str, body: RefreshRequest, db: Session = Depends(get_db), _=Depends(get_current_user)):
    orchestrator.refresh(db, symbol.strip().upper(), body.dataset)
    return {"success": True}
