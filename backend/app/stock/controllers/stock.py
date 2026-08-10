from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.database import get_db
from app.stock.schemas.stock import WatchlistSymbolIn
from app.stock.services import kline_client, watchlist_client

router = APIRouter(prefix="/api/stock", tags=["stock"])


@router.get("/watchlist")
def get_watchlist(db: Session = Depends(get_db), _=Depends(get_current_user)):
    try:
        return watchlist_client.list_watchlist_stocks(db)
    except watchlist_client.WatchlistError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/watchlist")
def add_to_watchlist(body: WatchlistSymbolIn, db: Session = Depends(get_db), _=Depends(get_current_user)):
    try:
        watchlist_client.add_watchlist_symbol(db, body.symbol)
        db.commit()
        return watchlist_client.list_watchlist_stocks(db)
    except watchlist_client.WatchlistError as e:
        raise HTTPException(400, str(e)) from e


@router.delete("/watchlist/{symbol}")
def remove_from_watchlist(symbol: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    watchlist_client.remove_watchlist_symbol(db, symbol)
    db.commit()
    try:
        return watchlist_client.list_watchlist_stocks(db)
    except watchlist_client.WatchlistError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/kline/{symbol}")
def get_kline(symbol: str, interval: Literal["1d", "1wk", "1mo"] = "1d", db: Session = Depends(get_db), _=Depends(get_current_user)):
    try:
        return kline_client.get_kline(db, symbol, interval)
    except kline_client.KlineError as e:
        raise HTTPException(400, str(e)) from e
