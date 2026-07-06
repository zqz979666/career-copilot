"""Tests for the GitHub Data Minimizer (extract_pr_minimal / extract_push_minimal)
and the ``profile_merge`` PR→Candidate / push→Candidate builders (v0.8).

Two guarantees under test:

1. **Data minimization** — diff hunks, review comments, reviewers, and file
   trees never leave the extractor. Only the whitelisted fields survive.
2. **Idempotency contract** — every candidate carries a ``source_ref`` prefixed
   ``github:pr:`` or ``github:repo:`` / ``github:commit:`` so the Profile
   Engine can dedupe replays without touching ``occurrences``.
"""
from __future__ import annotations

from app.config import get_settings
from app.integrations.github import extract_pr_minimal, extract_push_minimal
from app.services import profile_merge as pm


def _pr_payload(*, body: str = "hello", extra: dict | None = None) -> dict:
    """Simulate the pull_request webhook body — including *forbidden* fields
    like ``diff`` / ``review_comments`` to prove they are dropped."""
    payload = {
        "action": "opened",
        "pull_request": {
            "node_id": "PR_abc123",
            "number": 42,
            "title": "feat: add rate limit",
            "body": body,
            "state": "open",
            "merged": False,
            "merged_at": None,
            "html_url": "https://github.com/acme/repo/pull/42",
            "user": {"id": 999, "login": "octo"},
            # These MUST be dropped by the minimizer.
            "diff_url": "https://.../diff",
            "review_comments": [{"body": "leaks"}],
            "requested_reviewers": [{"login": "boss"}],
        },
        "repository": {"full_name": "acme/repo"},
    }
    if extra:
        payload["pull_request"].update(extra)
    return payload


def test_extract_pr_minimal_keeps_only_whitelisted_fields() -> None:
    minimal = extract_pr_minimal(_pr_payload())
    # Whitelisted fields all present.
    assert minimal["event"] == "pull_request"
    assert minimal["action"] == "opened"
    assert minimal["github_user_id"] == "999"
    assert minimal["github_login"] == "octo"
    assert minimal["node_id"] == "PR_abc123"
    assert minimal["number"] == 42
    assert minimal["title"] == "feat: add rate limit"
    assert minimal["body"] == "hello"
    assert minimal["repo_full_name"] == "acme/repo"
    assert minimal["merged"] is False
    assert minimal["html_url"].endswith("/pull/42")
    # Forbidden keys must NOT appear anywhere in the flat dict.
    forbidden = {"diff_url", "review_comments", "requested_reviewers"}
    assert forbidden.isdisjoint(minimal.keys())


def test_extract_pr_minimal_truncates_body_to_configured_limit() -> None:
    limit = get_settings().github_pr_body_max_chars
    long_body = "x" * (limit + 250)
    minimal = extract_pr_minimal(_pr_payload(body=long_body))
    assert len(minimal["body"]) == limit


def test_extract_pr_minimal_survives_missing_fields() -> None:
    minimal = extract_pr_minimal({})
    assert minimal["event"] == "pull_request"
    assert minimal["node_id"] == ""
    assert minimal["number"] == 0
    assert minimal["title"] == ""
    assert minimal["body"] == ""
    assert minimal["repo_full_name"] == ""


def test_extract_push_minimal_caps_commits_and_keeps_message_only() -> None:
    payload = {
        "repository": {"full_name": "acme/repo"},
        "sender": {"id": 42, "login": "octo"},
        "commits": [
            # 12 commits, only the first 10 should survive.
            {
                "message": f"fix: bug {i}",
                # These per-commit extras must be dropped by the minimizer.
                "added": ["src/leak.py"],
                "modified": ["src/secret.py"],
                "removed": [],
            }
            for i in range(12)
        ],
    }
    minimal = extract_push_minimal(payload)
    assert minimal["event"] == "push"
    assert minimal["repo_full_name"] == "acme/repo"
    assert minimal["github_user_id"] == "42"
    assert len(minimal["commit_messages"]) == 10
    assert minimal["commit_messages"][0] == "fix: bug 0"
    # No diff / file lists leaked in.
    assert set(minimal.keys()) == {
        "event",
        "github_user_id",
        "github_login",
        "repo_full_name",
        "commit_messages",
    }


def test_github_pr_to_candidates_shape_and_source_ref() -> None:
    minimal = extract_pr_minimal(_pr_payload(body="ship rate limiter"))
    cands = pm.github_pr_to_candidates(minimal)
    # Expect exactly two candidates: achievement (PR) + project (repo).
    types = [c.entry_type for c in cands]
    assert types == ["achievement", "project"]

    ach = cands[0]
    assert ach.source_type == "github"
    assert ach.source_ref == "github:pr:PR_abc123"
    assert "feat: add rate limit" in ach.content["summary"]
    assert ach.content["repo"] == "acme/repo"
    assert ach.content["merged"] is False

    proj = cands[1]
    assert proj.source_ref == "github:repo:acme/repo"
    assert proj.dedup_key == "acme/repo"
    assert proj.content["name"] == "acme/repo"


def test_github_pr_to_candidates_drops_when_id_or_title_missing() -> None:
    # Missing node_id → no candidates (can't dedupe).
    assert pm.github_pr_to_candidates({"title": "x"}) == []
    # Missing title → no candidates (nothing to describe).
    assert pm.github_pr_to_candidates({"node_id": "PR_1"}) == []
    # Not a dict → empty list (defensive).
    assert pm.github_pr_to_candidates(None) == []  # type: ignore[arg-type]


def test_github_push_to_candidates_first_line_only() -> None:
    payload = {
        "repo_full_name": "acme/repo",
        "commit_messages": [
            "feat: add caching\n\nSecret token: ghp_leaky_body_should_be_dropped",
            "  ",  # empty after trim → skipped
            "docs: readme",
        ],
    }
    cands = pm.github_push_to_candidates(payload)
    assert len(cands) == 2
    assert cands[0].entry_type == "achievement"
    assert cands[0].source_type == "github"
    # First-line only — leaky body dropped.
    assert cands[0].content["summary"] == "feat: add caching"
    assert "ghp_leaky_body_should_be_dropped" not in cands[0].content["summary"]
    assert cands[0].source_ref.startswith("github:commit:acme/repo:")
    assert cands[1].content["summary"] == "docs: readme"


def test_github_push_to_candidates_requires_repo_full_name() -> None:
    assert pm.github_push_to_candidates({"commit_messages": ["x"]}) == []
