"""Tests for GenerationRepository's edit-ratio calculation.

Only the pure helper needs coverage — DB access is exercised via integration
tests once a live PG is available.
"""
from __future__ import annotations

from app.repository.generation_repo import _normalized_edit_ratio


def test_edit_ratio_zero_when_identical() -> None:
    text = "## 本周工作总结\n- 完成了 A/B 实验平台上线"
    assert _normalized_edit_ratio(text, text) == 0.0


def test_edit_ratio_one_when_edit_empty() -> None:
    assert _normalized_edit_ratio("some output", "") == 1.0


def test_edit_ratio_zero_when_original_empty() -> None:
    # Degenerate case: no original text means no denominator.
    assert _normalized_edit_ratio("", "user typed something") == 0.0


def test_edit_ratio_between_zero_and_one_on_partial_edit() -> None:
    original = "本周完成了推荐算法上线，QPS 提升 30%"
    edited = "本周完成了推荐算法灰度上线，QPS 提升到 30% 左右"
    ratio = _normalized_edit_ratio(original, edited)
    assert 0.0 < ratio < 1.0


def test_edit_ratio_large_when_full_rewrite() -> None:
    original = "本周做了三件事：上线推荐算法、修 Bug、review PR"
    edited = "完全重写一段与原文毫无相似度的内容 fully rewritten content xyz"
    ratio = _normalized_edit_ratio(original, edited)
    assert ratio > 0.5
