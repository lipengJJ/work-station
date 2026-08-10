"""
智谱 GLM Key/模型配置的读写：复用系统设置里的 ApiConfig 表，和 gemini_config.py
是同一套模式，只是换了一组 name。目前只有笔记结构化预处理（note_structurer.py）
用这份配置，chat/xhs 分析等其余功能继续用 Gemini，互不影响。

系统设置 > API 配置页面本来就是"任意 name/value"的通用录入界面（见
frontend/.../settings/api-config/index.vue），不需要为这两个新 key 改前端代码，
直接在那个页面点"新增配置"填 name=zhipu_api_key 就行。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.common.models import ApiConfig

API_KEY_CONFIG_NAME = "zhipu_api_key"
MODEL_CONFIG_NAME = "zhipu_model"
DEFAULT_MODEL = "glm-4-flash"


def get_config_value(db: Session, name: str) -> Optional[str]:
    row = db.query(ApiConfig).filter(ApiConfig.name == name).first()
    return row.value if row else None


def get_zhipu_config(db: Session) -> tuple[Optional[str], str]:
    """返回 (api_key, model)；api_key 为空表示尚未配置。"""
    api_key = get_config_value(db, API_KEY_CONFIG_NAME)
    model = get_config_value(db, MODEL_CONFIG_NAME) or DEFAULT_MODEL
    return api_key, model
