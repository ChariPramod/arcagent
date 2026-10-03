"""Human reconciliation evidence with independent optimistic concurrency."""

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from arcagent.console.api import iso
from arcagent.persistence.integration_models import IntegrationDelivery, IntegrationReview
from arcagent.persistence.workflow_models import WorkflowAudit


def serialize_review(row: IntegrationReview) -> dict:
    return {
        "id": row.id,
        "delivery_id": row.delivery_id,
        "provider_status": row.provider_status,
        "attempt_count": row.attempt_count,
        "review_revision": row.review_revision,
        "resolution": row.resolution,
        "evidence": row.evidence,
        "created_by": row.created_by,
        "created_at": iso(row.created_at),
    }


def latest_reviews(session, delivery_ids: list[int]) -> dict[int, dict]:
    if not delivery_ids:
        return {}
    latest = (
        select(func.max(IntegrationReview.id))
        .where(IntegrationReview.delivery_id.in_(delivery_ids))
        .group_by(IntegrationReview.delivery_id)
    )
    return {
        row.delivery_id: serialize_review(row)
        for row in session.scalars(
            select(IntegrationReview).where(IntegrationReview.id.in_(latest))
        )
    }


def record_review(session, delivery_id: int, body, identity: str) -> tuple[dict, bool]:
    def replay():
        existing = session.scalar(
            select(IntegrationReview).where(
                IntegrationReview.client_request_id == str(body.client_request_id)
            )
        )
        if existing is None:
            return None
        if (
            existing.delivery_id != delivery_id
            or existing.provider_status != body.expected_status
            or existing.attempt_count != body.expected_attempt_count
            or existing.review_revision != body.expected_review_revision + 1
            or existing.resolution != body.resolution
            or existing.evidence != body.evidence
            or existing.created_by != identity
        ):
            raise HTTPException(409, "Request identifier belongs to a different review")
        return serialize_review(existing), False

    repeated = replay()
    if repeated is not None:
        return repeated
    row = session.get(IntegrationDelivery, delivery_id)
    if row is None:
        raise HTTPException(404, "Delivery not found")
    try:
        changed = session.execute(
            update(IntegrationDelivery)
            .where(
                IntegrationDelivery.id == delivery_id,
                IntegrationDelivery.status == body.expected_status,
                IntegrationDelivery.status.in_(("uncertain", "failed")),
                IntegrationDelivery.attempt_count == body.expected_attempt_count,
                IntegrationDelivery.review_revision == body.expected_review_revision,
            )
            .values(review_revision=IntegrationDelivery.review_revision + 1)
        )
        if changed.rowcount != 1:
            session.rollback()
            repeated = replay()
            if repeated is not None:
                return repeated
            raise HTTPException(409, "Delivery or review changed. Refresh before reviewing.")
        review = IntegrationReview(
            delivery_id=delivery_id,
            client_request_id=str(body.client_request_id),
            provider_status=body.expected_status,
            attempt_count=body.expected_attempt_count,
            review_revision=body.expected_review_revision + 1,
            resolution=body.resolution,
            evidence=body.evidence,
            created_by=identity,
        )
        session.add(review)
        session.flush()
        session.add(
            WorkflowAudit(
                call_id=row.call_id,
                entity="integration",
                entity_id=delivery_id,
                revision=review.review_revision,
                actor=identity,
                action="reviewed",
                changes={
                    "review_id": review.id,
                    "resolution": review.resolution,
                    "provider_status": review.provider_status,
                    "attempt_count": review.attempt_count,
                    "review_revision": review.review_revision,
                },
            )
        )
        session.commit()
        return serialize_review(review), True
    except IntegrityError:
        session.rollback()
        repeated = replay()
        if repeated is not None:
            return repeated
        raise HTTPException(409, "Review changed. Refresh before reviewing.") from None
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(
            503, "Review could not be confirmed. Refresh before retrying."
        ) from None
