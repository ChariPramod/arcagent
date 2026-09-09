"""Save evaluation input snapshots. Historical runs retain null provenance.

Revision ID: b8e5f431a290
Revises: 742a8b19c6d0
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b8e5f431a290"
down_revision = "742a8b19c6d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("eval_runs", sa.Column(
        "snapshot", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True,
    ))


def downgrade() -> None:
    op.drop_column("eval_runs", "snapshot")
