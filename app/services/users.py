from __future__ import annotations

from uuid import UUID

from app.core.exceptions import ConflictError, NotFoundError
from app.db.models import User
from app.repositories.uow import SqlAlchemyUnitOfWork


class UserService:
    def __init__(self, uow: SqlAlchemyUnitOfWork) -> None:
        self.uow = uow

    async def get(self, user_id: UUID) -> User:
        async with self.uow:
            user = await self.uow.users.get(user_id)
            if user is None:
                raise NotFoundError("User was not found")
            return user

    async def update(self, user_id: UUID, email: str, display_name: str) -> User:
        normalized_email = email.strip().lower()
        async with self.uow:
            user = await self.uow.users.get(user_id)
            if user is None:
                raise NotFoundError("User was not found")
            existing = await self.uow.users.get_by_email(normalized_email)
            if existing is not None and existing.id != user_id:
                raise ConflictError("A user with this email already exists")
            user.email = normalized_email
            user.display_name = display_name.strip()
            await self.uow.commit()
            return user

    async def search(self, query: str) -> list[User]:
        async with self.uow:
            return await self.uow.users.search(query.strip())
