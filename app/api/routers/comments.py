from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, UowDep
from app.api.schemas import CommentCreate, CommentPut, CommentRead
from app.services.comments import CommentService

router = APIRouter(tags=["Comments"])


@router.get("/api/tasks/{task_id}/comments", response_model=list[CommentRead])
async def list_comments(
    task_id: UUID, current_user: CurrentUser, uow: UowDep
) -> list[CommentRead]:
    comments = await CommentService(uow).list(task_id, current_user.id)
    return [CommentRead.model_validate(comment) for comment in comments]


@router.post(
    "/api/tasks/{task_id}/comments",
    response_model=CommentRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_comment(
    task_id: UUID, body: CommentCreate, current_user: CurrentUser, uow: UowDep
) -> CommentRead:
    comment = await CommentService(uow).create(task_id, current_user.id, body.body)
    return CommentRead.model_validate(comment)


@router.get("/api/comments/{comment_id}", response_model=CommentRead)
async def get_comment(
    comment_id: UUID, current_user: CurrentUser, uow: UowDep
) -> CommentRead:
    return CommentRead.model_validate(
        await CommentService(uow).get(comment_id, current_user.id)
    )


@router.put("/api/comments/{comment_id}", response_model=CommentRead)
async def update_comment(
    comment_id: UUID, body: CommentPut, current_user: CurrentUser, uow: UowDep
) -> CommentRead:
    comment = await CommentService(uow).update(comment_id, current_user.id, body.body)
    return CommentRead.model_validate(comment)


@router.delete("/api/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_id: UUID, current_user: CurrentUser, uow: UowDep
) -> Response:
    await CommentService(uow).delete(comment_id, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

