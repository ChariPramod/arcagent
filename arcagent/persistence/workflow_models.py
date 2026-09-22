"""Coordinator work and synthetic feedback, separate from automated call actions."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from arcagent.persistence.models import Base, JsonCol


class FollowupTask(Base):
    __tablename__ = "followup_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    assignee: Mapped[str | None] = mapped_column(String(128))
    notes: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[int] = mapped_column(default=1)
    created_by: Mapped[str] = mapped_column(String(128))
    updated_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RegressionFeedback(Base):
    __tablename__ = "regression_feedback"
    client_request_id: Mapped[str] = mapped_column(
        String(36), unique=True, default=lambda: str(uuid4())
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(40))
    scenario: Mapped[str] = mapped_column(Text)
    expected_behavior: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    revision: Mapped[int] = mapped_column(default=1)
    created_by: Mapped[str] = mapped_column(String(128))
    reviewed_by: Mapped[str | None] = mapped_column(String(128))
    review_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowAudit(Base):
    __tablename__ = "workflow_audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), index=True)
    entity: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[int] = mapped_column(index=True)
    revision: Mapped[int]
    actor: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(30))
    changes: Mapped[dict] = mapped_column(JsonCol)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
