import enum
from datetime import datetime

from sqlalchemy import BigInteger, String, Text, Enum, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    MEMBER = "member"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.MEMBER)
    google_refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    assigned_tasks = relationship("Task", foreign_keys="Task.assignee_id", back_populates="assignee")
    created_tasks = relationship("Task", foreign_keys="Task.creator_id", back_populates="creator")
    comments = relationship("Comment", back_populates="user")
