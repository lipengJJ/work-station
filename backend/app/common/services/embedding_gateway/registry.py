"""Embedding Provider 注册表：厂商以 EmbeddingProviderSpec 注册到这里，
service.embed() 按 provider 分发。要接新厂商只加一条注册，不需要改分发逻辑。

每个 provider 的配置 key 名由注册时声明（见 embedding_config.py），存在系统设置的
ApiConfig 表里，各厂商互不干扰。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.common.services.embedding_gateway.base import EmbeddingRequest, EmbeddingResult


@dataclass(frozen=True)
class EmbeddingProviderSpec:
    """一个向量模型厂商的完整描述。handler 是批量 embedding 调用函数。"""

    key: str
    label: str
    description: str  # 前端提示文案（去哪里获取 Key）
    default_model: str
    default_dimension: int
    handler: Callable[[EmbeddingRequest, str], EmbeddingResult] | None = None


_PROVIDERS: dict[str, EmbeddingProviderSpec] = {}


def register_provider(spec: EmbeddingProviderSpec) -> None:
    """注册一个 provider。重复注册同 key 会覆盖（方便测试/热更新）。"""
    _PROVIDERS[spec.key] = spec


def get_provider(key: str) -> EmbeddingProviderSpec | None:
    return _PROVIDERS.get(key)


def list_providers() -> list[EmbeddingProviderSpec]:
    return list(_PROVIDERS.values())


def provider_keys() -> list[str]:
    return list(_PROVIDERS.keys())
