from __future__ import annotations

from pydantic import BaseModel


class FundamentalsEnvelope(BaseModel):
    """统一响应结构：data 具体形状因 dataset 而异（财务序列、估值区间、SEC文件列表……），
    结构还在演进，这里不逐字段强类型化，但外层信封（来源/部分失败/更新时间/是否命中缓存）
    对所有 dataset 都一致，前端可以用同一套状态处理逻辑对待任何一个 tab。"""

    data: dict
    sources: list[str]
    partial_failures: list[str]
    fetched_at: str
    from_cache: bool


class SearchResult(BaseModel):
    symbol: str
    cik: int | None = None
    cik_str: str | None = None
    title: str


class RefreshRequest(BaseModel):
    dataset: str | None = None  # 不传就清空这支股票的全部 dataset 缓存
