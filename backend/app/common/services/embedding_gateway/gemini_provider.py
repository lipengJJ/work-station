"""Gemini Embedding：POST /v1beta/models/{model}:batchEmbedContents。

Gemini 的 embedding 接口一次最多 100 条，taskType 区分 RETRIEVAL_DOCUMENT / RETRIEVAL_QUERY。
"""
from __future__ import annotations

import requests

from app.common.services.embedding_gateway.base import (
    EmbeddingGatewayError,
    EmbeddingRequest,
    EmbeddingResult,
    TASK_DOCUMENT,
    TASK_QUERY,
)

GEMINI_BATCH_LIMIT = 100
GEMINI_TIMEOUT = 60

_TASK_MAP = {
    TASK_DOCUMENT: "RETRIEVAL_DOCUMENT",
    TASK_QUERY: "RETRIEVAL_QUERY",
}


def embed_gemini(request: EmbeddingRequest, api_key: str) -> EmbeddingResult:
    if not api_key:
        raise EmbeddingGatewayError("Gemini Embedding 未配置 API Key")
    task_type = _TASK_MAP.get(request.task_type, "RETRIEVAL_DOCUMENT")
    vectors: list[list[float]] = []
    for i in range(0, len(request.texts), GEMINI_BATCH_LIMIT):
        batch = request.texts[i : i + GEMINI_BATCH_LIMIT]
        payload = {
            "requests": [
                {
                    "model": f"models/{request.model}",
                    "content": {"parts": [{"text": t}]},
                    "taskType": task_type,
                }
                for t in batch
            ]
        }
        try:
            resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{request.model}:batchEmbedContents",
                params={"key": api_key},
                json=payload,
                timeout=GEMINI_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise EmbeddingGatewayError(f"Gemini Embedding 请求失败: {exc}") from exc
        if resp.status_code >= 400:
            raise EmbeddingGatewayError(
                f"Gemini Embedding 失败 {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
        for emb in data.get("embeddings", []):
            vectors.append(emb["values"])
    if not vectors:
        raise EmbeddingGatewayError("Gemini Embedding 返回空结果")
    return EmbeddingResult(vectors=vectors, dimension=len(vectors[0]))
