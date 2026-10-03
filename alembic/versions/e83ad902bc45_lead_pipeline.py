"""Single group lead conversion state.

Revision ID: e83ad902bc45
Revises: d72fc801ab34
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "e83ad902bc45"
down_revision = "d72fc801ab34"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "locations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(128), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "location_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column(
            "changes", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_location_audit_location_id", "location_audit", ["location_id"])
    op.create_table(
        "lead_pipeline",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "call_id",
            sa.Integer(),
            sa.ForeignKey("calls.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("locations.id")),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("assignee", sa.String(128)),
        sa.Column("next_action_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(128), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("stage IN ('new','contacted','booked','won','lost')"),
        sa.CheckConstraint("revision > 0"),
    )
    op.create_index("ix_lead_pipeline_location_id", "lead_pipeline", ["location_id"])
    op.create_index("ix_lead_pipeline_stage", "lead_pipeline", ["stage"])


def downgrade() -> None:
    op.drop_table("lead_pipeline")
    op.drop_table("location_audit")
    op.drop_table("locations")
