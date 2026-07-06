"""GitHub OAuth + REST client + Webhook signature verifier (v0.8).

Design goals:

- **Minimal scope**: only ``read:user user:email repo`` (repo is required to
  read private PR metadata; if the user only cares about public PRs the
  frontend can hand out ``public_repo`` scope instead).
- **Data minimisation**: we only surface PR title / body[:500] / repo / merge
  status. Never diff content, never review comments — see Data Minimizer in
  the technical guide (§ 6.3).
- **Fail-friendly**: without ``GITHUB_CLIENT_ID`` set, everything raises
  :class:`GitHubNotConfigured` so the API layer can respond with 503 rather
  than crashing on boot.
- **HMAC verification**: :func:`verify_webhook_signature` uses
  :func:`hmac.compare_digest` (constant-time) and validates against the
  ``X-Hub-Signature-256`` header.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)


class GitHubNotConfigured(RuntimeError):
    """Raised when GitHub OAuth credentials are missing (production safeguard)."""


class GitHubError(RuntimeError):
    """Raised when the GitHub API returns a non-2xx response."""


@dataclass
class GitHubToken:
    access_token: str
    token_type: str
    scope: str


@dataclass
class GitHubUser:
    id: str
    login: str
    name: str | None
    email: str | None


@dataclass
class GitHubPullRequest:
    """Minimal PR payload — the *only* shape that ever leaves this module."""

    node_id: str      # Idempotency key
    number: int
    title: str
    body: str          # Truncated to GITHUB_PR_BODY_MAX_CHARS
    repo_full_name: str
    state: str          # open/closed
    merged: bool
    merged_at: str | None
    html_url: str


class GitHubClient:
    """Thin async wrapper around the GitHub API v3 + OAuth flow."""

    OAUTH_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
    OAUTH_TOKEN_URL = "https://github.com/login/oauth/access_token"

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._http = http_client
        self._owns_http = http_client is None

    async def __aenter__(self) -> GitHubClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=15.0)
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    # ---------- OAuth ----------

    @staticmethod
    def build_authorize_url(state: str) -> str:
        s = get_settings()
        _require_configured(s.github_client_id)
        from urllib.parse import urlencode

        params = {
            "client_id": s.github_client_id,
            "redirect_uri": s.github_oauth_redirect_uri,
            "scope": s.github_oauth_scopes,
            "state": state,
            "allow_signup": "false",
        }
        return f"{GitHubClient.OAUTH_AUTHORIZE_URL}?{urlencode(params)}"

    @staticmethod
    def generate_state() -> str:
        """Cryptographically random CSRF token for the ``state`` param."""
        return secrets.token_urlsafe(24)

    async def exchange_code(self, code: str) -> GitHubToken:
        s = get_settings()
        _require_configured(s.github_client_id, s.github_client_secret)
        assert self._http is not None
        resp = await self._http.post(
            self.OAUTH_TOKEN_URL,
            data={
                "client_id": s.github_client_id,
                "client_secret": s.github_client_secret,
                "code": code,
                "redirect_uri": s.github_oauth_redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        if resp.status_code >= 400:
            raise GitHubError(f"exchange_failed status={resp.status_code}")
        data = resp.json()
        if "access_token" not in data:
            raise GitHubError(f"exchange_error: {data.get('error_description') or data.get('error')}")
        return GitHubToken(
            access_token=data["access_token"],
            token_type=data.get("token_type", "bearer"),
            scope=data.get("scope", ""),
        )

    # ---------- API ----------

    async def get_user(self, access_token: str) -> GitHubUser:
        data = await self._get("/user", access_token)
        return GitHubUser(
            id=str(data["id"]),
            login=data["login"],
            name=data.get("name"),
            email=data.get("email"),
        )

    async def list_user_pull_requests(
        self,
        access_token: str,
        login: str,
        *,
        limit: int = 30,
    ) -> list[GitHubPullRequest]:
        """List PRs authored by ``login`` (merged or open), newest first."""
        s = get_settings()
        max_body = s.github_pr_body_max_chars
        # /search/issues is the cheapest way to get all PRs by an author.
        q = f"is:pr author:{login} sort:updated-desc"
        # Cap page_size at GitHub's 100.
        page_size = min(limit, 100)
        data = await self._get(
            f"/search/issues?q={q}&per_page={page_size}",
            access_token,
        )
        prs: list[GitHubPullRequest] = []
        for item in (data.get("items") or [])[:limit]:
            pr = _pr_from_issue_hit(item, max_body)
            if pr is not None:
                prs.append(pr)
        return prs

    async def _get(self, path: str, access_token: str) -> dict[str, Any]:
        assert self._http is not None
        s = get_settings()
        url = f"{s.github_api_base}{path}"
        resp = await self._http.get(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        if resp.status_code >= 400:
            raise GitHubError(f"github_api {path} status={resp.status_code}")
        return resp.json()


def _require_configured(*values: str) -> None:
    if any(not v for v in values):
        raise GitHubNotConfigured(
            "github_oauth_not_configured: set GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET"
        )


def _pr_from_issue_hit(item: dict[str, Any], body_limit: int) -> GitHubPullRequest | None:
    """Convert a /search/issues hit (PR flavour) into our minimal shape."""
    pr_info = item.get("pull_request") or {}
    if not pr_info:
        return None
    repo_url = item.get("repository_url") or ""
    repo_full_name = "/".join(repo_url.rsplit("/", 2)[-2:]) if repo_url else ""
    return GitHubPullRequest(
        node_id=str(item.get("node_id") or item.get("id") or item.get("url")),
        number=int(item.get("number") or 0),
        title=str(item.get("title") or ""),
        body=(item.get("body") or "")[:body_limit],
        repo_full_name=repo_full_name,
        state=str(item.get("state") or "open"),
        merged=bool(pr_info.get("merged_at")),
        merged_at=pr_info.get("merged_at"),
        html_url=str(item.get("html_url") or ""),
    )


def verify_webhook_signature(body: bytes, signature_header: str) -> bool:
    """Validate ``X-Hub-Signature-256`` against ``GITHUB_WEBHOOK_SECRET``.

    Returns ``False`` when the secret is unset, when the header is missing /
    malformed, or when the HMAC does not match. Uses constant-time compare.
    """
    settings = get_settings()
    secret = settings.github_webhook_secret
    if not secret:
        return False
    if not signature_header or "=" not in signature_header:
        return False
    algo, provided = signature_header.split("=", 1)
    if algo != "sha256":
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    try:
        return hmac.compare_digest(expected, provided)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return False


def extract_pr_minimal(payload: dict[str, Any]) -> dict[str, Any]:
    """Turn a `pull_request` webhook body into the minimal shape we accept.

    Discards diffs, review comments, and reviewers — only keeps the fields
    that the Data Minimizer approves for the Profile Engine.
    """
    settings = get_settings()
    pr = payload.get("pull_request") or {}
    repo = payload.get("repository") or {}
    user = pr.get("user") or {}
    body = (pr.get("body") or "")[: settings.github_pr_body_max_chars]
    return {
        "event": "pull_request",
        "action": payload.get("action"),
        "github_user_id": str(user.get("id") or ""),
        "github_login": user.get("login"),
        "node_id": str(pr.get("node_id") or ""),
        "number": int(pr.get("number") or 0),
        "title": pr.get("title", ""),
        "body": body,
        "repo_full_name": repo.get("full_name", ""),
        "state": pr.get("state", "open"),
        "merged": bool(pr.get("merged")),
        "merged_at": pr.get("merged_at"),
        "html_url": pr.get("html_url", ""),
    }


def extract_push_minimal(payload: dict[str, Any]) -> dict[str, Any]:
    """Only commit messages (first 10) — no diff, no file lists."""
    repo = payload.get("repository") or {}
    sender = payload.get("sender") or {}
    commits = payload.get("commits") or []
    return {
        "event": "push",
        "github_user_id": str(sender.get("id") or ""),
        "github_login": sender.get("login"),
        "repo_full_name": repo.get("full_name", ""),
        "commit_messages": [
            (c.get("message") or "").strip()
            for c in commits[:10]
            if isinstance(c, dict)
        ],
    }
