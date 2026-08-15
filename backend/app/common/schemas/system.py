from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
    created_at: datetime


class ApiConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    value: str
    updated_at: datetime | None = None
    description: str | None


class ApiConfigIn(BaseModel):
    name: str
    # 留空 = 编辑已有配置时不修改已保存的值；新增配置时必填
    value: str | None = None
    description: str | None = None
