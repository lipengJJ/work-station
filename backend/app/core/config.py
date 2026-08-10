"""
分层配置：环境变量 > 默认值。骨架阶段只做够用的最小集合。
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend 项目根目录（这个文件在 app/core/config.py，往上三级就是 backend/）。给需要按
# 固定路径找文件的地方用（比如 xhs 签名用的 static/*.js），不要在各处自己拼 __file__ 的
# 相对路径——那样一旦文件挪了层级（这次 MVC 重构就踩过一次）就悄悄找不到文件。
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WORKBENCH_")

    app_title: str = "统一工作台"
    database_url: str = "sqlite:///./workbench.db"
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 60 * 12
    cors_origins: str = "http://localhost:8000,http://localhost:8001"
    # 可选：第三方夸克资源搜索 API 地址（GET {url}?keyword=&page=&page_size=），
    # 配置了资源搜索模块会优先使用它，否则用内置搜索引擎渠道
    quark_search_api: str = ""


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
