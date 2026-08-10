from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.database import get_db
from app.core.security import create_access_token, verify_password
from app.common.models import User
from app.common.schemas.auth import CurrentUser, TokenResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form.username).first()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    return TokenResponse(access_token=create_access_token(user.username))


@router.get("/me", response_model=CurrentUser)
def me(current_user: User = Depends(get_current_user)):
    return CurrentUser(id=current_user.id, username=current_user.username, role=current_user.role)
