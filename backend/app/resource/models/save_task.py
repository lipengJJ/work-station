from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ResourceSaveTask(Base):
    """
    资源转存记录：把搜索到的网盘分享链接转存进用户网盘的流水账。
    只记录转存请求与结果（成功/失败原因），不缓存资源内容本身；
    不同资源源（quark/baidu/aliyun...）共用这一张表，source 字段区分。
    """

    __tablename__ = "resource_save_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, default=0, index=True)
    source: Mapped[str] = mapped_column(String(32), default="quark", index=True)
    resource_title: Mapped[str] = mapped_column(String(512))
    share_url: Mapped[str] = mapped_column(Text)
    share_id: Mapped[str] = mapped_column(String(64), index=True)
    share_pwd: Mapped[str] = mapped_column(String(16), default="")
    target_dir: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending/success/failed
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
