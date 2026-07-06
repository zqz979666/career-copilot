"""Smoke test: the app can be imported without a running database.

We can't do a full HTTP roundtrip against `/api/v1/generate` without a live LLM
key + DB, so this test just verifies the module tree wires correctly and every
expected endpoint is exposed in the OpenAPI schema.
"""
from __future__ import annotations


def test_import_app_module() -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app()
    assert app.title == "AI Career Copilot API"

    client = TestClient(app)
    schema = client.get("/openapi.json").json()
    paths = set(schema["paths"].keys())

    expected = {
        "/health",
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/me",
        "/api/v1/generate",
        "/api/v1/generate/voice",
        "/api/v1/analysis/assess",
        "/api/v1/analysis/radar",
        "/api/v1/analysis/trend",
        "/api/v1/analysis/gap",
        "/api/v1/jobs/kit",
        "/api/v1/jobs/kit/{kit_id}",
        "/api/v1/jobs/debrief",
        "/api/v1/documents/upload",
        "/api/v1/reports/monthly",
        "/api/v1/trust/level",
        "/api/v1/history",
        "/api/v1/history/{generation_id}",
        "/api/v1/profile",
        "/api/v1/profile/resume",
        "/api/v1/settings",
        # v0.8 GitHub OAuth + webhooks + integrations
        "/api/v1/oauth/github/authorize",
        "/api/v1/oauth/github/callback",
        "/api/v1/oauth/github/callback/redirect",
        "/api/v1/oauth/calendar/authorize",
        "/api/v1/oauth/calendar/callback",
        "/api/v1/oauth/jira/authorize",
        "/api/v1/oauth/jira/callback",
        "/api/v1/oauth",
        "/api/v1/oauth/{provider}",
        "/api/v1/oauth/github/sync",
        "/api/v1/webhooks/github",
        "/api/v1/webhooks/calendar",
        "/api/v1/webhooks/jira",
        "/api/v1/integrations/events",
    }
    missing = expected - paths
    assert not missing, f"missing endpoints: {missing}"
