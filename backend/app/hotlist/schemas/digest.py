"""热点摘要请求/响应模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.hotlist.schemas.item import ItemOut


class DigestGroupOut(BaseModel):
    rule_id: int | None = None
    display_name: str = ""
    items: list[ItemOut] = Field(default_factory=list)


class DigestOut(BaseModel):
    mode: str
    stat_date: str
    total_items: int = 0
    groups: list[DigestGroupOut] = Field(default_factory=list)
