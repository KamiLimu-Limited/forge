"""JWT token generation and validation utilities."""

import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import jwt
from jwt.exceptions import InvalidTokenError

from forge.core.config import settings


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


class TokenError(Exception):
    pass


def create_token(
    subject: str,
    token_type: TokenType,
    expires_delta: timedelta | None = None,
    additional_claims: dict[str, Any] | None = None,
) -> tuple[str, str, datetime]:
    """Create a JWT and return ``(token, jti, expires_at)``."""
    now = datetime.now(UTC)
    if expires_delta is None:
        expires_delta = (
            timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
            if token_type is TokenType.ACCESS
            else timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        )
    expire = now + expires_delta
    jti = str(uuid.uuid4())

    claims: dict[str, Any] = {
        "sub": subject,
        "type": token_type.value,
        "iat": now,
        "exp": expire,
        "jti": jti,
        **(additional_claims or {}),
    }
    token = jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, jti, expire


def create_access_token(
    user_id: uuid.UUID, additional_claims: dict[str, Any] | None = None
) -> tuple[str, str, datetime]:
    return create_token(
        str(user_id), TokenType.ACCESS, additional_claims=additional_claims
    )


def create_refresh_token(
    user_id: uuid.UUID, additional_claims: dict[str, Any] | None = None
) -> tuple[str, str, datetime]:
    return create_token(
        str(user_id), TokenType.REFRESH, additional_claims=additional_claims
    )


def decode_token(token: str) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"require": ["exp", "sub", "jti", "type"]},
        )
    except InvalidTokenError as e:
        raise TokenError(f"Invalid token: {e}") from e
    return payload


def get_token_payload(token: str, expected_type: TokenType) -> dict[str, Any]:
    payload = decode_token(token)
    if payload.get("type") != expected_type.value:
        raise TokenError(
            f"Invalid token type: expected {expected_type.value}, got {payload.get('type')}"
        )
    return payload


def get_token_subject(token: str, expected_type: TokenType) -> str:
    return str(get_token_payload(token, expected_type)["sub"])


def get_token_jti(token: str) -> str:
    return str(decode_token(token)["jti"])


def get_token_expiration(token: str) -> datetime:
    return datetime.fromtimestamp(decode_token(token)["exp"], tz=UTC)
