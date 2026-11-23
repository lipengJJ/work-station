"""Embedding 向量模型配置：从 ApiConfig 读取 embedding_provider / embedding_model 等。

embedding_api_key 可空——仅 provider=gemini 时为空会复用 AI 模型的 gemini_api_key
（同一账号同一个 Key，两处配置本就该一致）。其余厂商（如 zhipu）不做隐式复用：
向量模型是独立业务，即便系统里已经为其他功能（笔记结构化）配了 zhipu_api_key，
也要求在这里单独填一遍，避免两个用途共用一个 Key 时额度/权限互相影响、排查错误
时也分不清是哪边在耗额度。
聊天模型与向量模型分别配置、分别演进，不能把聊天模型名当向量模型名用。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.common.services.embedding_gateway.registry import get_provider
from app.common.services.gemini_config import get_config_value

EMBEDDING_PROVIDER_CONFIG = "embedding_provider"
EMBEDDING_API_KEY_CONFIG = "embedding_api_key"
EMBEDDING_MODEL_CONFIG = "embedding_model"
EMBEDDING_DIMENSION_CONFIG = "embedding_dimension"

DEFAULT_EMBEDDING_PROVIDER = "gemini"
DEFAULT_EMBEDDING_MODEL = "gemini-embedding-001"
DEFAULT_EMBEDDING_DIMENSION = 768


def get_embedding_provider(db: Session) -> str:
    return get_config_value(db, EMBEDDING_PROVIDER_CONFIG) or DEFAULT_EMBEDDING_PROVIDER


def get_embedding_model(db: Session) -> str:
    """未显式配置模型名时，落到当前厂商注册的默认模型（而不是死死写死 Gemini 的），
    否则切到智谱等厂商却不填模型名，会把 gemini-embedding-001 发给智谱的接口。"""
    explicit = get_config_value(db, EMBEDDING_MODEL_CONFIG)
    if explicit:
        return explicit
    spec = get_provider(get_embedding_provider(db))
    return spec.default_model if spec else DEFAULT_EMBEDDING_MODEL


def get_embedding_dimension(db: Session) -> int:
    raw = get_config_value(db, EMBEDDING_DIMENSION_CONFIG)
    if raw and raw.isdigit():
        return int(raw)
    spec = get_provider(get_embedding_provider(db))
    return spec.default_dimension if spec else DEFAULT_EMBEDDING_DIMENSION


def get_embedding_api_key(db: Session) -> str:
    """embedding_api_key 为空时，只有 gemini 会回退复用 AI 模型的 gemini_api_key；
    其余厂商（zhipu 等）必须单独填 embedding_api_key，不隐式复用其他功能的 Key。"""
    explicit = get_config_value(db, EMBEDDING_API_KEY_CONFIG) or ""
    if explicit:
        return explicit
    if get_embedding_provider(db) == "gemini":
        return get_config_value(db, "gemini_api_key") or ""
    return ""
