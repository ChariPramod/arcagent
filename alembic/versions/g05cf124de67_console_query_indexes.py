"""Bounded console query indexes and explicit transcript redaction state.

Revision ID: g05cf124de67
Revises: f94be013cd56
"""

import sqlalchemy as sa

from alembic import op

revision = "g05cf124de67"
down_revision = "f94be013cd56"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("turns", sa.Column("transcript_redacted_at", sa.DateTime(timezone=True)))
    op.create_index(
        "ix_turns_pending_transcript_id",
        "turns",
        ["id"],
        postgresql_where=sa.text("transcript_redacted_at IS NULL"),
        sqlite_where=sa.text("transcript_redacted_at IS NULL"),
    )
    op.create_index("ix_calls_started_id", "calls", ["started_at", "id"])
    op.create_index("ix_calls_outcome_started_id", "calls", ["outcome", "started_at", "id"])
    op.create_index("ix_leads_call_id_id", "leads", ["call_id", "id"])
    op.create_index("ix_lead_scores_lead_id_id", "lead_scores", ["lead_id", "id"])
    # Composite indexes retain the foreign-key prefix lookup. Avoid paying for
    # redundant single-column copies on every contact/score write.
    op.drop_index("ix_leads_call_id", table_name="leads")
    op.drop_index("ix_lead_scores_lead_id", table_name="lead_scores")


def downgrade() -> None:
    op.create_index("ix_leads_call_id", "leads", ["call_id"])
    op.create_index("ix_lead_scores_lead_id", "lead_scores", ["lead_id"])
    op.drop_index("ix_lead_scores_lead_id_id", table_name="lead_scores")
    op.drop_index("ix_leads_call_id_id", table_name="leads")
    op.drop_index("ix_calls_outcome_started_id", table_name="calls")
    op.drop_index("ix_calls_started_id", table_name="calls")
    op.drop_index("ix_turns_pending_transcript_id", table_name="turns")
    op.drop_column("turns", "transcript_redacted_at")
