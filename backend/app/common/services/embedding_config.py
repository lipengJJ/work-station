"""Embedding 向量模型配置：从 ApiConfig 读取 embedding_provider / embedding_model 等。

embedding_api_key 可空——为空时复用对应 AI provider 的 key（如 gemini 用 gemini_api_key）。
聊天模型与向量模型分别配置、分别演进，不能把聊天模型名当向量模型名用。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

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
    return get_config_value(db, EMBEDDING_MODEL_CONFIG) or DEFAULT_EMBEDDING_MODEL


def get_embedding_dimension(db: Session) -> int:
    raw = get_config_value(db, EMBEDDING_DIMENSION_CONFIG)
    if raw and raw.isdigit():
        return int(raw)
    return DEFAULT_EMBEDDING_DIMENSION


def get_embedding_api_key(db: Session) -> str:
    """embedding_api_key 为空时，复用对应 AI provider 的 key（如 gemini_api_key）。"""
    explicit = get_config_value(db, EMBEDDING_API_KEY_CONFIG) or ""
    if explicit:
        return explicit
    provider = get_embedding_provider(db)
    return get_config_value(db, f"{provider}_api_key") or ""
