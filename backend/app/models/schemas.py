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

# v0.5: efficiency task types + "auto" (Master Agent intent classification).
TaskType = Literal[
    "auto",
    "weekly_report",
    "monthly_report",
    "star",
    "free_format",
    "promotion",
    "pr_parse",
    "meeting_parse",
    "ability_assessment",
    "job_kit",
]


class GenerateRequest(BaseModel):
    task_type: TaskType = "weekly_report"
    input_content: str = Field(min_length=1, max_length=20000)
    voice_mode: bool = False


class IntentResponse(BaseModel):
    intent: str
    task_type: str
    agent_type: str
    confidence: float
    method: str


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


# ---------- Profile Engine v0.5 ----------


class ProfileSnapshotOut(BaseModel):
    """Compiled profile snapshot + summary produced by the Profile Engine."""

    user_id: UUID
    version: int
    summary: str | None = None
    snapshot: dict = Field(default_factory=dict)
    entry_count: int = 0


class ProfileEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    entry_type: str
    content: dict
    confidence: float
    status: str
    source_type: str
    occurrences: int
    created_at: datetime
    updated_at: datetime


class ProfileEntriesList(BaseModel):
    items: list[ProfileEntryOut]
    total: int


EntryStatus = Literal["confirmed", "rejected"]


class EntryStatusUpdateRequest(BaseModel):
    status: EntryStatus


class BatchEntryConfirmRequest(BaseModel):
    """Batch confirm/reject for the data-confirmation page."""

    confirmed_ids: list[UUID] = Field(default_factory=list)
    rejected_ids: list[UUID] = Field(default_factory=list)


class BatchEntryConfirmResponse(BaseModel):
    confirmed: int
    rejected: int


# ---------- Resume Studio ----------


class ResumeGenerateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200, default="我的简历")
    jd_text: str | None = Field(default=None, max_length=20000)


class ResumeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    target_jd: str | None = None
    jd_analysis_id: UUID | None = None
    content: dict = Field(default_factory=dict)
    version: int
    token_usage: dict | None = None
    created_at: datetime
    updated_at: datetime


class ResumeList(BaseModel):
    items: list[ResumeOut]
    total: int


class ResumeUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    content: dict | None = None


class ResumeDiagnoseRequest(BaseModel):
    resume_text: str = Field(min_length=1, max_length=40000)


# ---------- JD Analysis ----------


class JDAnalyzeRequest(BaseModel):
    jd_text: str = Field(min_length=1, max_length=20000)
    with_matching: bool = True


class JDAnalysisOut(BaseModel):
    id: UUID | None = None
    analysis: dict = Field(default_factory=dict)
    matching: dict = Field(default_factory=dict)
    overall_score: float | None = None


class ScreenshotParseResponse(BaseModel):
    summary: str = ""
    tasks: list[dict] = Field(default_factory=list)
    token_usage: dict | None = None


# ---------- v0.8 OAuth / Integrations ----------


class OAuthAuthorizeResponse(BaseModel):
    """Response for ``GET /api/v1/oauth/{provider}/authorize``."""

    provider: str
    authorize_url: str
    state: str


class OAuthConnectionOut(BaseModel):
    provider: str
    provider_user_id: str | None = None
    provider_login: str | None = None
    scopes: str | None = None
    status: str


class OAuthConnectionsList(BaseModel):
    items: list[OAuthConnectionOut]


class OAuthCallbackResponse(BaseModel):
    connection: OAuthConnectionOut
    # Whether the frontend should trigger the sync worker immediately.
    should_sync: bool = True


class GitHubSyncResponse(BaseModel):
    fetched: int
    created: int
    updated: int
    skipped_duplicates: int


class SyncEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider: str
    event_type: str
    external_id: str
    status: str
    created_at: datetime
    processed_at: datetime | None = None


class SyncEventList(BaseModel):
    items: list[SyncEventOut]
    total: int


class WebhookAck(BaseModel):
    status: str
    detail: dict | None = None


# ---------- v1.0 Analysis / Jobs / Documents / Trust / Reports ----------


class AnalysisAssessRequest(BaseModel):
    input_content: str = Field(default="", max_length=8000)


class AnalysisGapRequest(BaseModel):
    target_jd_id: UUID | None = None
    target_level: str | None = Field(default=None, max_length=50)


class JobKitRequest(BaseModel):
    jd_analysis_id: UUID | None = None
    jd_text: str | None = Field(default=None, max_length=20000)


class JobDebriefRequest(BaseModel):
    kit_id: UUID | None = None
    company: str | None = Field(default=None, max_length=200)
    position: str | None = Field(default=None, max_length=200)
    result: str | None = Field(default=None, max_length=30)
    notes_md: str = Field(min_length=1, max_length=40000)


class TrustLevelRequest(BaseModel):
    level: Literal[1, 2, 3]
