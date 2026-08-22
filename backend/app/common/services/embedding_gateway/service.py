"""Embedding Gateway 的分发入口：按 EmbeddingRequest.provider 查注册表，把请求交给
对应 provider 的 handler。要接新厂商，在下面 PROVIDER 注册区加一条注册即可——
OpenAI 兼容厂商用 make_openai_compatible_embed(base_url) 工厂函数，一行搞定；
Gemini 这种自有协议自己实现一个 handler 再注册。

调用方在同步阶段取好 api_key 作为普通参数传入，不要在 handler 内部依赖 db session。
"""
from __future__ import annotations

from app.common.services.embedding_gateway.base import (
    EmbeddingGatewayError,
    EmbeddingRequest,
    EmbeddingResult,
)
from app.common.services.embedding_gateway.gemini_provider import embed_gemini
from app.common.services.embedding_gateway.openai_compatible_provider import (
    make_openai_compatible_embed,
)
from app.common.services.embedding_gateway.registry import (
    EmbeddingProviderSpec,
    get_provider,
    register_provider,
)

# ---------------------------------------------------------------- PROVIDER 注册 ----
register_provider(
    EmbeddingProviderSpec(
        key="gemini",
        label="Gemini（Google）",
        description="Google AI Studio（aistudio.google.com）获取 API Key；模型如 gemini-embedding-001",
        default_model="gemini-embedding-001",
        default_dimension=768,
        handler=embed_gemini,
    )
)

register_provider(
    EmbeddingProviderSpec(
        key="openai_compatible",
        label="OpenAI 兼容（/embeddings）",
        description="支持 text-embedding-3-small 等 OpenAI 兼容向量接口",
        default_model="text-embedding-3-small",
        default_dimension=1536,
        handler=make_openai_compatible_embed("https://api.openai.com/v1"),
    )
)


def embed(request: EmbeddingRequest, api_key: str) -> EmbeddingResult:
    spec = get_provider(request.provider)
    if spec is None or spec.handler is None:
        raise EmbeddingGatewayError(f"暂不支持的 Embedding provider：{request.provider}")
    return spec.handler(request, api_key)


def build_model_key(provider: str, model: str, dimension: int) -> str:
    """模型唯一标识：{provider}:{model}:{dimension}，例如 gemini:gemini-embedding-001:768。

    文章向量与主题向量只有在 model_key、维度和预处理版本兼容时才能比较。
    """
    return f"{provider}:{model}:{dimension}"
