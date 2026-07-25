from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import SessionLocal, get_db
from app.gemini.client import GeminiError, stream_chat
from app.models import ApiConfig, ChatMessage, User
from app.schemas.chat import ChatConfigIn, ChatConfigOut, ChatMessageOut, ChatSendIn

router = APIRouter(prefix="/api/chat", tags=["chat"])

# 复用系统设置里已有的 ApiConfig 表（key/value 存第三方服务凭证），不用再建一张配置表
_API_KEY_CONFIG_NAME = "gemini_api_key"
_MODEL_CONFIG_NAME = "gemini_model"
_DEFAULT_MODEL = "gemini-2.0-flash"


def _get_config_value(db: Session, name: str) -> Optional[str]:
    row = db.query(ApiConfig).filter(ApiConfig.name == name).first()
    return row.value if row else None


def _set_config_value(db: Session, name: str, value: str, description: str) -> None:
    row = db.query(ApiConfig).filter(ApiConfig.name == name).first()
    if row:
        row.value = value
    else:
        db.add(ApiConfig(name=name, value=value, description=description))


@router.get("/config", response_model=ChatConfigOut)
def get_config(db: Session = Depends(get_db), _=Depends(get_current_user)):
    api_key = _get_config_value(db, _API_KEY_CONFIG_NAME)
    model = _get_config_value(db, _MODEL_CONFIG_NAME) or _DEFAULT_MODEL
    return ChatConfigOut(configured=bool(api_key), model=model)


@router.put("/config", response_model=ChatConfigOut)
def set_config(body: ChatConfigIn, db: Session = Depends(get_db), _=Depends(get_current_user)):
    model = body.model.strip() or _DEFAULT_MODEL
    if body.api_key and body.api_key.strip():
        _set_config_value(db, _API_KEY_CONFIG_NAME, body.api_key.strip(), "Gemini API Key")
    _set_config_value(db, _MODEL_CONFIG_NAME, model, "Gemini 模型名称")
    db.commit()
    has_key = bool(_get_config_value(db, _API_KEY_CONFIG_NAME))
    return ChatConfigOut(configured=has_key, model=model)


@router.get("/messages", response_model=list[ChatMessageOut])
def list_messages(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return (
        db.query(ChatMessage)
        .filter(ChatMessage.user_id == user.id)
        .order_by(ChatMessage.created_at, ChatMessage.id)
        .all()
    )


@router.delete("/messages")
def clear_messages(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.query(ChatMessage).filter(ChatMessage.user_id == user.id).delete()
    db.commit()
    return {"success": True}


@router.post("/stream")
def send_message(body: ChatSendIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    api_key = _get_config_value(db, _API_KEY_CONFIG_NAME)
    if not api_key:
        raise HTTPException(400, "尚未配置 Gemini API Key")
    model = _get_config_value(db, _MODEL_CONFIG_NAME) or _DEFAULT_MODEL

    db.add(ChatMessage(user_id=user.id, role="user", content=body.content))
    db.commit()

    history = [
        {"role": m.role, "content": m.content}
        for m in db.query(ChatMessage)
        .filter(ChatMessage.user_id == user.id)
        .order_by(ChatMessage.created_at, ChatMessage.id)
        .all()
    ]
    user_id = user.id

    def event_stream():
        full_text = ""
        try:
            for delta in stream_chat(api_key, model, history):
                full_text += delta
                yield f"data: {json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
        except GeminiError as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
            return
        except Exception as e:
            yield f"data: {json.dumps({'error': f'请求失败：{e}'}, ensure_ascii=False)}\n\n"
            return

        # 流已经结束，这里另开一个 session 落库——不复用请求作用域的 db，
        # 避免依赖它在流式响应发完之前是否还开着
        if full_text:
            save_db = SessionLocal()
            try:
                save_db.add(ChatMessage(user_id=user_id, role="assistant", content=full_text))
                save_db.commit()
            finally:
                save_db.close()
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
