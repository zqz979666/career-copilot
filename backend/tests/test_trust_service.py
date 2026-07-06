"""Tests for TrustService (v1.0)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import pytest

import app.services.trust_service as trust_module
from app.services.trust_service import TrustService


@dataclass
class _FakeRow:
    level: int
    level_changed_at: datetime


class _FakeRepo:
    def __init__(self, _session) -> None:  # noqa: ANN001
        pass

    async def get_or_create(self, _user_id):  # noqa: ANN001
        return _FakeRow(level=1, level_changed_at=datetime(2026, 7, 1, tzinfo=UTC))

    async def update_level(self, _user_id, level):  # noqa: ANN001
        return _FakeRow(level=level, level_changed_at=datetime(2026, 7, 6, tzinfo=UTC))


class _FakeSessionFactory:
    async def __aenter__(self):  # noqa: ANN204
        return object()

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN204
        return False

    def __call__(self):
        return self


async def test_get_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trust_module, "TrustLadderRepository", _FakeRepo)
    svc = TrustService(session_factory=_FakeSessionFactory())  # type: ignore[arg-type]

    out = await svc.get_level(uuid4())
    assert out["level"] == 1
    assert out["changed_at"].startswith("2026-07-01")


async def test_set_level_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trust_module, "TrustLadderRepository", _FakeRepo)
    svc = TrustService(session_factory=_FakeSessionFactory())  # type: ignore[arg-type]

    out = await svc.set_level(uuid4(), 3)
    assert out["level"] == 3
    assert out["changed_at"].startswith("2026-07-06")


async def test_set_level_rejects_invalid() -> None:
    svc = TrustService(session_factory=_FakeSessionFactory())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="level_must_be_1_2_3"):
        await svc.set_level(uuid4(), 0)
