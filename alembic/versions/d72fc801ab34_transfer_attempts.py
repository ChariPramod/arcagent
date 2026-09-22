"""Persist verified transfer outcomes separately from request acceptance.

Revision ID: d72fc801ab34
Revises: c21ab845df10
"""

import sqlalchemy as sa

from alembic import op

revision = "d72fc801ab34"
down_revision = "c21ab845df10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transfer_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "call_id",
            sa.Integer(),
            sa.ForeignKey("calls.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("request_status", sa.String(16), nullable=False),
        sa.Column("child_call_sid", sa.String(64), unique=True),
        sa.Column("outcome", sa.String(16)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("request_status IN ('pending','accepted','failed','uncertain')"),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN "
            "('completed','no_answer','busy','failed','canceled','unbridged')"
        ),
    )

    op.create_table(
        "transfer_progress",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "attempt_id",
            sa.String(36),
            sa.ForeignKey("transfer_attempts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("attempt_id", "sequence"),
    )


def downgrade() -> None:
    op.drop_table("transfer_progress")
    op.drop_table("transfer_attempts")
