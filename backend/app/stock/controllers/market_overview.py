from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.stock.services import market_overview_service

router = APIRouter(prefix="/api/stock/market-overview", tags=["market-overview"])


@router.get("/indices")
def get_indices(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return market_overview_service.get_index_quotes(db)


@router.get("/indices/{symbol}/history")
def get_index_history(
    symbol: str,
    period: Literal["1M", "3M", "6M", "YTD", "1Y"] = "6M",
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    try:
        return market_overview_service.get_index_history(db, symbol, period)
    except market_overview_service.MarketOverviewError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/mag7-earnings")
def get_mag7_earnings(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return market_overview_service.get_mag7_earnings(db)


@router.get("/events")
def get_events(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return market_overview_service.get_upcoming_events(db)
