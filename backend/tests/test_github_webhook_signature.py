"""Tests for the GitHub webhook HMAC-SHA256 signature verifier (v0.8).

Guardrail: the verifier MUST refuse to authenticate any request when the
secret is not configured, when the algorithm prefix is wrong, or when the
digest doesn't match — using constant-time compare so timing side-channels
don't leak the secret.
"""
from __future__ import annotations

import hashlib
import hmac

import pytest

from app.config import get_settings
from app.integrations.github import verify_webhook_signature


@pytest.fixture(autouse=True)
def _restore_settings():
    settings = get_settings()
    original = settings.github_webhook_secret
    yield
    settings.github_webhook_secret = original


def _sign(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_verify_returns_false_when_secret_unset() -> None:
    get_settings().github_webhook_secret = ""
    assert verify_webhook_signature(b'{"ok":true}', "sha256=deadbeef") is False


def test_verify_returns_false_when_header_missing() -> None:
    get_settings().github_webhook_secret = "s3cret"
    assert verify_webhook_signature(b"{}", "") is False


def test_verify_returns_false_on_wrong_algo_prefix() -> None:
    get_settings().github_webhook_secret = "s3cret"
    # sha1 is deprecated for GitHub webhooks; must be rejected.
    assert verify_webhook_signature(b"{}", "sha1=00") is False


def test_verify_returns_false_on_malformed_header() -> None:
    get_settings().github_webhook_secret = "s3cret"
    assert verify_webhook_signature(b"{}", "sha256") is False


def test_verify_happy_path() -> None:
    get_settings().github_webhook_secret = "s3cret"
    body = b'{"action":"opened","number":42}'
    assert verify_webhook_signature(body, _sign("s3cret", body)) is True


def test_verify_detects_body_tamper() -> None:
    get_settings().github_webhook_secret = "s3cret"
    body = b'{"action":"opened"}'
    signature = _sign("s3cret", body)
    tampered = b'{"action":"closed"}'
    assert verify_webhook_signature(tampered, signature) is False


def test_verify_detects_wrong_secret() -> None:
    get_settings().github_webhook_secret = "s3cret"
    body = b"{}"
    # Signed with a different secret than what the server has.
    assert verify_webhook_signature(body, _sign("other", body)) is False
