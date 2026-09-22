"""Durable transfer intent and verified terminal evidence, without caller PII."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from arcagent.persistence.models import Base


class TransferAttempt(Base):
    __tablename__ = "transfer_attempts"
    __table_args__ = (
        CheckConstraint("request_status IN ('pending','accepted','failed','uncertain')"),
        CheckConstraint(
            "outcome IS NULL OR outcome IN "
            "('completed','no_answer','busy','failed','canceled','unbridged')"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), unique=True)
    request_status: Mapped[str] = mapped_column(String(16), default="pending")
    child_call_sid: Mapped[str | None] = mapped_column(String(64), unique=True)
    outcome: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TransferProgress(Base):
    __tablename__ = "transfer_progress"
    __table_args__ = (UniqueConstraint("attempt_id", "sequence"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("transfer_attempts.id", ondelete="CASCADE"))
    sequence: Mapped[int]
    status: Mapped[str] = mapped_column(String(16))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
