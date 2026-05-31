"""Core analytics tables: sessions, events, transactions, anomalies, store_metrics.

Revision ID: 002
Revises: 001
Create Date: 2026-05-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_track_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sessions_store_started", "sessions", ["store_id", "started_at"], unique=False)
    op.create_index("ix_sessions_store_status", "sessions", ["store_id", "status"], unique=False)
    op.create_index(
        "ix_sessions_store_external_track", "sessions", ["store_id", "external_track_id"], unique=False
    )

    op.create_table(
        "events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("causation_id", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=256), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_store_occurred", "events", ["store_id", "occurred_at"], unique=False)
    op.create_index(
        "ix_events_store_type_occurred", "events", ["store_id", "event_type", "occurred_at"], unique=False
    )
    op.create_index("ix_events_tenant_occurred", "events", ["tenant_id", "occurred_at"], unique=False)
    op.create_index("ix_events_correlation_id", "events", ["correlation_id"], unique=False)
    op.create_index("ix_events_session_id", "events", ["session_id"], unique=False)
    op.create_index(
        "uq_events_idempotency_key",
        "events",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("external_ref", sa.String(length=128), nullable=True),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="completed", nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_transactions_store_occurred", "transactions", ["store_id", "occurred_at"], unique=False
    )
    op.create_index("ix_transactions_session_id", "transactions", ["session_id"], unique=False)
    op.create_index(
        "uq_transactions_store_external_ref",
        "transactions",
        ["store_id", "external_ref"],
        unique=True,
        postgresql_where=sa.text("external_ref IS NOT NULL"),
    )

    op.create_table(
        "anomalies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("anomaly_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), server_default="warning", nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_anomalies_store_detected", "anomalies", ["store_id", "detected_at"], unique=False)
    op.create_index(
        "ix_anomalies_store_severity_detected",
        "anomalies",
        ["store_id", "severity", "detected_at"],
        unique=False,
    )
    op.create_index(
        "ix_anomalies_store_type_detected",
        "anomalies",
        ["store_id", "anomaly_type", "detected_at"],
        unique=False,
    )
    op.create_index(
        "ix_anomalies_store_open",
        "anomalies",
        ["store_id", "detected_at"],
        unique=False,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )

    op.create_table(
        "store_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_name", sa.String(length=128), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bucket_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("granularity", sa.String(length=16), server_default="hour", nullable=False),
        sa.Column("dimensions", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("value", sa.Float(), server_default="0", nullable=False),
        sa.Column("sample_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "store_id",
            "metric_name",
            "bucket_start",
            "granularity",
            "dimensions",
            name="uq_store_metrics_bucket",
        ),
    )
    op.create_index(
        "ix_store_metrics_store_metric_bucket",
        "store_metrics",
        ["store_id", "metric_name", "bucket_start"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_store_metrics_store_metric_bucket", table_name="store_metrics")
    op.drop_table("store_metrics")
    op.drop_index("ix_anomalies_store_open", table_name="anomalies")
    op.drop_index("ix_anomalies_store_type_detected", table_name="anomalies")
    op.drop_index("ix_anomalies_store_severity_detected", table_name="anomalies")
    op.drop_index("ix_anomalies_store_detected", table_name="anomalies")
    op.drop_table("anomalies")
    op.drop_index("uq_transactions_store_external_ref", table_name="transactions")
    op.drop_index("ix_transactions_session_id", table_name="transactions")
    op.drop_index("ix_transactions_store_occurred", table_name="transactions")
    op.drop_table("transactions")
    op.drop_index("uq_events_idempotency_key", table_name="events")
    op.drop_index("ix_events_session_id", table_name="events")
    op.drop_index("ix_events_correlation_id", table_name="events")
    op.drop_index("ix_events_tenant_occurred", table_name="events")
    op.drop_index("ix_events_store_type_occurred", table_name="events")
    op.drop_index("ix_events_store_occurred", table_name="events")
    op.drop_table("events")
    op.drop_index("ix_sessions_store_external_track", table_name="sessions")
    op.drop_index("ix_sessions_store_status", table_name="sessions")
    op.drop_index("ix_sessions_store_started", table_name="sessions")
    op.drop_table("sessions")
