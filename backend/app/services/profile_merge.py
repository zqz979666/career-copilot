"""Pure logic for the Profile Engine (entity alignment + confidence + compile).

Kept dependency-free (no DB, no LLM, no I/O) so it is cheap to unit test and
reason about. :class:`ProfileEngine` orchestrates these helpers around the DB.

Vocabulary
----------
- *candidate*  : a normalised fact derived from an ``extracted_data`` row or a
  parsed resume, ready to be merged into ``profile_entries``.
- *dedup_key*  : the normalised identity of an entry within its ``entry_type``;
  two candidates with the same (type, key) are the *same* real-world entity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# Base confidence by provenance. Higher = more trustworthy source.
_SOURCE_BASE_CONFIDENCE: dict[str, float] = {
    "user_input": 0.9,     # user typed/confirmed it directly
    "resume_import": 0.8,  # parsed from an uploaded resume
    "github": 0.9,         # (v0.8) verified third-party data
    "generation": 0.5,     # inferred as a side-effect of a generation
}
_DEFAULT_BASE_CONFIDENCE = 0.5

# extracted_data.data_type → profile_entries.entry_type
_DATA_TYPE_TO_ENTRY_TYPE: dict[str, str] = {
    "project": "project",
    "skill": "skill",
    "achievement": "achievement",
    "tech_stack": "tech",
}


@dataclass
class Candidate:
    """A normalised fact ready to merge into ``profile_entries``."""

    entry_type: str
    content: dict[str, Any]
    dedup_key: str
    source_type: str = "generation"
    source_id: Any = None  # UUID | None
    evidence_ids: list = field(default_factory=list)
    # v0.8: third-party idempotency key ("github:pr:{node_id}", ...). Enables
    # webhook retries / manual re-sync to update the same row instead of
    # producing duplicates. NULL for legacy generation/resume sources.
    source_ref: str | None = None


def normalize_name(name: str) -> str:
    """Canonical form used for skill/tech/company/role dedup keys."""
    return " ".join(name.strip().lower().split())


def _short_key(text: str, limit: int = 60) -> str:
    return normalize_name(text)[:limit]


def dedup_key_for(entry_type: str, content: dict[str, Any]) -> str:
    """Compute the dedup key for a (entry_type, content) pair."""
    if entry_type in ("skill", "tech"):
        return normalize_name(str(content.get("name", "")))
    if entry_type == "project":
        return normalize_name(str(content.get("name", "")) or str(content.get("summary", "")))
    if entry_type == "achievement":
        return _short_key(str(content.get("summary", "")))
    if entry_type in ("company", "role"):
        return normalize_name(str(content.get("name", "")) or str(content.get("title", "")))
    # Fallback: stringify the whole content.
    return _short_key(str(content))


def score_confidence(occurrences: int, source_type: str) -> float:
    """Confidence grows with corroborating observations, capped at 0.98.

    A single generation-sourced fact starts at 0.5; each additional
    corroboration adds 0.08. Resume/user/GitHub sources start higher.
    """
    base = _SOURCE_BASE_CONFIDENCE.get(source_type, _DEFAULT_BASE_CONFIDENCE)
    boosted = base + 0.08 * max(0, occurrences - 1)
    return round(min(0.98, boosted), 4)


def entry_text_for_embedding(entry_type: str, content: dict[str, Any]) -> str:
    """Flatten an entry's content into a single string for embedding."""
    if entry_type in ("skill", "tech"):
        return str(content.get("name", "")).strip()
    if entry_type == "project":
        parts = [content.get("name"), content.get("role"), content.get("summary")]
        return " ".join(str(p) for p in parts if p).strip()
    if entry_type == "achievement":
        parts = [content.get("summary"), content.get("metric")]
        return " ".join(str(p) for p in parts if p).strip()
    if entry_type in ("company", "role"):
        parts = [content.get("name"), content.get("title")]
        return " ".join(str(p) for p in parts if p).strip()
    return " ".join(str(v) for v in content.values() if v).strip()


def _clean_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def extracted_row_to_candidate(
    *, data_type: str, data_content: dict[str, Any], source_id: Any, evidence_ids: list
) -> Candidate | None:
    """Convert one ``extracted_data`` row into a merge candidate (or None)."""
    entry_type = _DATA_TYPE_TO_ENTRY_TYPE.get(data_type)
    if entry_type is None or not isinstance(data_content, dict):
        return None

    if entry_type in ("skill", "tech"):
        name = _clean_str(data_content.get("name"))
        if not name:
            return None
        content: dict[str, Any] = {"name": name}
    elif entry_type == "project":
        name = _clean_str(data_content.get("name"))
        summary = _clean_str(data_content.get("summary"))
        if not name and not summary:
            return None
        content = {
            "name": name,
            "role": _clean_str(data_content.get("role")),
            "summary": summary,
        }
    elif entry_type == "achievement":
        summary = _clean_str(data_content.get("summary"))
        if not summary:
            return None
        content = {"summary": summary, "metric": _clean_str(data_content.get("metric"))}
    else:  # pragma: no cover - defensive
        return None

    key = dedup_key_for(entry_type, content)
    if not key:
        return None
    return Candidate(
        entry_type=entry_type,
        content=content,
        dedup_key=key,
        source_type="generation",
        source_id=source_id,
        evidence_ids=list(evidence_ids or []),
    )


def merge_content(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Merge incoming fields into existing, preferring the longer non-empty value.

    Rationale: later generations often add detail (e.g. a project summary that
    grows richer). We keep whichever value carries more information.
    """
    merged = dict(existing)
    for k, v in incoming.items():
        if not v:
            continue
        cur = merged.get(k)
        if not cur or (isinstance(v, str) and isinstance(cur, str) and len(v) > len(cur)):
            merged[k] = v
    return merged


# --------- resume → candidates ---------


def resume_to_candidates(parsed: dict[str, Any], source_id: Any = None) -> list[Candidate]:
    """Turn a parsed resume dict into high-confidence profile candidates."""
    candidates: list[Candidate] = []

    for skill in parsed.get("skills") or []:
        name = _clean_str(skill)
        if not name:
            continue
        content = {"name": name}
        candidates.append(
            Candidate(
                entry_type="skill",
                content=content,
                dedup_key=dedup_key_for("skill", content),
                source_type="resume_import",
                source_id=source_id,
            )
        )

    for exp in parsed.get("experiences") or []:
        if not isinstance(exp, dict):
            continue
        company = _clean_str(exp.get("company"))
        title = _clean_str(exp.get("title"))
        if company:
            content = {
                "name": company,
                "title": title,
                "start_date": _clean_str(exp.get("start_date")),
                "end_date": _clean_str(exp.get("end_date")),
            }
            candidates.append(
                Candidate(
                    entry_type="company",
                    content=content,
                    dedup_key=dedup_key_for("company", content),
                    source_type="resume_import",
                    source_id=source_id,
                )
            )
        for bullet in exp.get("bullets") or []:
            summary = _clean_str(bullet)
            if not summary:
                continue
            content = {"summary": summary, "metric": None, "company": company}
            candidates.append(
                Candidate(
                    entry_type="achievement",
                    content=content,
                    dedup_key=dedup_key_for("achievement", content),
                    source_type="resume_import",
                    source_id=source_id,
                )
            )

    return candidates


# --------- github PR → candidates (v0.8) ---------


def github_pr_to_candidates(pr: dict[str, Any]) -> list[Candidate]:
    """Turn a minimal GitHub PR payload into merge candidates.

    ``pr`` matches the shape produced by
    :func:`app.integrations.github.extract_pr_minimal` (webhook) or
    :func:`_pr_from_issue_hit` (manual sync). We only keep two candidate
    kinds — an ``achievement`` (the PR itself, as a verified deliverable) and
    a ``project`` (the repository, so PRs from the same repo corroborate).
    """
    if not isinstance(pr, dict):
        return []
    node_id = _clean_str(pr.get("node_id"))
    title = _clean_str(pr.get("title"))
    if not node_id or not title:
        return []

    body = _clean_str(pr.get("body")) or ""
    repo_full_name = _clean_str(pr.get("repo_full_name") or pr.get("repo_name")) or ""
    html_url = _clean_str(pr.get("html_url"))
    merged = bool(pr.get("merged"))
    merged_at = _clean_str(pr.get("merged_at"))
    state = _clean_str(pr.get("state")) or "open"

    source_ref = f"github:pr:{node_id}"
    summary = title if not body else f"{title} — {body[:200]}"

    # A merged PR is a stronger signal than an open one; achievement
    # confidence scoring is driven by source_type=github (base 0.9).
    achievement = Candidate(
        entry_type="achievement",
        content={
            "summary": summary,
            "metric": None,
            "repo": repo_full_name,
            "url": html_url,
            "state": state,
            "merged": merged,
            "merged_at": merged_at,
        },
        dedup_key=_short_key(summary),
        source_type="github",
        source_ref=source_ref,
    )
    candidates = [achievement]

    if repo_full_name:
        candidates.append(
            Candidate(
                entry_type="project",
                content={
                    "name": repo_full_name,
                    "role": None,
                    "summary": f"GitHub 仓库 {repo_full_name}",
                },
                dedup_key=normalize_name(repo_full_name),
                source_type="github",
                source_ref=f"github:repo:{repo_full_name}",
            )
        )

    return candidates


def github_push_to_candidates(payload: dict[str, Any]) -> list[Candidate]:
    """Turn a minimal GitHub push payload into achievement candidates.

    Each of the top-10 commit messages becomes its own achievement candidate.
    Merged with existing entries via ``dedup_key`` so the same commit message
    text collapses across pushes.
    """
    if not isinstance(payload, dict):
        return []
    repo_full_name = _clean_str(payload.get("repo_full_name") or payload.get("repo_name")) or ""
    if not repo_full_name:
        return []
    candidates: list[Candidate] = []
    for i, msg in enumerate(payload.get("commit_messages") or []):
        summary = _clean_str(msg)
        if not summary:
            continue
        # Only take the first line — commit bodies leak diff excerpts.
        first_line = summary.splitlines()[0][:200]
        candidates.append(
            Candidate(
                entry_type="achievement",
                content={
                    "summary": first_line,
                    "metric": None,
                    "repo": repo_full_name,
                    "state": "committed",
                },
                dedup_key=_short_key(f"{repo_full_name} {first_line}"),
                source_type="github",
                source_ref=f"github:commit:{repo_full_name}:{i}:{first_line[:40]}",
            )
        )
    return candidates


# --------- snapshot compilation ---------


def _entry_view(entry_type: str, content: dict[str, Any], confidence: float) -> dict[str, Any]:
    view = {k: v for k, v in content.items() if v is not None}
    view["confidence"] = round(confidence, 3)
    return view


def compile_snapshot(
    *,
    basic_info: dict[str, Any],
    experiences: list[dict[str, Any]],
    entries: list[tuple[str, dict[str, Any], float]],
) -> dict[str, Any]:
    """Compile granular entries + resume seed into a structured snapshot.

    ``entries`` is a list of ``(entry_type, content, confidence)`` tuples,
    already filtered to non-rejected statuses.
    """
    buckets: dict[str, list[dict[str, Any]]] = {
        "skills": [],
        "tech_stack": [],
        "projects": [],
        "achievements": [],
        "companies": [],
    }
    type_to_bucket = {
        "skill": "skills",
        "tech": "tech_stack",
        "project": "projects",
        "achievement": "achievements",
        "company": "companies",
    }
    confidences: list[float] = []
    for entry_type, content, confidence in entries:
        bucket = type_to_bucket.get(entry_type)
        if bucket is None:
            continue
        buckets[bucket].append(_entry_view(entry_type, content, confidence))
        confidences.append(confidence)

    for key in buckets:
        buckets[key].sort(key=lambda v: v.get("confidence", 0), reverse=True)

    avg_conf = round(sum(confidences) / len(confidences), 3) if confidences else 0.0
    return {
        "basic_info": basic_info or {},
        "skills": buckets["skills"],
        "tech_stack": buckets["tech_stack"],
        "projects": buckets["projects"],
        "achievements": buckets["achievements"],
        "companies": buckets["companies"],
        "experiences": experiences or [],
        "stats": {
            "entry_count": len(entries),
            "confidence_avg": avg_conf,
        },
        "generated_at": datetime.now(UTC).isoformat(),
    }


def build_summary(snapshot: dict[str, Any], max_items: int = 8) -> str:
    """Build a short natural-language profile block for prompt injection."""
    lines: list[str] = []
    basic = snapshot.get("basic_info") or {}
    headline = basic.get("headline") or basic.get("title")
    yoe = basic.get("years_of_experience")
    if headline:
        lines.append(f"定位：{headline}")
    if yoe:
        lines.append(f"经验年限：约 {yoe} 年")

    skills = [s.get("name") for s in (snapshot.get("skills") or [])[:max_items] if s.get("name")]
    tech = [s.get("name") for s in (snapshot.get("tech_stack") or [])[:max_items] if s.get("name")]
    combined = list(dict.fromkeys(skills + tech))
    if combined:
        lines.append("技能栈：" + "、".join(combined[:max_items]))

    projects = snapshot.get("projects") or []
    if projects:
        lines.append("代表项目：")
        for p in projects[:5]:
            name = p.get("name") or ""
            summ = p.get("summary") or ""
            lines.append(f"  - {name}：{summ}".rstrip("："))

    achievements = snapshot.get("achievements") or []
    if achievements:
        lines.append("量化成果：")
        for a in achievements[:5]:
            summ = a.get("summary") or ""
            metric = a.get("metric")
            lines.append(f"  - {summ}" + (f"（{metric}）" if metric else ""))

    return "\n".join(lines).strip()
