"""Prompt template loader.

Prompts are YAML files under `backend/prompts/`. Each file has:
    name: identifier
    version: int
    description: human doc
    system: |  system prompt text
    user_template: |  Jinja-like placeholder string (uses str.format)

Placeholders supported in user_template:
    {input_content}    — raw user input (required)
    {profile_block}    — profile summary (empty string in v0.1)
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    version: int
    description: str
    system: str
    user_template: str

    def render_user(self, input_content: str, profile_block: str = "") -> str:
        return self.user_template.format(
            input_content=input_content.strip(),
            profile_block=profile_block.strip(),
        ).strip()


@lru_cache(maxsize=32)
def load_prompt(name: str) -> PromptTemplate:
    path = _PROMPTS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return PromptTemplate(
        name=data["name"],
        version=int(data.get("version", 1)),
        description=data.get("description", ""),
        system=data["system"],
        user_template=data["user_template"],
    )
