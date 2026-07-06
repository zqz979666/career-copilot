"""Tests for the Profile Engine pure logic (entity alignment + confidence + compile)."""
from __future__ import annotations

from app.services import profile_merge as pm


def test_normalize_name() -> None:
    assert pm.normalize_name("  PostgreSQL  ") == "postgresql"
    assert pm.normalize_name("Apache   Kafka") == "apache kafka"


def test_dedup_key_for_types() -> None:
    assert pm.dedup_key_for("skill", {"name": "Redis"}) == "redis"
    assert pm.dedup_key_for("tech", {"name": "  Kafka "}) == "kafka"
    assert pm.dedup_key_for("project", {"name": "订单中心重构"}) == "订单中心重构"
    # achievement dedups on the (short) summary
    key = pm.dedup_key_for("achievement", {"summary": "QPS 从 3k 提升到 12k"})
    assert key == "qps 从 3k 提升到 12k"


def test_score_confidence_grows_and_caps() -> None:
    # generation base 0.5, +0.08 per extra occurrence
    assert pm.score_confidence(1, "generation") == 0.5
    assert pm.score_confidence(3, "generation") == 0.66
    # resume/user sources start higher
    assert pm.score_confidence(1, "resume_import") == 0.8
    assert pm.score_confidence(1, "user_input") == 0.9
    # capped at 0.98
    assert pm.score_confidence(50, "user_input") == 0.98


def test_extracted_row_to_candidate_skill() -> None:
    cand = pm.extracted_row_to_candidate(
        data_type="skill", data_content={"name": "  Go  "}, source_id=None, evidence_ids=[]
    )
    assert cand is not None
    assert cand.entry_type == "skill"
    assert cand.content["name"] == "Go"
    assert cand.dedup_key == "go"


def test_extracted_row_to_candidate_drops_empty_and_unknown() -> None:
    assert (
        pm.extracted_row_to_candidate(
            data_type="skill", data_content={"name": "   "}, source_id=None, evidence_ids=[]
        )
        is None
    )
    assert (
        pm.extracted_row_to_candidate(
            data_type="unknown_type", data_content={"x": 1}, source_id=None, evidence_ids=[]
        )
        is None
    )


def test_merge_content_prefers_longer_value() -> None:
    existing = {"name": "订单中心", "summary": "重构"}
    incoming = {"name": "订单中心", "summary": "分库分表重构，QPS 提升 4 倍", "role": "负责人"}
    merged = pm.merge_content(existing, incoming)
    assert merged["summary"] == "分库分表重构，QPS 提升 4 倍"
    assert merged["role"] == "负责人"
    assert merged["name"] == "订单中心"


def test_resume_to_candidates() -> None:
    parsed = {
        "skills": ["Python", "  ", "Kafka"],
        "experiences": [
            {
                "company": "字节跳动",
                "title": "高级后端工程师",
                "bullets": ["主导订单中心分库分表", ""],
            }
        ],
    }
    cands = pm.resume_to_candidates(parsed)
    types = [c.entry_type for c in cands]
    assert types.count("skill") == 2
    assert types.count("company") == 1
    assert types.count("achievement") == 1
    assert all(c.source_type == "resume_import" for c in cands)


def test_compile_snapshot_and_summary() -> None:
    entries = [
        ("skill", {"name": "Python"}, 0.9),
        ("tech", {"name": "PostgreSQL"}, 0.8),
        ("project", {"name": "订单中心", "summary": "分库分表"}, 0.7),
        ("achievement", {"summary": "QPS 提升 4 倍", "metric": "3k→12k"}, 0.6),
    ]
    snap = pm.compile_snapshot(
        basic_info={"headline": "5 年后端", "years_of_experience": 5},
        experiences=[],
        entries=entries,
    )
    assert snap["stats"]["entry_count"] == 4
    assert snap["skills"][0]["name"] == "Python"
    assert snap["tech_stack"][0]["name"] == "PostgreSQL"

    summary = pm.build_summary(snap)
    assert "5 年后端" in summary
    assert "Python" in summary
    assert "订单中心" in summary
    assert "QPS 提升 4 倍" in summary


def test_entry_text_for_embedding() -> None:
    assert pm.entry_text_for_embedding("skill", {"name": "Redis"}) == "Redis"
    text = pm.entry_text_for_embedding(
        "project", {"name": "订单中心", "role": "负责人", "summary": "分库分表"}
    )
    assert "订单中心" in text and "负责人" in text and "分库分表" in text
