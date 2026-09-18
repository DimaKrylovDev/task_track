from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.models import AuthSession, User
from app.repositories.uow import SqlAlchemyUnitOfWork


@dataclass(slots=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime
    token_type: str = "bearer"


class AuthService:
    def __init__(self, uow: SqlAlchemyUnitOfWork) -> None:
        self.uow = uow

    async def _issue_tokens(self, user_id: UUID) -> IssuedTokens:
        access_token, access_expires_at = create_access_token(user_id)
        refresh_token, session_id, refresh_expires_at = create_refresh_token(user_id)
        await self.uow.auth_sessions.add(
            AuthSession(id=session_id, user_id=user_id, expires_at=refresh_expires_at)
        )
        return IssuedTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=access_expires_at,
            refresh_expires_at=refresh_expires_at,
        )

    async def register(
        self, email: str, display_name: str, password: str
    ) -> tuple[User, IssuedTokens]:
        normalized_email = email.strip().lower()
        async with self.uow:
            if await self.uow.users.get_by_email(normalized_email):
                raise ConflictError("A user with this email already exists")
            user = User(
                email=normalized_email,
                display_name=display_name.strip(),
                password_hash=hash_password(password),
            )
            await self.uow.users.add(user)
            tokens = await self._issue_tokens(user.id)
            await self.uow.commit()
            return user, tokens

    async def login(self, email: str, password: str) -> tuple[User, IssuedTokens]:
        async with self.uow:
            user = await self.uow.users.get_by_email(email.strip().lower())
            if user is None or not verify_password(password, user.password_hash):
                raise UnauthorizedError("Invalid email or password")
            tokens = await self._issue_tokens(user.id)
            await self.uow.commit()
            return user, tokens

    async def refresh(self, refresh_token: str) -> IssuedTokens:
        payload = decode_token(refresh_token, "refresh")
        user_id = UUID(payload["sub"])
        session_id = UUID(payload["jti"])
        async with self.uow:
            auth_session = await self.uow.auth_sessions.get_for_update(session_id)
            now = datetime.now(UTC)
            if (
                auth_session is None
                or auth_session.user_id != user_id
                or auth_session.revoked_at is not None
                or auth_session.expires_at <= now
            ):
                raise UnauthorizedError("Refresh session is no longer active")
            auth_session.revoked_at = now
            tokens = await self._issue_tokens(user_id)
            await self.uow.commit()
            return tokens

    async def logout(self, refresh_token: str, current_user_id: UUID) -> None:
        payload = decode_token(refresh_token, "refresh")
        session_id = UUID(payload["jti"])
        user_id = UUID(payload["sub"])
        if user_id != current_user_id:
            raise UnauthorizedError("Refresh token belongs to another user")
        async with self.uow:
            auth_session = await self.uow.auth_sessions.get_for_update(session_id)
            if auth_session is None or auth_session.user_id != user_id:
                raise UnauthorizedError("Refresh session was not found")
            if auth_session.revoked_at is None:
                auth_session.revoked_at = datetime.now(UTC)
            await self.uow.commit()
