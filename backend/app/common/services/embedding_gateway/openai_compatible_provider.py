"""OpenAI 兼容 Embedding：POST {base_url}/embeddings。

DeepSeek/通义/智谱等 OpenAI 兼容厂商如果提供 embedding 端点，用
make_openai_compatible_embed(base_url) 工厂函数一行接入。
"""
from __future__ import annotations

import requests

from app.common.services.embedding_gateway.base import (
    EmbeddingGatewayError,
    EmbeddingRequest,
    EmbeddingResult,
)

OPENAI_BATCH_LIMIT = 32
OPENAI_TIMEOUT = 60


def make_openai_compatible_embed(base_url: str):
    """返回一个绑定 base_url 的 embedding handler。"""

    def _embed(request: EmbeddingRequest, api_key: str) -> EmbeddingResult:
        if not api_key:
            raise EmbeddingGatewayError("OpenAI 兼容 Embedding 未配置 API Key")
        vectors: list[list[float]] = []
        for i in range(0, len(request.texts), OPENAI_BATCH_LIMIT):
            batch = request.texts[i : i + OPENAI_BATCH_LIMIT]
            try:
                resp = requests.post(
                    f"{base_url}/embeddings",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"model": request.model, "input": batch},
                    timeout=OPENAI_TIMEOUT,
                )
            except requests.RequestException as exc:
                raise EmbeddingGatewayError(f"Embedding 请求失败: {exc}") from exc
            if resp.status_code >= 400:
                raise EmbeddingGatewayError(
                    f"Embedding 失败 {resp.status_code}: {resp.text[:200]}"
                )
            data = resp.json()
            vectors.extend(d["embedding"] for d in data["data"])
        if not vectors:
            raise EmbeddingGatewayError("Embedding 返回空结果")
        return EmbeddingResult(vectors=vectors, dimension=len(vectors[0]))

    return _embed
