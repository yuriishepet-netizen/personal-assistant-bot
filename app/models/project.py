from __future__ import annotations

"""Project model for organizing tasks by project."""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Boolean, DateTime, ForeignKey, Integer, Table, Column, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# Association table for project membership (private projects)
project_members = Table(
    "project_members",
    Base.metadata,
    Column("project_id", Integer, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    color: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, default="#6366f1")
    is_private: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tasks = relationship("Task", back_populates="project")
    members = relationship("User", secondary=project_members, backref="accessible_projects")
