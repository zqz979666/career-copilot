"""SQLAlchemy ORM models.

v0.1 shipped: users / generations / profiles / extracted_data.
v0.5 adds the Profile Engine + Resume Studio tables:
    profile_entries / evidences / resumes / jd_analyses
plus a pgvector embedding column on profile_entries and a compiled
``snapshot`` / ``summary`` on profiles.
v0.8 adds the data flywheel — 3rd-party integration (GitHub OAuth + Webhooks):
    oauth_connections, sync_events, and provenance fields on profile_entries.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.config import get_settings
from app.db import Base

_EMBEDDING_DIM = get_settings().embedding_dim


def _uuid_col() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_col()
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    auth_provider: Mapped[str] = mapped_column(String(50), nullable=False, default="email")
    auth_provider_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    memory_mode: Mapped[str] = mapped_column(String(20), default="full", nullable=False)

    # v0.8 GitHub 关联（Webhook 事件通过 github_user_id 反查用户）。
    github_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    github_login: Mapped[str | None] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    generations: Mapped[list[Generation]] = relationship(back_populates="user")


class Generation(Base):
    __tablename__ = "generations"

    id: Mapped[uuid.UUID] = _uuid_col()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,  # Level 0 anonymous usage
        index=True,
    )
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    input_type: Mapped[str] = mapped_column(String(20), nullable=False, default="text")
    output_format: Mapped[str] = mapped_column(String(30), nullable=False)
    output_text: Mapped[str] = mapped_column(Text, nullable=False)

    edited_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    edit_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)

    extracted_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    user_rating: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    generation_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False, index=True
    )

    user: Mapped[User | None] = relationship(back_populates="generations")


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = _uuid_col()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    basic_info: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    skills: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    experiences: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    raw_resume_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # v0.5: compiled profile produced by the Profile Engine Summarizer.
    # `snapshot` is the full structured view (used for rollback / rendering);
    # `summary` is a short natural-language block injected into generation prompts.
    snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ExtractedData(Base):
    __tablename__ = "extracted_data"

    id: Mapped[uuid.UUID] = _uuid_col()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    generation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("generations.id", ondelete="SET NULL"),
        nullable=True,
    )
    data_type: Mapped[str] = mapped_column(String(50), nullable=False)
    data_content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="auto", nullable=False)
    # v0.5: set once the Profile Engine Ingester has folded this row into a
    # profile_entry. NULL = not yet ingested.
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class ProfileEntry(Base):
    """Fine-grained, mergeable unit of a user's professional profile.

    Populated by the Profile Engine (Ingester + Merger) from ``extracted_data``
    and resume imports. Each entry carries a confidence score, a lifecycle
    ``status`` (auto/confirmed/rejected), and an optional pgvector embedding for
    semantic retrieval during resume/JD matching.
    """

    __tablename__ = "profile_entries"

    id: Mapped[uuid.UUID] = _uuid_col()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entry_type: Mapped[str] = mapped_column(String(50), nullable=False)  # skill/project/achievement/company/role/tech
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Normalised key used for entity alignment / dedup (e.g. lower-cased name).
    dedup_key: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="auto", nullable=False)  # auto/confirmed/rejected
    source_type: Mapped[str] = mapped_column(String(50), default="generation", nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    evidence_ids: Mapped[list] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list, nullable=False)
    # Number of corroborating observations — drives the confidence scorer.
    occurrences: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(_EMBEDDING_DIM), nullable=True)

    # v0.8: 数据溯源（同一 PR 反复到达时用于幂等更新）。
    source_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Evidence(Base):
    """Raw source material backing profile entries / Evidence Chains."""

    __tablename__ = "evidences"

    id: Mapped[uuid.UUID] = _uuid_col()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    evidence_type: Mapped[str] = mapped_column(String(50), nullable=False)  # text_input/pr/meeting_notes/resume/screenshot
    raw_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_facts: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    generation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("generations.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class Resume(Base):
    """A generated/edited resume version, optionally tailored to a target JD."""

    __tablename__ = "resumes"

    id: Mapped[uuid.UUID] = _uuid_col()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    target_jd: Mapped[str | None] = mapped_column(Text, nullable=True)
    jd_analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jd_analyses.id", ondelete="SET NULL"),
        nullable=True,
    )
    content: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    pdf_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    token_usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


class JDAnalysis(Base):
    """Result of a JD deep-analysis + match assessment (with Evidence Chain)."""

    __tablename__ = "jd_analyses"

    id: Mapped[uuid.UUID] = _uuid_col()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,  # Level 0 anonymous JD analysis is allowed (no matching)
        index=True,
    )
    jd_text: Mapped[str] = mapped_column(Text, nullable=False)
    analysis: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)  # 要求/隐含/红旗/团队推测
    matching: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)  # 含 Evidence Chain
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    token_usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


# ------------------------------------------------------------------
# v0.8 — data flywheel: OAuth connections + 3rd-party sync events
# ------------------------------------------------------------------


class OAuthConnection(Base):
    """A user's authorised connection to a 3rd-party provider (GitHub first).

    Access/refresh tokens are stored **encrypted at rest** (Fernet with
    ``GITHUB_TOKEN_ENC_KEY`` / a shared key). We never accept nor return raw
    tokens over HTTP — the encrypted blob is the ground truth.
    """

    __tablename__ = "oauth_connections"

    id: Mapped[uuid.UUID] = _uuid_col()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)  # github/calendar/jira
    provider_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_login: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scopes: Mapped[str | None] = mapped_column(String(400), nullable=True)
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SyncEvent(Base):
    """Provenance + idempotency ledger for 3rd-party sync events.

    Each row represents one external event (a GitHub PR node, a webhook
    delivery, a manual pull). ``(provider, external_id)`` is UNIQUE so retries
    are safe and the Sync Worker is naturally idempotent.
    """

    __tablename__ = "sync_events"

    id: Mapped[uuid.UUID] = _uuid_col()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


# ------------------------------------------------------------------
# v1.0 — analysis / jobs / trust ladder / document ingest
# ------------------------------------------------------------------


class AbilityAssessment(Base):
    __tablename__ = "ability_assessments"

    id: Mapped[uuid.UUID] = _uuid_col()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dimension: Mapped[str] = mapped_column(String(80), nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_chain: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    trend_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    profile_snapshot_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    assessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class GrowthReport(Base):
    __tablename__ = "growth_reports"

    id: Mapped[uuid.UUID] = _uuid_col()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period: Mapped[str] = mapped_column(String(20), nullable=False)
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class InterviewKit(Base):
    __tablename__ = "interview_kits"

    id: Mapped[uuid.UUID] = _uuid_col()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    jd_analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jd_analyses.id", ondelete="SET NULL"),
        nullable=True,
    )
    questions: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    pitch: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class InterviewDebrief(Base):
    __tablename__ = "interview_debriefs"

    id: Mapped[uuid.UUID] = _uuid_col()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interview_kits.id", ondelete="SET NULL"),
        nullable=True,
    )
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    position: Mapped[str | None] = mapped_column(String(200), nullable=True)
    result: Mapped[str | None] = mapped_column(String(30), nullable=True)
    notes_md: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class TrustLadderState(Base):
    __tablename__ = "trust_ladder_state"

    id: Mapped[uuid.UUID] = _uuid_col()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    level_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DocumentBlob(Base):
    __tablename__ = "document_blobs"

    id: Mapped[uuid.UUID] = _uuid_col()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    content: Mapped[bytes] = mapped_column(nullable=False)
    extracted_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
