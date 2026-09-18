from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DDL,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.partitioning import partition_ddl, required_months
from app.domain.enums import ProjectRole, TaskPriority, TaskStatus


def utc_now() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        onupdate=utc_now,
        nullable=False,
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)

    owner: Mapped[User] = relationship(foreign_keys=[owner_id])
    members: Mapped[list["ProjectMember"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )


class ProjectMember(Base):
    __tablename__ = "project_members"

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[ProjectRole] = mapped_column(
        Enum(ProjectRole, name="project_role", native_enum=False, length=20)
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="members")
    user: Mapped[User] = relationship()


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = {"postgresql_partition_by": "RANGE (created_at)"}

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, default=utc_now, server_default=func.now()
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    creator_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    assignee_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(240), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status", native_enum=False, length=20), index=True
    )
    priority: Mapped[TaskPriority] = mapped_column(
        Enum(TaskPriority, name="task_priority", native_enum=False, length=20), index=True
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    project: Mapped[Project] = relationship()
    creator: Mapped[User] = relationship(foreign_keys=[creator_id])
    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id])
    tags: Mapped[list["Tag"]] = relationship(secondary="task_tags", back_populates="tasks")


class Tag(TimestampMixin, Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_tags_project_name"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(60))
    color: Mapped[str] = mapped_column(String(7), default="#808080")

    project: Mapped[Project] = relationship()
    tasks: Mapped[list[Task]] = relationship(secondary="task_tags", back_populates="tags")


class TaskTag(Base):
    __tablename__ = "task_tags"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "task_created_at"], ["tasks.id", "tasks.created_at"],
            ondelete="CASCADE",
        ),
    )

    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    task_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    tag_id: Mapped[UUID] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )


class Comment(TimestampMixin, Base):
    __tablename__ = "comments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "task_created_at"], ["tasks.id", "tasks.created_at"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    task_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    author_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    body: Mapped[str] = mapped_column(Text)

    task: Mapped[Task] = relationship()
    author: Mapped[User] = relationship()


Index("ix_tasks_created_at_desc", Task.created_at.desc())
Index("uq_tags_project_name_lower", Tag.project_id, func.lower(Tag.name), unique=True)


def _create_test_partitions(target, connection, **kwargs) -> None:
    if connection.dialect.name == "postgresql":
        for start in required_months():
            connection.execute(DDL(partition_ddl(start)))


event.listen(Task.__table__, "after_create", _create_test_partitions)
