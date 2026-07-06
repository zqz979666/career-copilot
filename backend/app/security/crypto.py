"""Encryption helpers for storing 3rd-party OAuth tokens at rest.

Design (v0.8):

- OAuth access/refresh tokens are **never** stored in plaintext. They travel
  through :func:`encrypt_token` before landing in ``oauth_connections`` and
  through :func:`decrypt_token` on the way out.
- We use ``cryptography.fernet`` (AES-128-CBC + HMAC-SHA256, versioned) — the
  standard "authenticated symmetric encryption" primitive in the Python
  ecosystem.
- The key is taken from ``INTEGRATION_ENCRYPTION_KEY`` (a Fernet key: 32-byte
  urlsafe-base64 string). If unset, we DERIVE a stable dev key from
  ``JWT_SECRET_KEY`` so tests / local runs work out of the box. Production
  MUST set an explicit key so rotating JWT doesn't invalidate stored tokens.

Rotate keys by adding old keys as trailing entries in ``MultiFernet``; a
future migration can re-encrypt legacy blobs during that window.
"""
from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


def _derive_dev_key(secret: str) -> bytes:
    """Deterministically derive a 32-byte Fernet key from ``secret`` (dev only)."""
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    settings = get_settings()
    raw = (settings.integration_encryption_key or "").strip()
    if raw:
        try:
            return Fernet(raw.encode("utf-8"))
        except Exception as e:  # noqa: BLE001
            # Fall through to dev-derivation but shout in the logs.
            from app.logging_config import get_logger

            get_logger(__name__).warning(
                "integration_key_invalid_fallback_to_derived", error=str(e)
            )
    return Fernet(_derive_dev_key(settings.jwt_secret_key))


class TokenCryptoError(Exception):
    """Raised when a stored ciphertext cannot be decrypted (rotated key, tamper, ...)."""


def encrypt_token(plaintext: str) -> str:
    """Return a base64 ciphertext of ``plaintext`` (empty string in → empty out)."""
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_token(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as e:  # pragma: no cover - defensive
        raise TokenCryptoError("token_decrypt_failed") from e


def reset_cache_for_tests() -> None:
    """Clear the Fernet cache — used by tests that mutate settings."""
    _fernet.cache_clear()
