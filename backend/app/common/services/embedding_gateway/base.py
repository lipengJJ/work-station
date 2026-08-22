"""Embedding Gateway 的统一请求/结果形状。

与 AI Gateway（生成式对话）刻意分开：Embedding 没有 system/messages/tools/thinking，
且通常支持批量文本与 task type（检索文档 vs 检索查询）。业务方（hotlist 语义检索）
拼出 EmbeddingRequest 交给 service.embed()，不关心具体厂商的 REST 格式。
"""
from __future__ import annotations

from dataclasses import dataclass

# task_type 取值：检索文档（入库）与检索查询（用户需求）分开，供厂商区分 embedding 方向
TASK_DOCUMENT = "retrieval_document"
TASK_QUERY = "retrieval_query"


@dataclass
class EmbeddingRequest:
    provider: str
    model: str
    texts: list[str]
    task_type: str = TASK_DOCUMENT  # retrieval_document / retrieval_query


@dataclass
class EmbeddingResult:
    vectors: list[list[float]]
    dimension: int
    usage_tokens: int = 0


class EmbeddingGatewayError(Exception):
    """Embedding provider 请求失败（HTTP 错误、超时、厂商错误）时统一抛出。"""
