from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChatConfigOut(BaseModel):
    configured: bool
    model: str


class ChatConfigIn(BaseModel):
    # 留空 = 不修改已保存的 key，只更新模型；首次配置时前端会要求必填
    api_key: str | None = Field(None, min_length=10)
    model: str = "gemini-2.0-flash"


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    created_at: datetime


class ChatSendIn(BaseModel):
    content: str = Field(..., min_length=1)
