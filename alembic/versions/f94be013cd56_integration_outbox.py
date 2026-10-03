"""Durable location-snapshotted integration outbox.

Revision ID: f94be013cd56
Revises: e83ad902bc45
"""

import sqlalchemy as sa
from alembic import op

revision = "f94be013cd56"
down_revision = "e83ad902bc45"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("call_id", sa.Integer(), sa.ForeignKey("calls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("location_name", sa.String(128), nullable=False),
        sa.Column("destination", sa.String(20), nullable=False),
        sa.Column("client_request_id", sa.String(36), unique=True, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("config_fingerprint", sa.String(64), nullable=False),
        sa.Column("error_code", sa.String(40)),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("updated_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("call_id", "destination"),
        sa.CheckConstraint("destination IN ('hubspot','automation')"),
        sa.CheckConstraint("status IN ('queued','sending','delivered','failed','uncertain')"),
        sa.CheckConstraint("attempt_count >= 0 AND attempt_count <= 3"),
    )
    for column in ("call_id", "location_id", "status"):
        op.create_index(f"ix_integration_deliveries_{column}", "integration_deliveries", [column])


def downgrade() -> None:
    op.drop_table("integration_deliveries")
