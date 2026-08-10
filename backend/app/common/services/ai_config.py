"""
AI 模型统一配置入口：系统里所有"选哪个厂商、哪个模型"的地方（小红书 AI 分析、
Skill Runtime、API 配置页的 AI 模型卡）都从这里读，不在各业务里各自判断。

配置仍是复用 ApiConfig 表（key/value），按 provider 分开存——每个厂商的 key 名
由 ProviderSpec 注册时声明（见 ai_gateway/registry.py 与 ai_gateway/service.py 的
注册表），这里不做任何厂商相关的硬编码：新增厂商只需注册 ProviderSpec，配置读写、
前端渲染自动跟着走。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.common.services.ai_gateway.registry import get_provider, list_providers, provider_keys, to_meta
from app.common.services.gemini_config import get_config_value, set_config_value

PROVIDER_CONFIG_NAME = "ai_provider"
DEFAULT_PROVIDER = "gemini"


def get_ai_provider(db: Session) -> str:
    provider = get_config_value(db, PROVIDER_CONFIG_NAME)
    return provider if get_provider(provider) else DEFAULT_PROVIDER


def get_ai_credentials(db: Session) -> tuple[str, Optional[str], str, bool]:
    """
    返回 (provider, api_key, model, thinking_enabled)。api_key 为空表示当前厂商还没
    配置 Key（controller 拿这个值判 400，提示先配置）。
    """
    provider = get_ai_provider(db)
    spec = get_provider(provider)
    api_key = get_config_value(db, spec.api_key_config)
    model = get_config_value(db, spec.model_config) or spec.default_model
    thinking_enabled = False
    if spec.thinking_config:
        thinking_enabled = get_config_value(db, spec.thinking_config) == "true"
    return provider, api_key, model, thinking_enabled


def get_ai_config(db: Session) -> dict:
    """返回当前选中 provider 的生效配置：{"provider", "configured", "model", "thinking_enabled"}"""
    provider, api_key, model, thinking_enabled = get_ai_credentials(db)
    return {
        "provider": provider,
        "configured": bool(api_key),
        "model": model,
        "thinking_enabled": thinking_enabled,
    }


def set_ai_config(
    db: Session,
    provider: str,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    thinking_enabled: Optional[bool] = None,
) -> dict:
    """
    保存 AI 配置：先落 provider，再按注册表里该厂商声明的 key 名写 Key/模型/思考模式。
    api_key 留空 = 不修改已保存的 Key（首次配置时调用方负责校验必填）；
    thinking_enabled 不传 = 保持已保存的值（比如只切厂商/只改模型，不动思考模式）。
    返回保存后的 get_ai_config() 结果。
    """
    spec = get_provider(provider) or get_provider(DEFAULT_PROVIDER)
    provider = spec.key
    set_config_value(db, PROVIDER_CONFIG_NAME, provider, "AI 模型厂商")

    if api_key and api_key.strip():
        set_config_value(db, spec.api_key_config, api_key.strip(), f"{spec.label} API Key")
    if model and model.strip():
        set_config_value(db, spec.model_config, model.strip(), f"{spec.label} 模型名称")
    if spec.thinking_config and thinking_enabled is not None:
        set_config_value(
            db,
            spec.thinking_config,
            "true" if thinking_enabled else "false",
            f"{spec.label} 思考模式",
        )
    db.commit()
    return get_ai_config(db)


def list_provider_meta() -> list[dict]:
    """下发给前端渲染"厂商切换"的元数据：label/提示文案/预设模型/是否支持思考模式。"""
    return [to_meta(spec) for spec in list_providers()]


def ai_config_names() -> set[str]:
    """注册表里所有厂商用到的 ApiConfig key 名 + 厂商标记（API 配置页归类用）。"""
    names = {PROVIDER_CONFIG_NAME}
    for spec in list_providers():
        names.add(spec.api_key_config)
        names.add(spec.model_config)
        if spec.thinking_config:
            names.add(spec.thinking_config)
    return names


# 供外部确认当前支持的厂商列表（一般用不到，注册表是唯一事实来源）
def supported_providers() -> list[str]:
    return provider_keys()
