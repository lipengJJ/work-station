from pydantic import BaseModel, Field


class TokenStatus(BaseModel):
    has_token: bool
    preview: str | None
    updated_at: str | None


class ManualTokenIn(BaseModel):
    cookies: str = Field(..., min_length=10)


class PhoneSendIn(BaseModel):
    phone: str
    zone: str = "86"


class PhoneVerifyIn(BaseModel):
    phone: str
    code: str
    zone: str = "86"


class BatchDeleteNotesIn(BaseModel):
    note_ids: list[str] = Field(..., min_length=1)


class CollectTaskIn(BaseModel):
    keyword: str = Field(..., min_length=1)
    require_num: int = Field(50, ge=1, le=1000)
    sort_type_choice: int = 0
    note_type: int = 0
    note_time: int = 0
    note_range: int = 0
    save_choice: str = "excel"
    fetch_comments: bool = False
    max_comments_per_note: int | None = None
    comment_interval_seconds: float | None = None
