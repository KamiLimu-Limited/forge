"""Symmetric encryption for sensitive data at rest."""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet

from forge.core.config import settings


@lru_cache
def get_fernet() -> Fernet:
    key = (
        settings.DATA_ENCRYPTION_KEY
        or base64.urlsafe_b64encode(
            hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        ).decode()
    )
    return Fernet(key)


def encrypt(value: str) -> str:
    return get_fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return get_fernet().decrypt(value.encode()).decode()
