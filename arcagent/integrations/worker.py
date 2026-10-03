"""Durable single-attempt dispatcher. CLI is read-only unless --send is explicit."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx
from sqlalchemy import or_, select, update
from sqlalchemy.exc import SQLAlchemyError

from arcagent.config import get_settings
from arcagent.integrations.service import (
    Destination,
    audit_delivery,
    configured_destination,
    resolve_public_address,
)
from arcagent.persistence.db import get_session_factory
from arcagent.persistence.integration_models import IntegrationDelivery
from arcagent.persistence.pipeline_models import LeadPipeline, Location

MAX_ATTEMPTS = 3
SENDING_LEASE_SECONDS = 120


@dataclass(frozen=True)
class Attempt:
    id: int
    attempt_count: int
    destination: str
    idempotency_key: str
    config_fingerprint: str = field(repr=False)
    payload: dict = field(repr=False)


def claim(
    factory, delivery_id: int, expected_attempt_count: int, now: datetime, identity: str
) -> Attempt | None:
    with factory() as session:
        result = session.execute(
            update(IntegrationDelivery)
            .where(
                IntegrationDelivery.id == delivery_id,
                IntegrationDelivery.status == "queued",
                IntegrationDelivery.attempt_count == expected_attempt_count,
                IntegrationDelivery.attempt_count < MAX_ATTEMPTS,
                or_(
                    IntegrationDelivery.next_attempt_at.is_(None),
                    IntegrationDelivery.next_attempt_at <= now,
                ),
            )
            .values(
                status="sending",
                attempt_count=IntegrationDelivery.attempt_count + 1,
                updated_by=identity,
                updated_at=now,
                last_attempt_at=now,
                next_attempt_at=None,
                error_code=None,
            )
        )
        if result.rowcount != 1:
            session.rollback()
            return None
        row = session.get(IntegrationDelivery, delivery_id)
        audit_delivery(session, row, identity, "sending")
        attempt = Attempt(
            row.id,
            row.attempt_count,
            row.destination,
            f"arcagent-delivery-{row.client_request_id}",
            row.config_fingerprint,
            row.payload,
        )
        # Commit before I/O. A crash after this point requires reconciliation, never blind replay.
        session.commit()
        return attempt


def finish(factory, attempt: Attempt, status: str, error: str | None, now: datetime) -> bool:
    with factory() as session:
        result = session.execute(
            update(IntegrationDelivery)
            .where(
                IntegrationDelivery.id == attempt.id,
                IntegrationDelivery.status == "sending",
                IntegrationDelivery.attempt_count == attempt.attempt_count,
            )
            .values(
                status=status,
                error_code=error,
                updated_at=now,
                next_attempt_at=(now + timedelta(seconds=60 * 2 ** (attempt.attempt_count - 1)))
                if status == "queued"
                else None,
            )
        )
        if result.rowcount != 1:
            session.rollback()
            return False
        row = session.get(IntegrationDelivery, attempt.id)
        audit_delivery(session, row, "integration-worker", status)
        session.commit()
        return True


def recover_stale(factory, now: datetime, limit: int = 100) -> int:
    """Expired claims become uncertain, regardless of whether the process reached the vendor."""
    count = 0
    with factory() as session:
        rows = session.scalars(
            select(IntegrationDelivery)
            .where(
                IntegrationDelivery.status == "sending",
                IntegrationDelivery.last_attempt_at
                < now - timedelta(seconds=SENDING_LEASE_SECONDS),
            )
            .limit(limit)
        ).all()
        for row in rows:
            result = session.execute(
                update(IntegrationDelivery)
                .where(
                    IntegrationDelivery.id == row.id,
                    IntegrationDelivery.status == "sending",
                    IntegrationDelivery.attempt_count == row.attempt_count,
                    IntegrationDelivery.last_attempt_at == row.last_attempt_at,
                )
                .values(status="uncertain", error_code="worker_interrupted", updated_at=now)
            )
            if result.rowcount == 1:
                session.refresh(row)
                audit_delivery(session, row, "integration-worker", "uncertain")
                count += 1
        session.commit()
    return count


def send_http(config: Destination, attempt: Attempt, timeout: float) -> int:
    ip = resolve_public_address(config)
    if ip is None:
        raise DestinationUnavailable()
    host = urlsplit(config.url).hostname
    headers = {"Host": host, "Idempotency-Key": attempt.idempotency_key}
    if config.name == "hubspot":
        headers["Authorization"] = f"Bearer {config.token}"
        contact = attempt.payload["contact"]
        # Preserve the supplied name without inferring how a person's name is partitioned.
        payload = {"properties": {"firstname": contact["name"], "phone": contact["phone"]}}
    else:
        payload = {
            "event_id": attempt.idempotency_key,
            "event": "arcagent.contact_export",
            **attempt.payload,
        }
    # Pin the validated public IP. TLS still verifies the original hostname; no DNS rebinding gap.
    url = httpx.URL(config.url).copy_with(host=ip)
    with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        with client.stream(
            "POST", url, json=payload, headers=headers, extensions={"sni_hostname": host}
        ) as response:
            # Never buffer/log vendor bodies, which may echo credentials or contact data.
            return response.status_code


class DestinationUnavailable(Exception):
    """Destination failed public-address validation before sending."""


def dispatch(
    factory,
    settings,
    delivery_id: int,
    expected_attempt_count: int,
    *,
    sender: Callable = send_http,
    now: datetime | None = None,
    identity: str = "integration-worker",
) -> bool:
    now = now or datetime.now(UTC)
    attempt = claim(factory, delivery_id, expected_attempt_count, now, identity)
    if attempt is None:
        return False
    with factory() as session:
        row = session.get(IntegrationDelivery, attempt.id)
        location = session.get(Location, row.location_id)
        pipeline = session.scalar(select(LeadPipeline).where(LeadPipeline.call_id == row.call_id))
        valid_location = (
            location and location.active and pipeline and pipeline.location_id == row.location_id
        )
    if not valid_location:
        return finish(factory, attempt, "failed", "location_changed", now)
    config = configured_destination(settings, attempt.destination)
    if config is None or config.fingerprint != attempt.config_fingerprint:
        return finish(factory, attempt, "failed", "configuration_changed", now)
    try:
        timeout = min(10.0, max(1.0, float(getattr(settings, "integration_delivery_timeout_s", 5))))
        status = sender(config, attempt, timeout)
    except DestinationUnavailable:
        return finish(
            factory,
            attempt,
            "queued" if attempt.attempt_count < MAX_ATTEMPTS else "failed",
            "destination_unavailable",
            now,
        )
    except Exception:
        # Even a network exception can follow remote acceptance. Never log exception text.
        return finish(factory, attempt, "uncertain", "response_unknown", now)
    if (attempt.destination == "hubspot" and status == 201) or (
        attempt.destination == "automation" and 200 <= status < 300
    ):
        return finish(factory, attempt, "delivered", None, now)
    if attempt.destination == "hubspot" and status == 429:
        return finish(
            factory,
            attempt,
            "queued" if attempt.attempt_count < MAX_ATTEMPTS else "failed",
            "rate_limited",
            now,
        )
    if attempt.destination == "hubspot" and status in (400, 401, 403, 404, 405, 410, 413, 415, 422):
        return finish(factory, attempt, "failed", "request_rejected", now)
    # 5xx, redirects, nonstandard responses, and automation 429 are not proof of no side effect.
    return finish(factory, attempt, "uncertain", "response_unknown", now)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send", action="store_true", help="Explicitly send queued contacts")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be between 1 and 100")
    settings = get_settings()
    factory = get_session_factory(settings.database_url)
    now = datetime.now(UTC)
    try:
        if args.send:
            recover_stale(factory, now)
        with factory() as session:
            rows = session.execute(
                select(IntegrationDelivery.id, IntegrationDelivery.attempt_count)
                .where(
                    IntegrationDelivery.status == "queued",
                    or_(
                        IntegrationDelivery.next_attempt_at.is_(None),
                        IntegrationDelivery.next_attempt_at <= now,
                    ),
                )
                .order_by(IntegrationDelivery.id)
                .limit(args.limit)
            ).all()
        if not args.send:
            print(json.dumps({"mode": "dry_run", "due_delivery_ids": [row.id for row in rows]}))
            return 0
        for row in rows:
            dispatch(factory, settings, row.id, row.attempt_count)
        print(json.dumps({"mode": "send", "considered": len(rows)}))
        return 0
    except SQLAlchemyError:
        print(json.dumps({"error": "database_unavailable", "action": "review before retrying"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
