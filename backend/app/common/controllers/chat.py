"""
"AI 助手"独立聊天页已下线（连同 ChatMessage 表和消息历史/流式发送接口一起删掉了），
但这里的模型配置接口还留着——小红书 AI 分析页的"模型设置"、系统设置 API 配置页的
"AI 模型"卡都是靠这两个接口读写同一份配置（见 app/common/services/ai_config.py
顶部注释），删了会直接打断那些功能。路由前缀继续用 /api/chat/config 只是为了不用
同时改前端调用路径，不代表还有"聊天"这个功能。

厂商由 AI Gateway 的注册表（app/common/services/ai_gateway/service.py）驱动：
新增厂商注册 ProviderSpec 后，GET 会自动返回它的元数据，前端不用改代码就能
切换/配置。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.database import get_db
from app.common.schemas.chat import ChatConfigIn, ChatConfigOut
from app.common.services.ai_config import (
    DEFAULT_PROVIDER,
    get_ai_config,
    get_ai_provider,
    list_provider_meta,
    set_ai_config,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.get("/config", response_model=ChatConfigOut)
def get_config(db: Session = Depends(get_db), _=Depends(get_current_user)):
    cfg = get_ai_config(db)
    return ChatConfigOut(**cfg, providers=list_provider_meta())


@router.put("/config", response_model=ChatConfigOut)
def set_config(body: ChatConfigIn, db: Session = Depends(get_db), _=Depends(get_current_user)):
    provider = body.provider or get_ai_provider(db) or DEFAULT_PROVIDER
    cfg = set_ai_config(
        db,
        provider=provider,
        api_key=body.api_key,
        model=body.model,
        thinking_enabled=body.thinking_enabled,
    )
    return ChatConfigOut(**cfg, providers=list_provider_meta())
