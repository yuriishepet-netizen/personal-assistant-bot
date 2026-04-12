from __future__ import annotations

"""Project model for organizing tasks by project."""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    color: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, default="#6366f1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tasks = relationship("Task", back_populates="project")
