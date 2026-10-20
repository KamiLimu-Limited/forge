"""Custom column types."""

from typing import Any

from sqlalchemy import Dialect, Text
from sqlalchemy.types import TypeDecorator

from forge.core.crypto import decrypt, encrypt


class EncryptedText(TypeDecorator[str]):
    """Text column transparently encrypted at rest with Fernet."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        return encrypt(value) if value is not None else None

    def process_result_value(self, value: Any, dialect: Dialect) -> str | None:
        return decrypt(value) if value is not None else None
