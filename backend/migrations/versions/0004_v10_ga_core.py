"""v1.0 GA core tables

Revision ID: 0004_v10
Revises: 0003_v08
Create Date: 2026-07-06
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_v10"
down_revision = "0003_v08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ability_assessments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dimension", sa.String(80), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column(
            "evidence_chain",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("trend_delta", sa.Float(), nullable=True),
        sa.Column("profile_snapshot_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("assessed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "idx_assessments_user_time",
        "ability_assessments",
        ["user_id", sa.text("assessed_at DESC")],
    )

    op.create_table(
        "growth_reports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period", sa.String(20), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column(
            "metrics",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "period", name="uq_growth_reports_user_period"),
    )

    op.create_table(
        "interview_kits",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "jd_analysis_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jd_analyses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("questions", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("pitch", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "interview_debriefs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "kit_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interview_kits.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("company", sa.String(200), nullable=True),
        sa.Column("position", sa.String(200), nullable=True),
        sa.Column("result", sa.String(30), nullable=True),
        sa.Column("notes_md", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "trust_ladder_state",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("level_changed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "document_blobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(120), nullable=True),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("extracted_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("document_blobs")
    op.drop_table("trust_ladder_state")
    op.drop_table("interview_debriefs")
    op.drop_table("interview_kits")
    op.drop_table("growth_reports")
    op.drop_index("idx_assessments_user_time", table_name="ability_assessments")
    op.drop_table("ability_assessments")
