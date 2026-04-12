from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Enum, DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class FileType(str, enum.Enum):
    IMAGE = "image"
    DOCUMENT = "document"
    VOICE = "voice"


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"))
    file_type: Mapped[FileType] = mapped_column(Enum(FileType))
    file_url: Mapped[str] = mapped_column(String(1000))
    original_name: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    task = relationship("Task", back_populates="attachments")
