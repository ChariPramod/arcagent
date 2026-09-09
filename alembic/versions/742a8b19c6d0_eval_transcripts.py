"""Preserve text evaluation transcripts for scenario review.

Revision ID: 742a8b19c6d0
Revises: e31339b35a93
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "742a8b19c6d0"
down_revision = "e31339b35a93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "eval_results",
        sa.Column(
            "transcript",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("eval_results", "transcript")
