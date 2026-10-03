"""Append-only human integration reconciliation, independent of provider state."""

import sqlalchemy as sa

from alembic import op

revision = "h16de235ef78"
down_revision = "g05cf124de67"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "integration_deliveries",
        sa.Column("review_revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "integration_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "delivery_id",
            sa.Integer(),
            sa.ForeignKey("integration_deliveries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_request_id", sa.String(36), unique=True, nullable=False),
        sa.Column("provider_status", sa.String(16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("review_revision", sa.Integer(), nullable=False),
        sa.Column("resolution", sa.String(32), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("delivery_id", "review_revision"),
        sa.CheckConstraint("provider_status IN ('failed','uncertain')"),
        sa.CheckConstraint(
            "resolution IN ('verified_received','verified_not_received','needs_followup')"
        ),
        sa.CheckConstraint("attempt_count >= 0 AND attempt_count <= 3"),
        sa.CheckConstraint("review_revision > 0"),
    )
    op.create_index("ix_integration_reviews_delivery_id", "integration_reviews", ["delivery_id"])


def downgrade() -> None:
    op.drop_table("integration_reviews")
    op.drop_column("integration_deliveries", "review_revision")
