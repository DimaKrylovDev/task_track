from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, UowDep
from app.api.schemas import TagCreate, TagPut, TagRead
from app.services.tags import TagService

router = APIRouter(prefix="/api/tags", tags=["Tags"])


@router.get("", response_model=list[TagRead])
async def list_tags(project_id: UUID, current_user: CurrentUser, uow: UowDep) -> list[TagRead]:
    tags = await TagService(uow).list(current_user.id, project_id)
    return [TagRead.model_validate(tag) for tag in tags]


@router.post("", response_model=TagRead, status_code=status.HTTP_201_CREATED)
async def create_tag(body: TagCreate, current_user: CurrentUser, uow: UowDep) -> TagRead:
    tag = await TagService(uow).create(current_user.id, body.project_id, body.name, body.color)
    return TagRead.model_validate(tag)


@router.get("/{tag_id}", response_model=TagRead)
async def get_tag(tag_id: UUID, current_user: CurrentUser, uow: UowDep) -> TagRead:
    return TagRead.model_validate(await TagService(uow).get(current_user.id, tag_id))


@router.put("/{tag_id}", response_model=TagRead)
async def update_tag(
    tag_id: UUID, body: TagPut, current_user: CurrentUser, uow: UowDep
) -> TagRead:
    tag = await TagService(uow).update(current_user.id, tag_id, body.name, body.color)
    return TagRead.model_validate(tag)


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(tag_id: UUID, current_user: CurrentUser, uow: UowDep) -> Response:
    await TagService(uow).delete(current_user.id, tag_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

