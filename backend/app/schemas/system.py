from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
    created_at: datetime


class ScheduleConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    module: str
    enabled: bool
    hour: int
    minute: int
    days: str


class ScheduleConfigIn(BaseModel):
    module: str
    enabled: bool = False
    hour: int = 9
    minute: int = 0
    days: str = "mon-fri"


class ApiConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    value: str
    description: str | None


class ApiConfigIn(BaseModel):
    name: str
    value: str
    description: str | None = None
