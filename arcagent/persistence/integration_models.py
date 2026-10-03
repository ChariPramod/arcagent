"""Durable, explicitly requested outbound contact deliveries."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from arcagent.persistence.models import Base, JsonCol


class IntegrationDelivery(Base):
    __tablename__ = "integration_deliveries"
    __table_args__ = (
        UniqueConstraint("call_id", "destination"),
        CheckConstraint("destination IN ('hubspot','automation')"),
        CheckConstraint("status IN ('queued','sending','delivered','failed','uncertain')"),
        CheckConstraint("attempt_count >= 0 AND attempt_count <= 3"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), index=True)
    location_name: Mapped[str] = mapped_column(String(128))
    destination: Mapped[str] = mapped_column(String(20))
    client_request_id: Mapped[str] = mapped_column(String(36), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    attempt_count: Mapped[int] = mapped_column(default=0)
    review_revision: Mapped[int] = mapped_column(default=0, server_default="0")
    payload: Mapped[dict] = mapped_column(JsonCol)
    config_fingerprint: Mapped[str] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(40))
    created_by: Mapped[str] = mapped_column(String(128))
    updated_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IntegrationReview(Base):
    """Append-only operator evidence; never substitutes for provider delivery status."""

    __tablename__ = "integration_reviews"
    __table_args__ = (
        UniqueConstraint("delivery_id", "review_revision"),
        CheckConstraint("provider_status IN ('failed','uncertain')"),
        CheckConstraint(
            "resolution IN ('verified_received','verified_not_received','needs_followup')"
        ),
        CheckConstraint("attempt_count >= 0 AND attempt_count <= 3"),
        CheckConstraint("review_revision > 0"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_id: Mapped[int] = mapped_column(
        ForeignKey("integration_deliveries.id", ondelete="CASCADE"), index=True
    )
    client_request_id: Mapped[str] = mapped_column(String(36), unique=True)
    provider_status: Mapped[str] = mapped_column(String(16))
    attempt_count: Mapped[int]
    review_revision: Mapped[int]
    resolution: Mapped[str] = mapped_column(String(32))
    evidence: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
