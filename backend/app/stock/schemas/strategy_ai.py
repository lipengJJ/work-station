from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class StrategyIn(BaseModel):
    """策略的创建/编辑入参。rules 是结构化策略规则（关注因子/风险偏好/买入倾向等），
    渲染进 AI Prompt；结构灵活，不强约束字段。"""

    name: str = Field(min_length=1, max_length=64)
    description: str = ""
    rules: dict = Field(default_factory=dict)


class AnalyzeIn(BaseModel):
    """发起一次策略分析：选股票 + 选策略。"""

    symbol: str = Field(min_length=1, max_length=20)
    strategy_id: int


class ReportQuery(BaseModel):
    symbol: Optional[str] = None
    strategy_id: Optional[int] = None
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)
