"""Evidence Chain (v0.5 基础版).

Every JD-match verdict and resume suggestion must carry a four-part chain so the
user can judge *why* the AI said what it said:

    1. data_basis  数据依据  — what we found in your profile
    2. reasoning   推理逻辑  — why that maps (or not) to the requirement
    3. confidence  置信度    — how sure we are (0..1)
    4. suggestion  建议      — the concrete, actionable next step

This module normalises/validates the raw LLM JSON into a stable shape and
computes an overall match score. It contains no I/O so it is directly testable.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

# Recognised match verdicts and their score weight.
_STATUS_WEIGHT: dict[str, float] = {
    "match": 1.0,
    "partial": 0.5,
    "missing": 0.0,
    "unknown": 0.0,  # data insufficient — honestly flagged, no credit
}
_VALID_STATUSES = set(_STATUS_WEIGHT)


@dataclass
class EvidenceItem:
    requirement: str
    status: str                # match / partial / missing / unknown
    data_basis: str            # 数据依据
    reasoning: str             # 推理逻辑
    confidence: float          # 0..1
    suggestion: str            # 可操作建议

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clamp_confidence(value: Any) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.3
    return round(max(0.0, min(1.0, f)), 2)


def _norm_status(value: Any) -> str:
    s = str(value or "").strip().lower()
    if s in _VALID_STATUSES:
        return s
    # Common synonyms from the model.
    if s in ("matched", "yes", "full"):
        return "match"
    if s in ("partially", "weak"):
        return "partial"
    if s in ("no", "gap", "not_found"):
        return "missing"
    return "unknown"


def normalize_item(raw: dict[str, Any]) -> EvidenceItem | None:
    """Validate one raw evidence dict. Returns ``None`` if unusable."""
    requirement = str(raw.get("requirement") or raw.get("要求") or "").strip()
    if not requirement:
        return None
    status = _norm_status(raw.get("status") or raw.get("状态"))
    data_basis = str(raw.get("data_basis") or raw.get("数据依据") or "").strip()
    reasoning = str(raw.get("reasoning") or raw.get("推理逻辑") or "").strip()
    suggestion = str(raw.get("suggestion") or raw.get("建议") or "").strip()
    confidence = _clamp_confidence(raw.get("confidence", raw.get("置信度")))

    # Honesty guard: no data → force unknown + explicit message.
    if not data_basis and status in ("match", "partial"):
        status = "unknown"
        data_basis = "暂无足够数据支撑该项。"
        confidence = min(confidence, 0.3)

    return EvidenceItem(
        requirement=requirement,
        status=status,
        data_basis=data_basis or "暂无足够数据支撑该项。",
        reasoning=reasoning,
        confidence=confidence,
        suggestion=suggestion,
    )


def build_chain(raw_items: Any) -> list[EvidenceItem]:
    """Normalise a list of raw evidence dicts into validated EvidenceItems."""
    if not isinstance(raw_items, list):
        return []
    items: list[EvidenceItem] = []
    for raw in raw_items:
        if isinstance(raw, dict):
            item = normalize_item(raw)
            if item is not None:
                items.append(item)
    return items


def overall_score(items: list[EvidenceItem]) -> float:
    """Confidence-weighted match score in [0, 100].

    Each requirement contributes ``status_weight * confidence``; the score is the
    weighted average scaled to 100. Empty input scores 0.
    """
    if not items:
        return 0.0
    total = 0.0
    weight = 0.0
    for item in items:
        w = max(item.confidence, 0.1)  # avoid zero-weight starving the average
        total += _STATUS_WEIGHT.get(item.status, 0.0) * w
        weight += w
    return round((total / weight) * 100, 1) if weight else 0.0


def summarize_gaps(items: list[EvidenceItem]) -> dict[str, int]:
    """Count verdicts by status — handy for a quick match header."""
    counts = dict.fromkeys(_VALID_STATUSES, 0)
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1
    return counts
