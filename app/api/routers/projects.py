from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, UowDep
from app.api.schemas import (
    MemberCreate,
    MemberRead,
    ProjectCreate,
    ProjectPut,
    ProjectRead,
    ProjectStats,
)
from app.services.projects import ProjectService
from app.services.tasks import TaskService

router = APIRouter(prefix="/api/projects", tags=["Projects"])


@router.get("", response_model=list[ProjectRead])
async def list_projects(current_user: CurrentUser, uow: UowDep) -> list[ProjectRead]:
    projects = await ProjectService(uow).list(current_user.id)
    return [ProjectRead.model_validate(project) for project in projects]


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate, current_user: CurrentUser, uow: UowDep
) -> ProjectRead:
    project = await ProjectService(uow).create(current_user.id, body.name, body.description)
    return ProjectRead.model_validate(project)


@router.get("/{project_id}/members", response_model=list[MemberRead])
async def list_members(
    project_id: UUID, current_user: CurrentUser, uow: UowDep
) -> list[MemberRead]:
    members = await ProjectService(uow).list_members(project_id, current_user.id)
    return [MemberRead.model_validate(member) for member in members]


@router.post(
    "/{project_id}/members", response_model=MemberRead, status_code=status.HTTP_201_CREATED
)
async def add_member(
    project_id: UUID, body: MemberCreate, current_user: CurrentUser, uow: UowDep
) -> MemberRead:
    member = await ProjectService(uow).add_member(project_id, current_user.id, body.user_id)
    return MemberRead.model_validate(member)


@router.delete("/{project_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    project_id: UUID, user_id: UUID, current_user: CurrentUser, uow: UowDep
) -> Response:
    await ProjectService(uow).remove_member(project_id, current_user.id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{project_id}/stats", response_model=ProjectStats)
async def project_stats(
    project_id: UUID, current_user: CurrentUser, uow: UowDep
) -> ProjectStats:
    result = await TaskService(uow).stats(project_id, current_user.id)
    return ProjectStats.model_validate(result)


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(project_id: UUID, current_user: CurrentUser, uow: UowDep) -> ProjectRead:
    project = await ProjectService(uow).get(project_id, current_user.id)
    return ProjectRead.model_validate(project)


@router.put("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: UUID, body: ProjectPut, current_user: CurrentUser, uow: UowDep
) -> ProjectRead:
    project = await ProjectService(uow).update(
        project_id, current_user.id, body.name, body.description
    )
    return ProjectRead.model_validate(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: UUID, current_user: CurrentUser, uow: UowDep) -> Response:
    await ProjectService(uow).delete(project_id, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

