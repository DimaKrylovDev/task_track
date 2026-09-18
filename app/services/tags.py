from __future__ import annotations

from uuid import UUID

from app.core.exceptions import ConflictError, NotFoundError
from app.db.models import Tag
from app.repositories.uow import SqlAlchemyUnitOfWork


class TagService:
    def __init__(self, uow: SqlAlchemyUnitOfWork) -> None:
        self.uow = uow

    async def _require_member(self, project_id: UUID, user_id: UUID) -> None:
        if await self.uow.projects.get_membership(project_id, user_id) is None:
            raise NotFoundError("Project was not found")

    async def create(
        self, user_id: UUID, project_id: UUID, name: str, color: str
    ) -> Tag:
        async with self.uow:
            await self._require_member(project_id, user_id)
            if await self.uow.tags.get_by_name(project_id, name):
                raise ConflictError("A tag with this name already exists in the project")
            tag = Tag(project_id=project_id, name=name.strip(), color=color.upper())
            await self.uow.tags.add(tag)
            await self.uow.commit()
            return tag

    async def list(self, user_id: UUID, project_id: UUID) -> list[Tag]:
        async with self.uow:
            await self._require_member(project_id, user_id)
            return await self.uow.tags.list_for_project(project_id)

    async def get(self, user_id: UUID, tag_id: UUID) -> Tag:
        async with self.uow:
            tag = await self.uow.tags.get(tag_id)
            if tag is None:
                raise NotFoundError("Tag was not found")
            await self._require_member(tag.project_id, user_id)
            return tag

    async def update(self, user_id: UUID, tag_id: UUID, name: str, color: str) -> Tag:
        async with self.uow:
            tag = await self.uow.tags.get(tag_id)
            if tag is None:
                raise NotFoundError("Tag was not found")
            await self._require_member(tag.project_id, user_id)
            duplicate = await self.uow.tags.get_by_name(tag.project_id, name)
            if duplicate is not None and duplicate.id != tag.id:
                raise ConflictError("A tag with this name already exists in the project")
            tag.name = name.strip()
            tag.color = color.upper()
            await self.uow.commit()
            return tag

    async def delete(self, user_id: UUID, tag_id: UUID) -> None:
        async with self.uow:
            tag = await self.uow.tags.get(tag_id)
            if tag is None:
                raise NotFoundError("Tag was not found")
            await self._require_member(tag.project_id, user_id)
            await self.uow.tags.delete(tag)
            await self.uow.commit()
