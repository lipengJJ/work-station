"""
小红书 cookie/token 的持久化，复用 app/common/controllers/system.py 里已经在用的 ApiConfig
（系统设置 > API 配置）表模式，用固定 name='xhs_cookie' 的一行存 cookie 字符串，
不再像上次独立 webapp 那样单独搞一个 token.json 文件。
"""
from datetime import timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.common.models import ApiConfig

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


def validate(db: Session) -> tuple[bool, str]:
    """
    登录态心跳探测：调 /api/sns/web/v1/user/selfinfo 检查 cookie 是否仍有效。
    返回 (是否有效, 描述)。只探测、不自动清 cookie——用户可能想先看状态再决定重登。

    结果按 VALIDATE_CACHE_TTL_SECONDS 缓存：定时追踪任务可能跑得很频繁，
    没必要每次都打一次 selfinfo。
    """
    import time as _time
    now = _time.time()
    if now - _last_validate_at < VALIDATE_CACHE_TTL_SECONDS and _last_validate_result is not None:
        return _last_validate_result

    cookies_str = get_cookies_str(db)
    if not cookies_str:
        result = (False, "未配置小红书 cookie，请先在系统设置或小红书页登录")
        _cache_validate(result, now)
        return result

    from app.xhs.services.client.xhs_crawler_client import XhsCrawlerClient
    from app.xhs.services.xhs_errors import XhsAuthError, XhsError

    try:
        success, msg, res_json = XhsCrawlerClient().get_user_self_info(cookies_str)
    except XhsAuthError as e:
        result = (False, f"登录态失效，请重新登录（{e}）")
        _cache_validate(result, now)
        return result
    except XhsError as e:
        # 网络/限流等原因导致探测失败，不确定登录态是否有效，保守按"无法确认"处理
        result = (False, f"登录态探测失败，暂时无法确认（{e}）")
        _cache_validate(result, now)
        return result
    except Exception as e:
        result = (False, f"登录态探测异常: {e}")
        _cache_validate(result, now)
        return result

    if success and res_json and res_json.get("data"):
        result = (True, "登录态有效")
    else:
        result = (False, f"登录态可能已失效（{msg or '接口未返回用户信息'}），请重新登录")
    _cache_validate(result, now)
    return result


VALIDATE_CACHE_TTL_SECONDS = 60
_last_validate_at: float = 0.0
_last_validate_result: Optional[tuple[bool, str]] = None


def _cache_validate(result: tuple[bool, str], now: float) -> None:
    global _last_validate_at, _last_validate_result
    _last_validate_at = now
    _last_validate_result = result
