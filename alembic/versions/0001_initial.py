"""Initial task tracker schema.

Revision ID: 0001_initial
Revises: None
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
now = sa.text("now()")


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "auth_sessions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])

    op.create_table(
        "projects",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column(
            "owner_id", UUID, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        *timestamps(),
    )
    op.create_index("ix_projects_name", "projects", ["name"])
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])

    op.create_table(
        "project_members",
        sa.Column(
            "project_id", UUID, sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.CheckConstraint("role IN ('OWNER', 'MEMBER')", name="ck_project_members_role"),
    )

    op.create_table(
        "tasks",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "project_id", UUID, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "creator_id", UUID, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("assignee_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('BACKLOG', 'TODO', 'IN_PROGRESS', 'DONE', 'CANCELLED')",
            name="ck_tasks_status",
        ),
        sa.CheckConstraint(
            "priority IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
            name="ck_tasks_priority",
        ),
    )
    for column in ("project_id", "assignee_id", "title", "status", "priority", "due_at"):
        op.create_index(f"ix_tasks_{column}", "tasks", [column])
    op.create_index("ix_tasks_created_at_desc", "tasks", [sa.text("created_at DESC")])

    op.create_table(
        "tags",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "project_id", UUID, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("color", sa.String(7), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("project_id", "name", name="uq_tags_project_name"),
    )
    op.create_index("ix_tags_project_id", "tags", ["project_id"])
    op.create_index(
        "uq_tags_project_name_lower", "tags", ["project_id", sa.text("lower(name)")], unique=True
    )

    op.create_table(
        "task_tags",
        sa.Column(
            "task_id", UUID, sa.ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("tag_id", UUID, sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    )

    op.create_table(
        "comments",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "task_id", UUID, sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "author_id", UUID, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("body", sa.Text(), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_comments_task_id", "comments", ["task_id"])


def downgrade() -> None:
    op.drop_table("comments")
    op.drop_table("task_tags")
    op.drop_table("tags")
    op.drop_table("tasks")
    op.drop_table("project_members")
    op.drop_table("projects")
    op.drop_table("auth_sessions")
    op.drop_table("users")
