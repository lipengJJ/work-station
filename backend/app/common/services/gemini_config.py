"""
Gemini Key/模型配置的读写：复用系统设置里已有的 ApiConfig 表（key/value 存第三方服务凭证），
chat 和 xhs 笔记分析都是同一份配置，不用各存一份。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.common.models import ApiConfig

API_KEY_CONFIG_NAME = "gemini_api_key"
MODEL_CONFIG_NAME = "gemini_model"
THINKING_CONFIG_NAME = "gemini_thinking_enabled"
DEFAULT_MODEL = "gemini-2.0-flash"


def get_config_value(db: Session, name: str) -> Optional[str]:
    row = db.query(ApiConfig).filter(ApiConfig.name == name).first()
    return row.value if row else None


def set_config_value(db: Session, name: str, value: str, description: str) -> None:
    row = db.query(ApiConfig).filter(ApiConfig.name == name).first()
    if row:
        row.value = value
    else:
        db.add(ApiConfig(name=name, value=value, description=description))


def get_thinking_enabled(db: Session) -> bool:
    return get_config_value(db, THINKING_CONFIG_NAME) == "true"


def get_gemini_config(db: Session) -> tuple[Optional[str], str, bool]:
    """返回 (api_key, model, thinking_enabled)；api_key 为空表示尚未配置。"""
    api_key = get_config_value(db, API_KEY_CONFIG_NAME)
    model = get_config_value(db, MODEL_CONFIG_NAME) or DEFAULT_MODEL
    thinking_enabled = get_thinking_enabled(db)
    return api_key, model, thinking_enabled
