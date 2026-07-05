"""Pydantic schemas for request/response payloads."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# ---------- Auth ----------


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    name: str | None = Field(default=None, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


MemoryMode = Literal["full", "selective", "none"]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str | None
    name: str | None
    memory_mode: str
    created_at: datetime


# ---------- Settings ----------


class SettingsOut(BaseModel):
    memory_mode: MemoryMode


class SettingsUpdateRequest(BaseModel):
    memory_mode: MemoryMode


# ---------- Generation ----------

TaskType = Literal["weekly_report", "star", "free_format"]


class GenerateRequest(BaseModel):
    task_type: TaskType = "weekly_report"
    input_content: str = Field(min_length=1, max_length=8000)
    voice_mode: bool = False


class GenerationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    input_text: str
    output_format: str
    output_text: str
    edited_text: str | None = None
    edit_ratio: float | None = None
    user_rating: int | None = None
    created_at: datetime


class HistoryList(BaseModel):
    items: list[GenerationOut]
    total: int


class GenerationFeedbackRequest(BaseModel):
    """PATCH body for `/api/v1/history/{id}`.

    Both fields optional — client can send either or both.
    `edit_ratio` is derived server-side from `edited_text` vs `output_text`.
    """

    user_rating: int | None = Field(default=None, ge=1, le=5)
    edited_text: str | None = Field(default=None, max_length=200_000)


# ---------- Meta ----------


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    env: str


# ---------- Profile / Resume ----------


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    basic_info: dict = Field(default_factory=dict)
    skills: list = Field(default_factory=list)
    experiences: list = Field(default_factory=list)
    raw_resume_url: str | None = None
    version: int
    created_at: datetime
    updated_at: datetime


class ResumeUploadResponse(BaseModel):
    profile: ProfileOut
    source_format: str
    source_page_count: int | None = None
    source_chars: int
    extracted_fields: int = Field(description="Number of top-level fields populated")
    token_usage: dict | None = None
