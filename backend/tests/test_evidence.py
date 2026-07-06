"""Tests for the Evidence Chain builder / scorer."""
from __future__ import annotations

from app.services import evidence as ev


def test_normalize_item_basic() -> None:
    item = ev.normalize_item(
        {
            "requirement": "3年分布式经验",
            "status": "match",
            "data_basis": "记录了4个分布式项目",
            "reasoning": "项目密度等效2.5年",
            "confidence": 0.75,
            "suggestion": "突出系统设计决策",
        }
    )
    assert item is not None
    assert item.status == "match"
    assert item.confidence == 0.75


def test_normalize_item_synonyms_and_clamp() -> None:
    item = ev.normalize_item(
        {"requirement": "Kubernetes", "status": "yes", "data_basis": "用过 k8s", "confidence": 5}
    )
    assert item is not None
    assert item.status == "match"
    assert item.confidence == 1.0  # clamped


def test_normalize_item_honesty_guard() -> None:
    # match/partial without data_basis is downgraded to unknown
    item = ev.normalize_item(
        {"requirement": "Rust", "status": "match", "data_basis": "", "confidence": 0.9}
    )
    assert item is not None
    assert item.status == "unknown"
    assert item.confidence <= 0.3
    assert "暂无足够数据" in item.data_basis


def test_normalize_item_requires_requirement() -> None:
    assert ev.normalize_item({"status": "match", "data_basis": "x"}) is None


def test_build_chain_filters_junk() -> None:
    raw = [
        {"requirement": "A", "status": "match", "data_basis": "有"},
        "not-a-dict",
        {"status": "match"},  # no requirement → dropped
        {"requirement": "B", "status": "missing", "data_basis": "无"},
    ]
    chain = ev.build_chain(raw)
    assert [i.requirement for i in chain] == ["A", "B"]


def test_overall_score_and_gaps() -> None:
    chain = ev.build_chain(
        [
            {"requirement": "A", "status": "match", "data_basis": "有", "confidence": 1.0},
            {"requirement": "B", "status": "missing", "data_basis": "无", "confidence": 0.9},
            {"requirement": "C", "status": "partial", "data_basis": "部分", "confidence": 0.5},
        ]
    )
    score = ev.overall_score(chain)
    assert 0 <= score <= 100
    # match(1.0*1.0) + missing(0*0.9) + partial(0.5*0.5) over weights (1.0+0.9+0.5)
    # = (1.0 + 0 + 0.25) / 2.4 * 100 ≈ 52.1
    assert 45 <= score <= 60

    gaps = ev.summarize_gaps(chain)
    assert gaps["match"] == 1
    assert gaps["missing"] == 1
    assert gaps["partial"] == 1


def test_overall_score_empty() -> None:
    assert ev.overall_score([]) == 0.0
