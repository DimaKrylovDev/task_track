from __future__ import annotations

from uuid import UUID

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.db.models import Project, ProjectMember
from app.domain.enums import ProjectRole
from app.repositories.uow import SqlAlchemyUnitOfWork


class ProjectService:
    def __init__(self, uow: SqlAlchemyUnitOfWork) -> None:
        self.uow = uow

    async def _require_access(self, project_id: UUID, user_id: UUID) -> Project:
        project = await self.uow.projects.get_accessible(project_id, user_id)
        if project is None:
            raise NotFoundError("Project was not found")
        return project

    async def _require_owner(self, project_id: UUID, user_id: UUID) -> Project:
        project = await self._require_access(project_id, user_id)
        if project.owner_id != user_id:
            raise ForbiddenError("Only the project owner can perform this operation")
        return project

    async def create(
        self, user_id: UUID, name: str, description: str | None
    ) -> Project:
        async with self.uow:
            owner = await self.uow.users.get(user_id)
            if owner is None:
                raise NotFoundError("User was not found")
            project = Project(
                name=name.strip(), description=description, owner_id=user_id, owner=owner
            )
            await self.uow.projects.add(project)
            await self.uow.projects.add_member(
                ProjectMember(project_id=project.id, user_id=user_id, role=ProjectRole.OWNER)
            )
            await self.uow.commit()
            return project

    async def list(self, user_id: UUID) -> list[Project]:
        async with self.uow:
            return await self.uow.projects.list_accessible(user_id)

    async def get(self, project_id: UUID, user_id: UUID) -> Project:
        async with self.uow:
            return await self._require_access(project_id, user_id)

    async def update(
        self, project_id: UUID, user_id: UUID, name: str, description: str | None
    ) -> Project:
        async with self.uow:
            project = await self._require_owner(project_id, user_id)
            project.name = name.strip()
            project.description = description
            await self.uow.commit()
            return project

    async def delete(self, project_id: UUID, user_id: UUID) -> None:
        async with self.uow:
            project = await self._require_owner(project_id, user_id)
            await self.uow.projects.delete(project)
            await self.uow.commit()

    async def list_members(self, project_id: UUID, user_id: UUID) -> list[ProjectMember]:
        async with self.uow:
            await self._require_access(project_id, user_id)
            return await self.uow.projects.list_members(project_id)

    async def add_member(
        self, project_id: UUID, actor_id: UUID, member_user_id: UUID
    ) -> ProjectMember:
        async with self.uow:
            await self._require_owner(project_id, actor_id)
            if await self.uow.users.get(member_user_id) is None:
                raise NotFoundError("User was not found")
            if await self.uow.projects.get_membership(project_id, member_user_id):
                raise ConflictError("User is already a project member")
            member = ProjectMember(
                project_id=project_id, user_id=member_user_id, role=ProjectRole.MEMBER
            )
            await self.uow.projects.add_member(member)
            members = await self.uow.projects.list_members(project_id)
            await self.uow.commit()
            return next(item for item in members if item.user_id == member_user_id)

    async def remove_member(
        self, project_id: UUID, actor_id: UUID, member_user_id: UUID
    ) -> None:
        async with self.uow:
            await self._require_owner(project_id, actor_id)
            member = await self.uow.projects.get_membership(project_id, member_user_id)
            if member is None:
                raise NotFoundError("Project member was not found")
            if member.role == ProjectRole.OWNER:
                raise ConflictError("The project owner cannot be removed")
            await self.uow.projects.unassign_member_tasks(project_id, member_user_id)
            await self.uow.projects.remove_member(member)
            await self.uow.commit()
