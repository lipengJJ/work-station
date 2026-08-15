"""Hugging Face 源：一个类两种 mode，注册为 hf_models / hf_papers 两个源。

- models：https://huggingface.co/api/models?sort=trendingScore&direction=-1&limit=50
  （id / likes / downloads / trendingScore），category=model
  search() 覆写为 /api/models?search=kw 真检索（仅 models mode）；
- papers：https://huggingface.co/api/daily_papers（paper.id 拼 arXiv 链接），category=paper
  （daily_papers 无检索接口，search() 继承基类降级 = fetch 全量 + 关键词过滤）
"""
from __future__ import annotations

from urllib.parse import quote_plus

from loguru import logger

from app.ai_trending.services.base import (
    RawItem,
    TrendingSource,
    TrendingSourceError,
    hf_models_heat,
    paper_heat,
    parse_datetime,
)


class HuggingFaceSource(TrendingSource):
    """Hugging Face 模型榜 / 每日论文，按 mode 区分 source_id / 展示名 / 抓取逻辑。"""

    source_id = "hf_models"
    source_name = "HF 模型榜"
    category_type = "model"
    filter_keywords: list[str] | None = None

    MODELS_URL = (
        "https://huggingface.co/api/models?sort=trendingScore&direction=-1&limit=50"
    )
    SEARCH_MODELS_URL = "https://huggingface.co/api/models"
    PAPERS_URL = "https://huggingface.co/api/daily_papers"

    def __init__(self, mode: str = "models") -> None:
        self.mode = mode
        if mode == "papers":
            self.source_id = "hf_papers"
            self.source_name = "HF 每日论文"
            self.category_type = "paper"
        else:
            self.source_id = "hf_models"
            self.source_name = "HF 模型榜"
            self.category_type = "model"

    def fetch(self) -> list[RawItem]:
        if self.mode == "papers":
            return self._fetch_papers()
        return self._fetch_models()

    def search(self, keywords: list[str], page_size: int = 30) -> list[RawItem]:
        """models mode 覆写为 /api/models?search=kw 真检索；papers mode 继承基类降级。"""
        if self.mode != "models":
            return super().search(keywords, page_size=page_size)
        items: list[RawItem] = []
        for kw in keywords or []:
            kw = str(kw).strip()
            if not kw:
                continue
            url = (
                f"{self.SEARCH_MODELS_URL}?search={quote_plus(kw)}"
                "&sort=trendingScore&direction=-1"
                f"&limit={page_size}"
            )
            try:
                data = self._http_get_json(url)
            except TrendingSourceError as exc:
                logger.warning(f"hf search 关键词「{kw}」请求失败: {exc}")
                continue
            items.extend(self._parse_models(data or []))
        return items

    # ------------------------------------------------------------ models ----
    def _fetch_models(self) -> list[RawItem]:
        data = self._http_get_json(self.MODELS_URL)
        return self._parse_models(data or [])

    def _parse_models(self, models: list[dict]) -> list[RawItem]:
        """HF models API 列表 → RawItem 列表（fetch / search 共用）。"""
        items: list[RawItem] = []
        for model in models or []:
            model_id = model.get("id") or ""
            if not model_id:
                continue
            trending_score = float(model.get("trendingScore") or 0)
            likes = int(model.get("likes") or 0)
            downloads = int(model.get("downloads") or 0)
            published_at = parse_datetime(model.get("lastModified"))
            heat = hf_models_heat(trending_score, published_at)
            tags: list[str] = []
            pipeline_tag = model.get("pipeline_tag")
            if pipeline_tag:
                tags.append(pipeline_tag)
            description = (model.get("description") or "").strip() or f"HF 模型 {model_id}"
            items.append(
                RawItem(
                    source=self.source_id,
                    title=model_id,
                    url=f"https://huggingface.co/{model_id}",
                    summary=description,
                    category=self.category_type,
                    tags=tags,
                    published_at=published_at,
                    heat_score=heat,
                    heat_meta={
                        "trendingScore": trending_score,
                        "likes": likes,
                        "downloads": downloads,
                    },
                )
            )
        return items

    # ------------------------------------------------------------ papers ----
    def _fetch_papers(self) -> list[RawItem]:
        data = self._http_get_json(self.PAPERS_URL)
        items: list[RawItem] = []
        for entry in data or []:
            if not isinstance(entry, dict):
                continue
            paper = entry.get("paper") if isinstance(entry.get("paper"), dict) else entry
            paper_id = paper.get("id") or ""
            title = (paper.get("title") or "").strip()
            if not paper_id or not title:
                continue
            url = paper.get("url") or f"https://arxiv.org/abs/{paper_id}"
            summary = (paper.get("summary") or "").strip()
            published_at = parse_datetime(paper.get("publishedAt"))
            heat = paper_heat(published_at)
            tags = [str(t) for t in (paper.get("tags") or []) if t][:5]
            items.append(
                RawItem(
                    source=self.source_id,
                    title=title,
                    url=url,
                    summary=summary,
                    category=self.category_type,
                    tags=tags,
                    published_at=published_at,
                    heat_score=heat,
                    heat_meta={"hf_paper_id": paper_id},
                )
            )
        return items
