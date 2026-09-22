"""Persist coordinator work and independently reviewed regression candidates.

Revision ID: c21ab845df10
Revises: b8e5f431a290
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'c21ab845df10'
down_revision = 'b8e5f431a290'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('followup_tasks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('call_id', sa.Integer(), sa.ForeignKey('calls.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('assignee', sa.String(128)),
        sa.Column('notes', sa.Text(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('created_by', sa.String(128), nullable=False),
        sa.Column('updated_by', sa.String(128), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_followup_tasks_status', 'followup_tasks', ['status'])
    op.create_table('regression_feedback',
        sa.Column('client_request_id', sa.String(36), nullable=False, unique=True),
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('call_id', sa.Integer(), sa.ForeignKey('calls.id', ondelete='CASCADE'), nullable=False),
        sa.Column('category', sa.String(40), nullable=False),
        sa.Column('scenario', sa.Text(), nullable=False),
        sa.Column('expected_behavior', sa.Text(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('created_by', sa.String(128), nullable=False),
        sa.Column('reviewed_by', sa.String(128)),
        sa.Column('review_note', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('reviewed_at', sa.DateTime(timezone=True)),
    )
    op.create_index('ix_regression_feedback_call_id', 'regression_feedback', ['call_id'])
    op.create_index('ix_regression_feedback_status', 'regression_feedback', ['status'])
    op.create_table('workflow_audit',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('call_id', sa.Integer(), sa.ForeignKey('calls.id', ondelete='CASCADE'), nullable=False),
        sa.Column('entity', sa.String(20), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('actor', sa.String(128), nullable=False),
        sa.Column('action', sa.String(30), nullable=False),
        sa.Column('changes', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_workflow_audit_call_id', 'workflow_audit', ['call_id'])
    op.create_index('ix_workflow_audit_entity_id', 'workflow_audit', ['entity_id'])


def downgrade() -> None:
    op.drop_table('workflow_audit')
    op.drop_table('regression_feedback')
    op.drop_table('followup_tasks')
