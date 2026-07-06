"""v0.5 Profile Engine + Resume Studio schema

Revision ID: 0002_v05
Revises: 0001_initial
Create Date: 2026-07-06

Adds:
    - pgvector extension
    - profiles.snapshot / profiles.summary  (compiled profile)
    - extracted_data.ingested_at            (Ingester bookkeeping)
    - profile_entries  (fine-grained, mergeable, embedded)
    - evidences        (raw source material for Evidence Chain)
    - jd_analyses      (JD deep analysis + match assessment)
    - resumes          (multi-version generated resumes)
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from app.config import get_settings

revision = "0002_v05"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

_DIM = get_settings().embedding_dim


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ---- profiles: compiled snapshot + summary ----
    op.add_column(
        "profiles",
        sa.Column("snapshot", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column("profiles", sa.Column("summary", sa.Text, nullable=True))

    # ---- extracted_data: Ingester bookkeeping ----
    op.add_column(
        "extracted_data",
        sa.Column("ingested_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_extracted_uningested",
        "extracted_data",
        ["user_id"],
        postgresql_where=sa.text("ingested_at IS NULL"),
    )

    # ---- profile_entries ----
    op.create_table(
        "profile_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entry_type", sa.String(50), nullable=False),
        sa.Column("content", postgresql.JSONB, nullable=False),
        sa.Column("dedup_key", sa.String(200), nullable=True),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0.5"),
        sa.Column("status", sa.String(20), nullable=False, server_default="auto"),
        sa.Column("source_type", sa.String(50), nullable=False, server_default="generation"),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("evidence_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False, server_default=sa.text("'{}'::uuid[]")),
        sa.Column("occurrences", sa.Integer, nullable=False, server_default="1"),
        sa.Column("embedding", Vector(_DIM), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_profile_entries_user_type", "profile_entries", ["user_id", "entry_type"])
    op.create_index("idx_profile_entries_dedup", "profile_entries", ["user_id", "entry_type", "dedup_key"])
    # HNSW index for cosine similarity (safe on empty tables; pgvector >= 0.5).
    op.execute(
        "CREATE INDEX idx_profile_entries_embedding ON profile_entries "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    # ---- evidences ----
    op.create_table(
        "evidences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_type", sa.String(50), nullable=False),
        sa.Column("raw_content", sa.Text, nullable=True),
        sa.Column("extracted_facts", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("generation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("generations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_evidences_user", "evidences", ["user_id"])

    # ---- jd_analyses (created before resumes: resumes references it) ----
    op.create_table(
        "jd_analyses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("jd_text", sa.Text, nullable=False),
        sa.Column("analysis", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("matching", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("overall_score", sa.Float, nullable=True),
        sa.Column("token_usage", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_jd_analyses_user_time", "jd_analyses", ["user_id", sa.text("created_at DESC")])

    # ---- resumes ----
    op.create_table(
        "resumes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("target_jd", sa.Text, nullable=True),
        sa.Column("jd_analysis_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jd_analyses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("content", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("pdf_url", sa.String(500), nullable=True),
        sa.Column("token_usage", postgresql.JSONB, nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_resumes_user_time", "resumes", ["user_id", sa.text("created_at DESC")])


def downgrade() -> None:
    op.drop_index("idx_resumes_user_time", table_name="resumes")
    op.drop_table("resumes")
    op.drop_index("idx_jd_analyses_user_time", table_name="jd_analyses")
    op.drop_table("jd_analyses")
    op.drop_index("idx_evidences_user", table_name="evidences")
    op.drop_table("evidences")
    op.execute("DROP INDEX IF EXISTS idx_profile_entries_embedding")
    op.drop_index("idx_profile_entries_dedup", table_name="profile_entries")
    op.drop_index("idx_profile_entries_user_type", table_name="profile_entries")
    op.drop_table("profile_entries")
    op.drop_index("idx_extracted_uningested", table_name="extracted_data")
    op.drop_column("extracted_data", "ingested_at")
    op.drop_column("profiles", "summary")
    op.drop_column("profiles", "snapshot")
    # Keep the vector extension in place (other objects may rely on it).
