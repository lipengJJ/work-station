"""Hugging Face 源：一个类两种 mode，注册为 hf_models / hf_papers 两个源。

- models：https://huggingface.co/api/models?sort=trendingScore&direction=-1&limit=50
  （id / likes / downloads / trendingScore），category=model
- papers：https://huggingface.co/api/daily_papers（paper.id 拼 arXiv 链接），category=paper
"""
from __future__ import annotations

from app.ai_trending.services.base import (
    RawItem,
    TrendingSource,
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

    # ------------------------------------------------------------ models ----
    def _fetch_models(self) -> list[RawItem]:
        data = self._http_get_json(self.MODELS_URL)
        items: list[RawItem] = []
        for model in data or []:
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
