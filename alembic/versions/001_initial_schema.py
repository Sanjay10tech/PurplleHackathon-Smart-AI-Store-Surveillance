"""Initial schema: tenants, stores, domain_events, analytics tables.

Revision ID: 001
Revises:
Create Date: 2026-05-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )

    op.create_table(
        "stores",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("timezone", sa.String(length=64), server_default="UTC", nullable=False),
        sa.Column("geo_location", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stores_tenant_id", "stores", ["tenant_id"], unique=False)

    op.create_table(
        "domain_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("causation_id", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=256), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_domain_events_tenant_occurred", "domain_events", ["tenant_id", "occurred_at"], unique=False)
    op.create_index(
        "ix_domain_events_aggregate",
        "domain_events",
        ["aggregate_type", "aggregate_id", "occurred_at"],
        unique=False,
    )
    op.create_index("ix_domain_events_event_type", "domain_events", ["event_type"], unique=False)
    op.create_index(
        "uq_domain_events_idempotency_key",
        "domain_events",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "analytics_rollups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("camera_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("metric_name", sa.String(length=128), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bucket_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dimensions", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("value", sa.Float(), server_default="0", nullable=False),
        sa.Column("sample_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "store_id",
            "camera_id",
            "metric_name",
            "bucket_start",
            "dimensions",
            name="uq_analytics_rollups_bucket",
        ),
    )
    op.create_index(
        "ix_analytics_rollups_store_metric",
        "analytics_rollups",
        ["store_id", "metric_name", "bucket_start"],
        unique=False,
    )

    op.create_table(
        "analytics_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_type", sa.String(length=64), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_analytics_snapshots_store_type",
        "analytics_snapshots",
        ["store_id", "snapshot_type", "period_start"],
        unique=False,
    )

    # Seed default tenant for local development
    op.execute(
        sa.text(
            """
            INSERT INTO tenants (id, name, slug, settings)
            VALUES (
                '00000000-0000-0000-0000-000000000001',
                'Default Tenant',
                'default',
                '{}'
            )
            ON CONFLICT (slug) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_analytics_snapshots_store_type", table_name="analytics_snapshots")
    op.drop_table("analytics_snapshots")
    op.drop_index("ix_analytics_rollups_store_metric", table_name="analytics_rollups")
    op.drop_table("analytics_rollups")
    op.drop_index("uq_domain_events_idempotency_key", table_name="domain_events")
    op.drop_index("ix_domain_events_event_type", table_name="domain_events")
    op.drop_index("ix_domain_events_aggregate", table_name="domain_events")
    op.drop_index("ix_domain_events_tenant_occurred", table_name="domain_events")
    op.drop_table("domain_events")
    op.drop_index("ix_stores_tenant_id", table_name="stores")
    op.drop_table("stores")
    op.drop_table("tenants")
