from pydantic import BaseModel, Field


class WatchlistSymbolIn(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
