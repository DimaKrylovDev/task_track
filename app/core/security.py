from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
from pwdlib import PasswordHash

from app.core.config import settings
from app.core.exceptions import UnauthorizedError

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    return password_hash.verify(password, encoded)


def create_access_token(user_id: UUID) -> tuple[str, datetime]:
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.access_token_minutes)
    payload = {
        "sub": str(user_id),
        "type": "access",
        "iat": datetime.now(UTC),
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm), expires_at


def create_refresh_token(
    user_id: UUID, session_id: UUID | None = None
) -> tuple[str, UUID, datetime]:
    session_id = session_id or uuid4()
    expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_days)
    payload = {
        "sub": str(user_id),
        "jti": str(session_id),
        "type": "refresh",
        "iat": datetime.now(UTC),
        "exp": expires_at,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, session_id, expires_at


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != expected_type or not payload.get("sub"):
            raise UnauthorizedError("Invalid token type")
        UUID(payload["sub"])
        if expected_type == "refresh":
            UUID(payload.get("jti", ""))
        return payload
    except UnauthorizedError:
        raise
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise UnauthorizedError("Invalid or expired token") from exc
