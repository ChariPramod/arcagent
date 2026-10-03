"""Single-group operator conversion state, independent of telephone outcomes."""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from arcagent.persistence.models import Base, JsonCol


class LeadPipeline(Base):
    __tablename__ = "lead_pipeline"
    __table_args__ = (
        CheckConstraint("stage IN ('new','contacted','booked','won','lost')"),
        CheckConstraint("revision > 0"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), unique=True)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"), index=True)
    stage: Mapped[str] = mapped_column(String(16), default="new", index=True)
    assignee: Mapped[str | None] = mapped_column(String(128))
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[int] = mapped_column(default=1)
    updated_by: Mapped[str] = mapped_column(String(128))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Location(Base):
    __tablename__ = "locations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    timezone: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(default=1)
    updated_by: Mapped[str] = mapped_column(String(128))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LocationAudit(Base):
    __tablename__ = "location_audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), index=True)
    revision: Mapped[int]
    actor: Mapped[str] = mapped_column(String(128))
    changes: Mapped[dict] = mapped_column(JsonCol)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
