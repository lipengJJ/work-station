from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class WatchlistStock(Base):
    """自选股代码列表 + 行情快照缓存：Finnhub/yfinance 都只是行情数据源，没有 moomoo
    那种账号自选股分组，所以自己存一张表记录选了哪些代码。

    行情字段（price/change/name 等）缓存在这张表里，updated_at 记录最后一次真的向
    yfinance 拉取的时间——不是每次打开自选股页面都重新请求一遍 Yahoo Finance，只有缓存
    过期（见 watchlist_client.py 的 _QUOTE_TTL_SECONDS）才会真的发请求，刷新完顺便更新
    这些字段。缓存字段允许为空：symbol 刚加进来、还没来得及拉到过行情时就是这个状态。
    """

    __tablename__ = "watchlist_stocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(120), nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    change: Mapped[float | None] = mapped_column(Float, nullable=True)
    change_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    change_1w: Mapped[float | None] = mapped_column(Float, nullable=True)
    change_1m: Mapped[float | None] = mapped_column(Float, nullable=True)
    day_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    day_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    quote_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
