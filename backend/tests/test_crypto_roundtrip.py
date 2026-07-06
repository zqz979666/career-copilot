"""Tests for the OAuth-token encryption helpers (v0.8).

Ensures OAuth tokens are round-trippable through Fernet and that:

- empty strings pass through untouched (used for absent refresh tokens);
- the dev key derived from ``JWT_SECRET_KEY`` produces a stable Fernet
  (so tests / local runs work without ``INTEGRATION_ENCRYPTION_KEY``);
- an explicit ``INTEGRATION_ENCRYPTION_KEY`` takes precedence.
"""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.config import get_settings
from app.security import crypto


@pytest.fixture(autouse=True)
def _reset_cache():
    crypto.reset_cache_for_tests()
    settings = get_settings()
    original = settings.integration_encryption_key
    yield
    settings.integration_encryption_key = original
    crypto.reset_cache_for_tests()


def test_encrypt_decrypt_roundtrip_with_derived_dev_key() -> None:
    get_settings().integration_encryption_key = ""
    ct = crypto.encrypt_token("gho_super_secret_token")
    assert ct
    assert ct != "gho_super_secret_token"  # not plaintext
    assert crypto.decrypt_token(ct) == "gho_super_secret_token"


def test_encrypt_empty_returns_empty() -> None:
    assert crypto.encrypt_token("") == ""
    assert crypto.decrypt_token("") == ""


def test_explicit_key_takes_precedence_over_derived() -> None:
    explicit = Fernet.generate_key().decode("utf-8")
    get_settings().integration_encryption_key = explicit
    crypto.reset_cache_for_tests()
    ct = crypto.encrypt_token("payload-A")
    assert crypto.decrypt_token(ct) == "payload-A"

    # After swapping the key, previous ciphertext should no longer be decryptable.
    get_settings().integration_encryption_key = Fernet.generate_key().decode("utf-8")
    crypto.reset_cache_for_tests()
    with pytest.raises(crypto.TokenCryptoError):
        crypto.decrypt_token(ct)


def test_invalid_key_falls_back_to_derived() -> None:
    # A garbage key should NOT crash boot — it degrades to the dev-derived key.
    get_settings().integration_encryption_key = "this-is-not-a-fernet-key"
    crypto.reset_cache_for_tests()
    ct = crypto.encrypt_token("payload-B")
    assert crypto.decrypt_token(ct) == "payload-B"
