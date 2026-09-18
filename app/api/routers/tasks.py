from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, ReadUowDep, UowDep
from app.api.schemas import TaskCreate, TaskPage, TaskPut, TaskRead
from app.domain.enums import TaskPriority, TaskStatus
from app.repositories.sqlalchemy import TaskFilters
from app.services.tasks import TaskService

router = APIRouter(tags=["Tasks"])
SortField = Literal["created_at", "-created_at", "due_at", "-due_at"]


async def _list_tasks(
    current_user,
    uow,
    page: int,
    page_size: int,
    project_id: UUID | None,
    task_status: TaskStatus | None,
    priority: TaskPriority | None,
    assignee_id: UUID | None,
    tag_id: UUID | None,
    created_from: datetime | None,
    created_to: datetime | None,
    search: str | None,
    sort: SortField,
) -> TaskPage:
    filters = TaskFilters(
        project_id=project_id,
        status=task_status,
        priority=priority,
        assignee_id=assignee_id,
        tag_id=tag_id,
        created_from=created_from,
        created_to=created_to,
        search=search,
        sort=sort,
    )
    result = await TaskService(uow).list(current_user.id, filters, page, page_size)
    return TaskPage.model_validate(result)


@router.get("/api/tasks", response_model=TaskPage)
async def list_tasks(
    current_user: CurrentUser,
    uow: ReadUowDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    project_id: UUID | None = None,
    status: TaskStatus | None = None,
    priority: TaskPriority | None = None,
    assignee_id: UUID | None = None,
    tag_id: UUID | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    search: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    sort: SortField = "-created_at",
) -> TaskPage:
    return await _list_tasks(
        current_user, uow, page, page_size, project_id, status, priority, assignee_id,
        tag_id, created_from, created_to, search, sort
    )


@router.get("/api/projects/{project_id}/tasks", response_model=TaskPage)
async def list_project_tasks(
    project_id: UUID,
    current_user: CurrentUser,
    uow: ReadUowDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status: TaskStatus | None = None,
    priority: TaskPriority | None = None,
    assignee_id: UUID | None = None,
    tag_id: UUID | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    search: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    sort: SortField = "-created_at",
) -> TaskPage:
    return await _list_tasks(
        current_user, uow, page, page_size, project_id, status, priority, assignee_id,
        tag_id, created_from, created_to, search, sort
    )


@router.post("/api/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(body: TaskCreate, current_user: CurrentUser, uow: UowDep) -> TaskRead:
    task = await TaskService(uow).create(current_user.id, **body.model_dump())
    return TaskRead.model_validate(task)


@router.get("/api/tasks/{task_id}", response_model=TaskRead)
async def get_task(task_id: UUID, current_user: CurrentUser, uow: UowDep) -> TaskRead:
    task = await TaskService(uow).get(task_id, current_user.id)
    return TaskRead.model_validate(task)


@router.put("/api/tasks/{task_id}", response_model=TaskRead)
async def update_task(
    task_id: UUID, body: TaskPut, current_user: CurrentUser, uow: UowDep
) -> TaskRead:
    task = await TaskService(uow).update(task_id, current_user.id, **body.model_dump())
    return TaskRead.model_validate(task)


@router.delete("/api/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: UUID, current_user: CurrentUser, uow: UowDep) -> Response:
    await TaskService(uow).delete(task_id, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
