"""Add Project model and project_id to tasks

Revision ID: a1b2c3d4e5f6
Revises: 40c5a2f26632
Create Date: 2026-04-13 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "40c5a2f26632"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create projects table
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), unique=True, nullable=False),
        sa.Column("color", sa.String(20), nullable=True, server_default="#6366f1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Add project_id FK to tasks
    op.add_column("tasks", sa.Column("project_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_tasks_project_id", "tasks", "projects", ["project_id"], ["id"])

    # Seed initial projects
    op.execute("""
        INSERT INTO projects (name, color) VALUES
        ('VDALO', '#ef4444'),
        ('USA проект', '#3b82f6'),
        ('Навчання', '#22c55e'),
        ('Проект X', '#a855f7'),
        ('Feel with Fill', '#f97316'),
        ('Особисті', '#06b6d4'),
        ('Інше', '#6b7280')
    """)


def downgrade() -> None:
    op.drop_constraint("fk_tasks_project_id", "tasks", type_="foreignkey")
    op.drop_column("tasks", "project_id")
    op.drop_table("projects")
