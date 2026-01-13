from __future__ import annotations

import base64
import hashlib
from typing import Final

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


_ENCODING: Final[str] = "utf-8"


def _derive_fernet_key_from_secret(secret: str) -> str:
    """Derive a deterministic Fernet key from a secret string.

    This is a *fallback* for dev/local runs when CREDENTIAL_ENCRYPTION_KEY isn't set.
    In production you must provide CREDENTIAL_ENCRYPTION_KEY explicitly.
    """

    digest = hashlib.sha256(secret.encode(_ENCODING)).digest()  # 32 bytes
    return base64.urlsafe_b64encode(digest).decode(_ENCODING)  # 44 chars


def get_fernet() -> Fernet:
    key = getattr(settings, "CREDENTIAL_ENCRYPTION_KEY", "") or ""
    key = key.strip()
    if not key:
        # Fallback: derive from Django SECRET_KEY (stable if SECRET_KEY stable).
        key = _derive_fernet_key_from_secret(settings.SECRET_KEY)
    return Fernet(key.encode(_ENCODING))


def encrypt_str(value: str) -> str:
    token = get_fernet().encrypt(value.encode(_ENCODING))
    return token.decode(_ENCODING)


def decrypt_str(token: str) -> str:
    try:
        data = get_fernet().decrypt(token.encode(_ENCODING))
    except InvalidToken:
        # Wrong key / corrupted token
        raise ValueError("Invalid encrypted token (wrong key or corrupted data)")
    return data.decode(_ENCODING)

