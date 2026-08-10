from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.common.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
_optional_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def _user_from_token(token: Optional[str], db: Session) -> User:
    username = decode_access_token(token) if token else None
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    return user


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    return _user_from_token(token, db)


def get_current_user_for_media(
    token_header: Optional[str] = Depends(_optional_oauth2_scheme),
    token_query: Optional[str] = Query(default=None, alias="token"),
    db: Session = Depends(get_db),
) -> User:
    """
    <img>/<video> 的 src 属性没法带 Authorization 请求头，只给小红书图片/视频代理这一个
    接口用：Authorization 头或 ?token= 查询参数二选一，其余校验逻辑和 get_current_user 一样。
    """
    return _user_from_token(token_header or token_query, db)
