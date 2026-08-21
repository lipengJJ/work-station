"""Hugging Face adapter：models + papers 两种 mode，靠 adapter_params['mode'] 区分。

重写自旧 ai_trending services/sources/hf.py，改动：
  - 删除 hf_models_heat / paper_heat；rank 按接口原始返回顺序 enumerate；
  - 只保留 fetch（search 检索能力由 Phase 3 频率词规则取代）。
"""
from __future__ import annotations

from app.common.utils.text import parse_datetime
from app.hotlist.services.adapters.base import (
    HotSourceAdapter,
    RawEntry,
    register,
)

MODELS_URL = (
    "https://huggingface.co/api/models?sort=trendingScore"
    "&direction=-1&limit=50"
)
PAPERS_URL = "https://huggingface.co/api/daily_papers"


class HuggingFaceAdapter(HotSourceAdapter):
    adapter_key = "huggingface"

    def fetch(self, params: dict) -> list[RawEntry]:
        mode = params.get("mode", "models")
        if mode == "papers":
            return self._fetch_papers()
        return self._fetch_models()

    def _fetch_models(self) -> list[RawEntry]:
        data = self._get_json(MODELS_URL, timeout=20)
        entries: list[RawEntry] = []
        for idx, model in enumerate(data or [], 1):
            model_id = model.get("id") or ""
            if not model_id:
                continue
            trending_score = float(model.get("trendingScore") or 0)
            likes = int(model.get("likes") or 0)
            downloads = int(model.get("downloads") or 0)
            description = (
                (model.get("description") or "").strip()
                or f"HF 模型 {model_id}"
            )
            entries.append(
                RawEntry(
                    rank=idx,
                    title=model_id,
                    url=f"https://huggingface.co/{model_id}",
                    summary=description,
                    published_at=parse_datetime(model.get("lastModified")),
                    metrics={
                        "trendingScore": trending_score,
                        "likes": likes,
                        "downloads": downloads,
                    },
                )
            )
        return entries

    def _fetch_papers(self) -> list[RawEntry]:
        data = self._get_json(PAPERS_URL, timeout=20)
        entries: list[RawEntry] = []
        for idx, entry in enumerate(data or [], 1):
            if not isinstance(entry, dict):
                continue
            paper = (
                entry.get("paper")
                if isinstance(entry.get("paper"), dict)
                else entry
            )
            paper_id = paper.get("id") or ""
            title = (paper.get("title") or "").strip()
            if not paper_id or not title:
                continue
            url = paper.get("url") or f"https://arxiv.org/abs/{paper_id}"
            summary = (paper.get("summary") or "").strip()
            entries.append(
                RawEntry(
                    rank=idx,
                    title=title,
                    url=url,
                    summary=summary,
                    published_at=parse_datetime(paper.get("publishedAt")),
                    metrics={"hf_paper_id": paper_id},
                )
            )
        return entries


register(HuggingFaceAdapter())
