"""
AI Provider 注册表：所有模型厂商都以 ProviderSpec 注册到这里，网关分发、
配置读写（key 名/默认模型/思考模式支持）、前端渲染（label/预设模型/提示文案）
全部以注册表为准。要接新厂商只加一条注册，不需要改分发逻辑和配置层。

每个 provider 的"配置 key 名"由注册时声明（比如 gemini_api_key），存在系统设置
的 ApiConfig 表里，各厂商互不干扰。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterator

from app.common.services.ai_gateway.base import AIRequest


@dataclass(frozen=True)
class ProviderSpec:
    """一个模型厂商的完整描述。handler 是真正的流式调用函数。"""

    key: str
    label: str
    description: str  # 前端提示文案（去哪里获取 Key）
    api_key_config: str  # ApiConfig 表里存 API Key 的 key 名
    model_config: str  # ApiConfig 表里存模型名的 key 名
    thinking_config: str | None  # 思考模式配置 key；None = 该厂商无独立思考开关
    default_model: str
    model_presets: tuple[tuple[str, str], ...] = field(default_factory=tuple)  # (label, value)
    supports_tools: bool = False  # 是否支持 google_search / url_context 工具
    handler: Callable[[AIRequest, str], Iterator[dict]] | None = None


_PROVIDERS: dict[str, ProviderSpec] = {}


def register_provider(spec: ProviderSpec) -> None:
    """注册一个 provider。重复注册同 key 会覆盖（方便测试/热更新）。"""
    _PROVIDERS[spec.key] = spec


def get_provider(key: str) -> ProviderSpec | None:
    return _PROVIDERS.get(key)


def list_providers() -> list[ProviderSpec]:
    return list(_PROVIDERS.values())


def provider_keys() -> list[str]:
    return list(_PROVIDERS.keys())


def to_meta(spec: ProviderSpec) -> dict:
    """转成下发给前端的元数据（不含 handler）。"""
    return {
        "key": spec.key,
        "label": spec.label,
        "description": spec.description,
        "supports_thinking": spec.thinking_config is not None,
        "default_model": spec.default_model,
        "presets": [{"label": label, "value": value} for label, value in spec.model_presets],
    }
