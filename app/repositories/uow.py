from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.sqlalchemy import (
    AuthSessionRepository,
    CommentRepository,
    ProjectRepository,
    TagRepository,
    TaskRepository,
    UserRepository,
)


class SqlAlchemyUnitOfWork:
    """Owns one SQLAlchemy session and one transaction per service call."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self.session: AsyncSession

    async def __aenter__(self) -> "SqlAlchemyUnitOfWork":
        self.session = self.session_factory()
        self.users = UserRepository(self.session)
        self.auth_sessions = AuthSessionRepository(self.session)
        self.projects = ProjectRepository(self.session)
        self.tasks = TaskRepository(self.session)
        self.tags = TagRepository(self.session)
        self.comments = CommentRepository(self.session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            await self.session.rollback()
        await self.session.close()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
