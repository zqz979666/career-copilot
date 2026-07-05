"""Smoke test for prompt loader — no external deps."""
from __future__ import annotations

import pytest

from app.agents.prompt_loader import load_prompt


@pytest.mark.parametrize("name", ["weekly_report", "star", "free_format"])
def test_prompt_templates_load(name: str) -> None:
    template = load_prompt(name)
    assert template.name == name
    assert template.system.strip()
    assert "{input_content}" in template.user_template


def test_prompt_render_substitutes_placeholders() -> None:
    template = load_prompt("weekly_report")
    rendered = template.render_user("上线了 A/B 实验平台", profile_block="")
    assert "上线了 A/B 实验平台" in rendered
    # profile_block empty → no leftover placeholder text
    assert "{profile_block}" not in rendered
