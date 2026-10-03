"""Authenticated explicit integration intents; enqueueing never contacts a vendor."""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from arcagent.config import Settings, get_settings
from arcagent.console.api import Database, authenticate
from arcagent.console.workflows import Actor
from arcagent.integrations.reviews import latest_reviews, record_review, serialize_review
from arcagent.integrations.service import (
    enqueue_delivery,
    integration_readiness,
    serialize_delivery,
)
from arcagent.integrations.worker import dispatch, recover_stale
from arcagent.persistence.integration_models import IntegrationDelivery, IntegrationReview


class SafeIntegrationRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe(request):
            try:
                return await handler(request)
            except RequestValidationError:
                return JSONResponse(
                    {"detail": "Invalid integration request"},
                    status_code=422,
                    headers={"Cache-Control": "no-store"},
                )
            except SQLAlchemyError:
                return JSONResponse(
                    {"detail": "Integration state unavailable. Refresh before retrying."},
                    status_code=503,
                    headers={"Cache-Control": "no-store"},
                )

        return safe


router = APIRouter(
    prefix="/api/console/integrations",
    dependencies=[Depends(authenticate)],
    tags=["integrations"],
    route_class=SafeIntegrationRoute,
)


class DeliveryIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    call_id: int = Field(gt=0, le=2_147_483_646)
    destination: Literal["hubspot", "automation"]
    client_request_id: UUID


@router.get("")
def readiness(settings: Annotated[Settings, Depends(get_settings)]):
    return {
        "destinations": integration_readiness(settings),
        "delivery_mode": "operator_worker",
        "automatic_delivery": False,
    }


@router.get("/deliveries")
def deliveries(
    session: Database,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1_000_000),
    location_id: int | None = Query(None, gt=0),
):
    query = select(IntegrationDelivery)
    count = select(func.count(IntegrationDelivery.id))
    if location_id is not None:
        query = query.where(IntegrationDelivery.location_id == location_id)
        count = count.where(IntegrationDelivery.location_id == location_id)
    rows = session.scalars(
        query.order_by(IntegrationDelivery.id.desc()).limit(limit).offset(offset)
    ).all()
    reviews = latest_reviews(session, [row.id for row in rows])
    return {
        "items": [
            {**serialize_delivery(row), "latest_review": reviews.get(row.id)} for row in rows
        ],
        "total": session.scalar(count),
        "limit": limit,
        "offset": offset,
    }


@router.post("/deliveries", status_code=201)
def queue_delivery(
    body: DeliveryIntent,
    session: Database,
    identity: Actor,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
):
    row, created = enqueue_delivery(
        session,
        call_id=body.call_id,
        destination=body.destination,
        client_request_id=str(body.client_request_id),
        identity=identity,
        settings=settings,
    )
    if not created:
        response.status_code = 200
    return serialize_delivery(row)


class SendIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_delivery: Literal[True]
    expected_attempt_count: int = Field(ge=0, le=2)


@router.post("/deliveries/{delivery_id}/send")
def send_delivery(
    body: SendIntent,
    session: Database,
    identity: Actor,
    settings: Annotated[Settings, Depends(get_settings)],
    delivery_id: int = Path(gt=0, le=2_147_483_646),
):
    if session.get(IntegrationDelivery, delivery_id) is None:
        raise HTTPException(404, "Delivery not found")
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    session.rollback()
    if not dispatch(factory, settings, delivery_id, body.expected_attempt_count, identity=identity):
        raise HTTPException(
            409, "Delivery is not queued, not due, or changed. Refresh before acting."
        )
    session.expire_all()
    return serialize_delivery(session.get(IntegrationDelivery, delivery_id))


class ReviewIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    client_request_id: UUID
    expected_status: Literal["uncertain", "failed"]
    expected_attempt_count: int = Field(ge=0, le=3)
    expected_review_revision: int = Field(ge=0, le=2_147_483_646)
    resolution: Literal["verified_received", "verified_not_received", "needs_followup"]
    evidence: str = Field(min_length=1, max_length=1000)


@router.post("/deliveries/{delivery_id}/reviews", status_code=201)
def review_delivery(
    body: ReviewIntent,
    session: Database,
    identity: Actor,
    response: Response,
    delivery_id: int = Path(gt=0, le=2_147_483_646),
):
    result, created = record_review(session, delivery_id, body, identity)
    if not created:
        response.status_code = 200
    return result


@router.get("/deliveries/{delivery_id}/reviews")
def delivery_reviews(
    session: Database,
    delivery_id: int = Path(gt=0, le=2_147_483_646),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1_000_000),
):
    if session.get(IntegrationDelivery, delivery_id) is None:
        raise HTTPException(404, "Delivery not found")
    query = select(IntegrationReview).where(IntegrationReview.delivery_id == delivery_id)
    rows = session.scalars(query.order_by(IntegrationReview.id.desc()).limit(limit).offset(offset))
    return {
        "items": [serialize_review(row) for row in rows],
        "total": session.scalar(
            select(func.count(IntegrationReview.id)).where(
                IntegrationReview.delivery_id == delivery_id
            )
        ),
        "limit": limit,
        "offset": offset,
    }


class RecoveryIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_recovery: Literal[True]
    limit: int = Field(default=100, ge=1, le=100)


@router.post("/deliveries/recover-stale")
def recover_deliveries(body: RecoveryIntent, session: Database, identity: Actor):
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    session.rollback()
    count = recover_stale(factory, datetime.now(UTC), body.limit, identity=identity)
    return {"recovered": count, "external_requests": False}
