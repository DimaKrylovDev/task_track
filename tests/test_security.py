from uuid import uuid4

import pytest

from app.core.exceptions import UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_is_not_plaintext_and_verifies() -> None:
    encoded = hash_password("StrongPassword123!")
    assert encoded != "StrongPassword123!"
    assert verify_password("StrongPassword123!", encoded)
    assert not verify_password("WrongPassword", encoded)


def test_access_and_refresh_token_types_cannot_be_mixed() -> None:
    user_id = uuid4()
    access_token, _ = create_access_token(user_id)
    refresh_token, _, _ = create_refresh_token(user_id)

    assert decode_token(access_token, "access")["sub"] == str(user_id)
    assert decode_token(refresh_token, "refresh")["sub"] == str(user_id)
    with pytest.raises(UnauthorizedError):
        decode_token(access_token, "refresh")
    with pytest.raises(UnauthorizedError):
        decode_token(refresh_token, "access")
