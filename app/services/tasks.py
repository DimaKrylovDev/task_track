from __future__ import annotations

from datetime import datetime
from math import ceil
from uuid import UUID

from app.core.exceptions import AppError, NotFoundError
from app.db.models import Task
from app.domain.enums import TaskPriority, TaskStatus
from app.repositories.sqlalchemy import TaskFilters
from app.repositories.uow import SqlAlchemyUnitOfWork


class TaskService:
    def __init__(self, uow: SqlAlchemyUnitOfWork) -> None:
        self.uow = uow

    async def _require_member(self, project_id: UUID, user_id: UUID) -> None:
        if await self.uow.projects.get_membership(project_id, user_id) is None:
            raise NotFoundError("Project was not found")

    async def _validated_assignee(self, project_id: UUID, assignee_id: UUID | None):
        if assignee_id is None:
            return None
        if await self.uow.projects.get_membership(project_id, assignee_id) is None:
            raise NotFoundError("Assignee is not a member of this project")
        return await self.uow.users.get(assignee_id)

    async def _validated_tags(self, project_id: UUID, tag_ids: list[UUID]):
        unique_ids = list(dict.fromkeys(tag_ids))
        tags = await self.uow.tags.get_many(unique_ids)
        if len(tags) != len(unique_ids) or any(tag.project_id != project_id for tag in tags):
            raise NotFoundError("One or more tags do not belong to this project")
        return tags

    async def create(
        self,
        user_id: UUID,
        project_id: UUID,
        title: str,
        description: str | None,
        status: TaskStatus,
        priority: TaskPriority,
        assignee_id: UUID | None,
        due_at: datetime | None,
        tag_ids: list[UUID],
    ) -> Task:
        async with self.uow:
            await self._require_member(project_id, user_id)
            assignee = await self._validated_assignee(project_id, assignee_id)
            tags = await self._validated_tags(project_id, tag_ids)
            task = Task(
                project_id=project_id,
                creator_id=user_id,
                assignee_id=assignee_id,
                title=title.strip(),
                description=description,
                status=status,
                priority=priority,
                due_at=due_at,
                assignee=assignee,
                tags=tags,
            )
            await self.uow.tasks.add(task)
            detailed = await self.uow.tasks.get_detailed(task.id, user_id)
            await self.uow.commit()
            return detailed or task

    async def get(self, task_id: UUID, user_id: UUID) -> Task:
        async with self.uow:
            task = await self.uow.tasks.get_detailed(task_id, user_id)
            if task is None:
                raise NotFoundError("Task was not found")
            return task

    async def list(
        self, user_id: UUID, filters: TaskFilters, page: int, page_size: int
    ) -> dict:
        if (
            filters.created_from is not None
            and filters.created_to is not None
            and filters.created_from > filters.created_to
        ):
            raise AppError("created_from must not be later than created_to")
        async with self.uow:
            items, total = await self.uow.tasks.list_detailed(user_id, filters, page, page_size)
            return {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": ceil(total / page_size) if total else 0,
            }

    async def update(
        self,
        task_id: UUID,
        user_id: UUID,
        title: str,
        description: str | None,
        status: TaskStatus,
        priority: TaskPriority,
        assignee_id: UUID | None,
        due_at: datetime | None,
        tag_ids: list[UUID],
    ) -> Task:
        async with self.uow:
            task = await self.uow.tasks.get_detailed(task_id, user_id)
            if task is None:
                raise NotFoundError("Task was not found")
            task.title = title.strip()
            task.description = description
            task.status = status
            task.priority = priority
            task.assignee_id = assignee_id
            task.assignee = await self._validated_assignee(task.project_id, assignee_id)
            task.due_at = due_at
            task.tags = await self._validated_tags(task.project_id, tag_ids)
            await self.uow.commit()
            return task

    async def delete(self, task_id: UUID, user_id: UUID) -> None:
        async with self.uow:
            task = await self.uow.tasks.get_detailed(task_id, user_id)
            if task is None:
                raise NotFoundError("Task was not found")
            await self.uow.tasks.delete(task)
            await self.uow.commit()

    async def stats(self, project_id: UUID, user_id: UUID) -> dict:
        async with self.uow:
            await self._require_member(project_id, user_id)
            return await self.uow.tasks.stats(project_id)
