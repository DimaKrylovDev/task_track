from __future__ import annotations

from uuid import UUID

from app.core.exceptions import ForbiddenError, NotFoundError
from app.db.models import Comment
from app.repositories.uow import SqlAlchemyUnitOfWork


class CommentService:
    def __init__(self, uow: SqlAlchemyUnitOfWork) -> None:
        self.uow = uow

    async def _task_for_member(self, task_id: UUID, user_id: UUID):
        task = await self.uow.tasks.get_detailed(task_id, user_id)
        if task is None:
            raise NotFoundError("Task was not found")
        return task

    async def create(self, task_id: UUID, user_id: UUID, body: str) -> Comment:
        async with self.uow:
            task = await self._task_for_member(task_id, user_id)
            author = await self.uow.users.get(user_id)
            comment = Comment(
                task=task, task_id=task_id, task_created_at=task.created_at,
                author_id=user_id, author=author, body=body.strip(),
            )
            await self.uow.comments.add(comment)
            comment.task = await self.uow.tasks.get(task_id)
            await self.uow.commit()
            return comment

    async def list(self, task_id: UUID, user_id: UUID) -> list[Comment]:
        async with self.uow:
            await self._task_for_member(task_id, user_id)
            return await self.uow.comments.list_for_task(task_id)

    async def get(self, comment_id: UUID, user_id: UUID) -> Comment:
        async with self.uow:
            comment = await self.uow.comments.get(comment_id)
            if comment is None:
                raise NotFoundError("Comment was not found")
            await self._task_for_member(comment.task_id, user_id)
            return comment

    async def update(self, comment_id: UUID, user_id: UUID, body: str) -> Comment:
        async with self.uow:
            comment = await self.uow.comments.get(comment_id)
            if comment is None:
                raise NotFoundError("Comment was not found")
            await self._task_for_member(comment.task_id, user_id)
            if comment.author_id != user_id:
                raise ForbiddenError("Only the comment author can edit it")
            comment.body = body.strip()
            await self.uow.commit()
            return comment

    async def delete(self, comment_id: UUID, user_id: UUID) -> None:
        async with self.uow:
            comment = await self.uow.comments.get(comment_id)
            if comment is None:
                raise NotFoundError("Comment was not found")
            await self._task_for_member(comment.task_id, user_id)
            if comment.author_id != user_id:
                raise ForbiddenError("Only the comment author can delete it")
            await self.uow.comments.delete(comment)
            await self.uow.commit()
