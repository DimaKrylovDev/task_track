from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import UnauthorizedError
from app.core.security import decode_token
from app.db.models import User
from app.db.session import replica_session_factory, session_factory
from app.repositories.uow import SqlAlchemyUnitOfWork
from app.services.users import UserService

bearer_scheme = HTTPBearer(auto_error=False)


def get_uow() -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(session_factory)


def get_read_uow() -> SqlAlchemyUnitOfWork:
    """Unit of work for SELECT-only endpoints backed by the streaming replica."""
    return SqlAlchemyUnitOfWork(replica_session_factory)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    uow: Annotated[SqlAlchemyUnitOfWork, Depends(get_uow)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError("Bearer access token is required")
    payload = decode_token(credentials.credentials, "access")
    return await UserService(uow).get(UUID(payload["sub"]))


UowDep = Annotated[SqlAlchemyUnitOfWork, Depends(get_uow)]
ReadUowDep = Annotated[SqlAlchemyUnitOfWork, Depends(get_read_uow)]
CurrentUser = Annotated[User, Depends(get_current_user)]
