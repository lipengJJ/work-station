"""
小红书 cookie/token 的持久化，复用 app/api/system.py 里已经在用的 ApiConfig
（系统设置 > API 配置）表模式，用固定 name='xhs_cookie' 的一行存 cookie 字符串，
不再像上次独立 webapp 那样单独搞一个 token.json 文件。
"""
from datetime import timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import ApiConfig

CONFIG_NAME = "xhs_cookie"


def get_cookies_str(db: Session) -> Optional[str]:
    row = db.query(ApiConfig).filter(ApiConfig.name == CONFIG_NAME).first()
    return row.value if row and row.value else None


def set_cookies_str(db: Session, cookies_str: str) -> None:
    row = db.query(ApiConfig).filter(ApiConfig.name == CONFIG_NAME).first()
    if row:
        row.value = cookies_str
    else:
        row = ApiConfig(name=CONFIG_NAME, value=cookies_str, description="小红书登录态 cookie")
        db.add(row)
    db.commit()


def clear(db: Session) -> None:
    row = db.query(ApiConfig).filter(ApiConfig.name == CONFIG_NAME).first()
    if row:
        db.delete(row)
        db.commit()


def _mask(cookies_str: str) -> str:
    if len(cookies_str) <= 24:
        return "*" * len(cookies_str)
    return f"{cookies_str[:10]}...{cookies_str[-10:]}"


def get_status(db: Session) -> dict:
    row = db.query(ApiConfig).filter(ApiConfig.name == CONFIG_NAME).first()
    if row and row.value:
        updated_at = row.updated_at
        return {
            "has_token": True,
            "preview": _mask(row.value),
            "updated_at": updated_at.astimezone(timezone.utc).isoformat() if updated_at else None,
        }
    return {"has_token": False, "preview": None, "updated_at": None}
