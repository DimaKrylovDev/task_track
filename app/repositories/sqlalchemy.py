from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, contains_eager, selectinload

from app.db.models import (
    AuthSession,
    Comment,
    Project,
    ProjectMember,
    Tag,
    Task,
    User,
)
from app.domain.enums import TaskPriority, TaskStatus


@dataclass(slots=True)
class TaskFilters:
    project_id: UUID | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    assignee_id: UUID | None = None
    tag_id: UUID | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    search: str | None = None
    sort: str = "-created_at"


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, user: User) -> None:
        self.session.add(user)
        await self.session.flush()

    async def get(self, user_id: UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        return await self.session.scalar(select(User).where(User.email == email))

    async def search(self, query: str, limit: int = 20) -> list[User]:
        pattern = f"%{query}%"
        result = await self.session.scalars(
            select(User)
            .where(or_(User.email.ilike(pattern), User.display_name.ilike(pattern)))
            .order_by(User.display_name, User.email)
            .limit(limit)
        )
        return list(result)


class AuthSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, auth_session: AuthSession) -> None:
        self.session.add(auth_session)
        await self.session.flush()

    async def get_for_update(self, session_id: UUID) -> AuthSession | None:
        return await self.session.scalar(
            select(AuthSession).where(AuthSession.id == session_id).with_for_update()
        )


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, project: Project) -> None:
        self.session.add(project)
        await self.session.flush()

    async def delete(self, project: Project) -> None:
        await self.session.delete(project)

    async def get(self, project_id: UUID) -> Project | None:
        return await self.session.scalar(
            select(Project).where(Project.id == project_id).options(selectinload(Project.owner))
        )

    async def get_accessible(self, project_id: UUID, user_id: UUID) -> Project | None:
        return await self.session.scalar(
            select(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(Project.id == project_id, ProjectMember.user_id == user_id)
            .options(selectinload(Project.owner))
        )

    async def list_accessible(self, user_id: UUID) -> list[Project]:
        result = await self.session.scalars(
            select(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user_id)
            .options(selectinload(Project.owner))
            .order_by(Project.created_at.desc())
        )
        return list(result)

    async def get_membership(self, project_id: UUID, user_id: UUID) -> ProjectMember | None:
        return await self.session.get(ProjectMember, (project_id, user_id))

    async def add_member(self, member: ProjectMember) -> None:
        self.session.add(member)
        await self.session.flush()

    async def remove_member(self, member: ProjectMember) -> None:
        await self.session.delete(member)

    async def unassign_member_tasks(self, project_id: UUID, user_id: UUID) -> None:
        await self.session.execute(
            update(Task)
            .where(Task.project_id == project_id, Task.assignee_id == user_id)
            .values(assignee_id=None)
        )

    async def list_members(self, project_id: UUID) -> list[ProjectMember]:
        # Real JOIN query used by the API: memberships + users + projects.
        result = await self.session.scalars(
            select(ProjectMember)
            .join(ProjectMember.user)
            .join(ProjectMember.project)
            .where(ProjectMember.project_id == project_id)
            .options(
                contains_eager(ProjectMember.user),
                contains_eager(ProjectMember.project),
            )
            .order_by(ProjectMember.role, User.display_name)
        )
        return list(result.unique())


class TagRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, tag: Tag) -> None:
        self.session.add(tag)
        await self.session.flush()

    async def get(self, tag_id: UUID) -> Tag | None:
        return await self.session.get(Tag, tag_id)

    async def get_by_name(self, project_id: UUID, name: str) -> Tag | None:
        return await self.session.scalar(
            select(Tag).where(Tag.project_id == project_id, func.lower(Tag.name) == name.lower())
        )

    async def list_for_project(self, project_id: UUID) -> list[Tag]:
        result = await self.session.scalars(
            select(Tag).where(Tag.project_id == project_id).order_by(Tag.name)
        )
        return list(result)

    async def get_many(self, tag_ids: Sequence[UUID]) -> list[Tag]:
        if not tag_ids:
            return []
        result = await self.session.scalars(select(Tag).where(Tag.id.in_(tag_ids)))
        return list(result)

    async def delete(self, tag: Tag) -> None:
        await self.session.delete(tag)


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, task: Task) -> None:
        self.session.add(task)
        await self.session.flush()

    async def delete(self, task: Task) -> None:
        await self.session.delete(task)

    async def get(self, task_id: UUID) -> Task | None:
        return await self.session.scalar(select(Task).where(Task.id == task_id))

    def _filter_conditions(self, filters: TaskFilters) -> list[Any]:
        conditions: list[Any] = []
        if filters.project_id:
            conditions.append(Task.project_id == filters.project_id)
        if filters.status:
            conditions.append(Task.status == filters.status)
        if filters.priority:
            conditions.append(Task.priority == filters.priority)
        if filters.assignee_id:
            conditions.append(Task.assignee_id == filters.assignee_id)
        if filters.tag_id:
            conditions.append(Task.tags.any(Tag.id == filters.tag_id))
        if filters.created_from:
            conditions.append(Task.created_at >= filters.created_from)
        if filters.created_to:
            conditions.append(Task.created_at <= filters.created_to)
        if filters.search:
            pattern = f"%{filters.search}%"
            conditions.append(or_(Task.title.ilike(pattern), Task.description.ilike(pattern)))
        return conditions

    async def get_detailed(self, task_id: UUID, user_id: UUID) -> Task | None:
        creator = aliased(User, name="creator")
        assignee = aliased(User, name="assignee")
        # Non-trivial JOIN query: task + project + creator + optional assignee.
        return await self.session.scalar(
            select(Task)
            .join(Project, Project.id == Task.project_id)
            .join(creator, creator.id == Task.creator_id)
            .outerjoin(assignee, assignee.id == Task.assignee_id)
            .join(ProjectMember, ProjectMember.project_id == Task.project_id)
            .where(Task.id == task_id, ProjectMember.user_id == user_id)
            .options(
                contains_eager(Task.project),
                contains_eager(Task.creator, alias=creator),
                contains_eager(Task.assignee, alias=assignee),
                selectinload(Task.tags),
            )
        )

    async def list_detailed(
        self,
        user_id: UUID,
        filters: TaskFilters,
        page: int,
        page_size: int,
    ) -> tuple[list[Task], int]:
        creator = aliased(User, name="creator")
        assignee = aliased(User, name="assignee")
        conditions = self._filter_conditions(filters)
        membership_condition = and_(
            ProjectMember.project_id == Task.project_id,
            ProjectMember.user_id == user_id,
        )

        count = await self.session.scalar(
            select(func.count(Task.id))
            .select_from(Task)
            .join(ProjectMember, membership_condition)
            .where(*conditions)
        )

        sort_columns = {
            "created_at": Task.created_at.asc(),
            "-created_at": Task.created_at.desc(),
            "due_at": Task.due_at.asc().nulls_last(),
            "-due_at": Task.due_at.desc().nulls_last(),
        }
        statement = (
            select(Task)
            .join(Project, Project.id == Task.project_id)
            .join(creator, creator.id == Task.creator_id)
            .outerjoin(assignee, assignee.id == Task.assignee_id)
            .join(ProjectMember, membership_condition)
            .where(*conditions)
            .options(
                contains_eager(Task.project),
                contains_eager(Task.creator, alias=creator),
                contains_eager(Task.assignee, alias=assignee),
                selectinload(Task.tags),
            )
            .order_by(sort_columns[filters.sort], Task.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.scalars(statement)
        return list(result.unique()), int(count or 0)

    async def stats(self, project_id: UUID) -> dict[str, Any]:
        status_rows = await self.session.execute(
            select(Task.status, func.count(Task.id))
            .where(Task.project_id == project_id)
            .group_by(Task.status)
        )
        priority_rows = await self.session.execute(
            select(Task.priority, func.count(Task.id))
            .where(Task.project_id == project_id)
            .group_by(Task.priority)
        )
        overdue = await self.session.scalar(
            select(func.count(Task.id)).where(
                Task.project_id == project_id,
                Task.due_at < datetime.now(UTC),
                Task.status.notin_([TaskStatus.DONE, TaskStatus.CANCELLED]),
            )
        )
        assignee_rows = await self.session.execute(
            select(User.id, User.display_name, func.count(Task.id).label("task_count"))
            .join(Task, Task.assignee_id == User.id)
            .where(Task.project_id == project_id)
            .group_by(User.id, User.display_name)
            .order_by(func.count(Task.id).desc(), User.display_name)
        )
        return {
            "by_status": {row[0].value: row[1] for row in status_rows},
            "by_priority": {row[0].value: row[1] for row in priority_rows},
            "overdue": int(overdue or 0),
            "by_assignee": [
                {"user_id": row[0], "display_name": row[1], "task_count": row[2]}
                for row in assignee_rows
            ],
        }


class CommentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, comment: Comment) -> None:
        self.session.add(comment)
        await self.session.flush()

    async def get(self, comment_id: UUID) -> Comment | None:
        return await self.session.scalar(
            select(Comment)
            .where(Comment.id == comment_id)
            .options(selectinload(Comment.task), selectinload(Comment.author))
        )

    async def list_for_task(self, task_id: UUID) -> list[Comment]:
        # Second JOIN used by the API: comments + tasks + authors.
        result = await self.session.scalars(
            select(Comment)
            .join(Comment.task)
            .join(Comment.author)
            .where(Comment.task_id == task_id)
            .options(contains_eager(Comment.task), contains_eager(Comment.author))
            .order_by(Comment.created_at)
        )
        return list(result.unique())

    async def delete(self, comment: Comment) -> None:
        await self.session.delete(comment)
