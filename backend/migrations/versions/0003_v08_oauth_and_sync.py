"""v0.8 OAuth + GitHub sync + Profile source refs

Revision ID: 0003_v08
Revises: 0002_v05
Create Date: 2026-07-06

v0.8 Beta+ 数据飞轮启动:
    - oauth_connections   第三方 OAuth 授权（GitHub 优先），token 加密存放
    - sync_events         第三方同步事件流水（GitHub Webhook/主动拉取）
    - profile_entries.source_ref / last_seen_at / first_seen_at
        为多源数据积累提供幂等键与时间维度
    - users.github_user_id / github_login
        用于 GitHub Webhook 关联用户
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_v08"
down_revision = "0002_v05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- users: GitHub 关联字段 ----
    op.add_column(
        "users",
        sa.Column("github_user_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("github_login", sa.String(128), nullable=True),
    )
    op.create_index(
        "idx_users_github_user_id",
        "users",
        ["github_user_id"],
        unique=False,
        postgresql_where=sa.text("github_user_id IS NOT NULL"),
    )

    # ---- profile_entries: 数据溯源 + 时间维度 ----
    op.add_column(
        "profile_entries",
        sa.Column("source_ref", sa.String(200), nullable=True),
    )
    op.add_column(
        "profile_entries",
        sa.Column("first_seen_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "profile_entries",
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_profile_entries_source_ref",
        "profile_entries",
        ["user_id", "source_type", "source_ref"],
        unique=False,
        postgresql_where=sa.text("source_ref IS NOT NULL"),
    )

    # ---- oauth_connections ----
    op.create_table(
        "oauth_connections",
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
        sa.Column("provider", sa.String(32), nullable=False),  # github / calendar / jira
        sa.Column("provider_user_id", sa.String(128), nullable=True),
        sa.Column("provider_login", sa.String(128), nullable=True),
        sa.Column("scopes", sa.String(400), nullable=True),
        # Access token is encrypted at rest (Fernet). We do NOT ever store raw.
        sa.Column("access_token_encrypted", sa.Text, nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text, nullable=True),
        sa.Column("token_expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column(
            "meta",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "provider", name="uq_oauth_user_provider"),
    )
    op.create_index(
        "idx_oauth_provider_uid",
        "oauth_connections",
        ["provider", "provider_user_id"],
    )

    # ---- sync_events (幂等 + 观测) ----
    op.create_table(
        "sync_events",
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
            nullable=True,  # webhook 可能先到再关联 user
        ),
        sa.Column("provider", sa.String(32), nullable=False),  # github / calendar / jira
        sa.Column("event_type", sa.String(64), nullable=False),  # pull_request / push / manual
        # Idempotency key: 同一事件重复到达也只落一次 (github delivery id / pr node id)。
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("processed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("provider", "external_id", name="uq_sync_provider_extid"),
    )
    op.create_index(
        "idx_sync_events_user_time",
        "sync_events",
        ["user_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_sync_events_user_time", table_name="sync_events")
    op.drop_table("sync_events")
    op.drop_index("idx_oauth_provider_uid", table_name="oauth_connections")
    op.drop_table("oauth_connections")

    op.drop_index("idx_profile_entries_source_ref", table_name="profile_entries")
    op.drop_column("profile_entries", "last_seen_at")
    op.drop_column("profile_entries", "first_seen_at")
    op.drop_column("profile_entries", "source_ref")

    op.drop_index("idx_users_github_user_id", table_name="users")
    op.drop_column("users", "github_login")
    op.drop_column("users", "github_user_id")
