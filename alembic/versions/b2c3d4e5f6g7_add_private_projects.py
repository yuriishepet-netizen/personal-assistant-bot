"""Add private projects with member access control

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-13 10:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "b2c3d4e5f6g7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add is_private column to projects
    op.add_column("projects", sa.Column("is_private", sa.Boolean(), server_default="false", nullable=False))

    # Create project_members association table
    op.create_table(
        "project_members",
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    )

    # Make "Проект X" private and add admin (user_id=1) as a member
    op.execute("UPDATE projects SET is_private = true WHERE name = 'Проект X'")
    op.execute("""
        INSERT INTO project_members (project_id, user_id)
        SELECT p.id, 1 FROM projects p WHERE p.name = 'Проект X'
    """)


def downgrade() -> None:
    op.drop_table("project_members")
    op.drop_column("projects", "is_private")
