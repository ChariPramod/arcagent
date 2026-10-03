"""Contact-only outbox intents and destination policy. No network calls on queueing."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from arcagent.console.api import iso
from arcagent.persistence.integration_models import IntegrationDelivery
from arcagent.persistence.models import Call, Lead
from arcagent.persistence.pipeline_models import LeadPipeline, Location
from arcagent.persistence.workflow_models import WorkflowAudit

HUBSPOT_URL = "https://api.hubapi.com/crm/v3/objects/contacts"


@dataclass(frozen=True)
class Destination:
    name: str
    url: str = field(repr=False)
    token: str = field(default="", repr=False)

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(f"{self.name}\0{self.url}\0{self.token}".encode()).hexdigest()


def configured_destination(settings, name: str) -> Destination | None:
    if name == "hubspot":
        token = getattr(settings, "hubspot_access_token", "").strip()
        if token and not any(ord(c) < 33 for c in token):
            return Destination(name, HUBSPOT_URL, token)
        return None
    if name != "automation":
        return None
    value = getattr(settings, "automation_webhook_url", "").strip()
    try:
        url = urlsplit(value)
        host = url.hostname or ""
        valid_host = (
            (host == "hooks.zapier.com" and url.path.startswith("/hooks/catch/"))
            or (re.fullmatch(r"hook\.(?:eu|us)[1-9]\.make\.com", host) and len(url.path) > 1)
            or (
                re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.app\.n8n\.cloud", host)
                and url.path.startswith("/webhook/")
            )
        )
        if (
            url.scheme != "https"
            or not valid_host
            or url.username is not None
            or url.password is not None
            or url.port not in (None, 443)
            or url.query
            or url.fragment
            or any(ord(c) < 33 for c in value)
            or "\\" in value
        ):
            return None
    except ValueError:
        return None
    return Destination(name, value)


def integration_readiness(settings) -> list[dict]:
    return [
        {
            "destination": name,
            "configured": configured_destination(settings, name) is not None,
            "detail": (
                "Configured; connectivity and receiver behavior unverified."
                if configured_destination(settings, name)
                else "A server-side destination must be configured."
            ),
        }
        for name in ("hubspot", "automation")
    ]


def _bounded_dns(host: str) -> list[str]:
    # Isolate libc DNS resolution so timeout actually terminates it, including in the CLI.
    code = (
        "import socket,json,sys; "
        "print(json.dumps([r[4][0] for r in "
        "socket.getaddrinfo(sys.argv[1],443,type=socket.SOCK_STREAM)]))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, host], capture_output=True, text=True, timeout=2, check=True
    )
    addresses = json.loads(result.stdout)
    if not isinstance(addresses, list) or not 1 <= len(addresses) <= 64:
        return []
    return addresses


def resolve_public_address(destination: Destination, resolver=None) -> str | None:
    """Bound DNS, reject any nonpublic answer, and return an address to pin for TLS."""
    try:
        host = urlsplit(destination.url).hostname
        addresses = (
            [row[4][0] for row in resolver(host, 443, type=socket.SOCK_STREAM)]
            if resolver is not None
            else _bounded_dns(host)
        )
        if not addresses or not all(
            ipaddress.ip_address(address).is_global for address in addresses
        ):
            return None
        return addresses[0]
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return None


def serialize_delivery(row: IntegrationDelivery) -> dict:
    # Explicit allowlist: expose only the contact fields an operator must confirm.
    # Never expose raw payloads, tokens, URLs or fingerprints.
    values = {
        name: getattr(row, name)
        for name in (
            "id",
            "call_id",
            "location_id",
            "location_name",
            "destination",
            "status",
            "attempt_count",
            "review_revision",
            "error_code",
            "created_by",
            "updated_by",
        )
    }
    values["contact_name"] = row.payload["contact"]["name"]
    values["contact_phone"] = row.payload["contact"]["phone"]
    for name in ("created_at", "updated_at", "last_attempt_at", "next_attempt_at"):
        values[name] = iso(getattr(row, name))
    return values


def audit_delivery(session: Session, row: IntegrationDelivery, actor: str, action: str) -> None:
    session.add(
        WorkflowAudit(
            call_id=row.call_id,
            entity="integration",
            entity_id=row.id,
            revision=row.attempt_count + 1,
            actor=actor,
            action=action,
            changes={
                "destination": row.destination,
                "location_id": row.location_id,
                "status": row.status,
                "attempt_count": row.attempt_count,
                "error_code": row.error_code,
            },
        )
    )


def enqueue_delivery(
    session: Session,
    *,
    call_id: int,
    destination: str,
    client_request_id: str,
    identity: str,
    settings,
) -> tuple[IntegrationDelivery, bool]:
    existing = session.scalar(
        select(IntegrationDelivery).where(
            IntegrationDelivery.client_request_id == client_request_id
        )
    )
    if existing:
        if (existing.call_id, existing.destination, existing.created_by) != (
            call_id,
            destination,
            identity,
        ):
            raise HTTPException(409, "Request ID belongs to a different delivery intent")
        return existing, False
    existing = session.scalar(
        select(IntegrationDelivery).where(
            IntegrationDelivery.call_id == call_id, IntegrationDelivery.destination == destination
        )
    )
    if existing:
        return existing, False
    config = configured_destination(settings, destination)
    if config is None:
        raise HTTPException(503, "This integration is not configured")
    if session.get(Call, call_id) is None:
        raise HTTPException(404, "Call not found")
    pipeline = session.scalar(select(LeadPipeline).where(LeadPipeline.call_id == call_id))
    location = (
        session.get(Location, pipeline.location_id) if pipeline and pipeline.location_id else None
    )
    if location is None or not location.active:
        raise HTTPException(409, "Assign this call to an active location before exporting")
    lead = session.scalar(
        select(Lead).where(Lead.call_id == call_id).order_by(Lead.id.desc()).limit(1)
    )
    name = (lead.name or "").strip() if lead else ""
    phone = (lead.callback_number or "").strip() if lead else ""
    if not name or not re.fullmatch(r"\+[1-9]\d{7,14}", phone):
        raise HTTPException(409, "A contact name and international callback number are required")
    # No clinical data, transcripts, scores, notes, insurance, or inferred email.
    contact = {"name": name[:128], "phone": phone}
    row = IntegrationDelivery(
        call_id=call_id,
        location_id=location.id,
        location_name=location.name,
        destination=destination,
        client_request_id=client_request_id,
        payload={"contact": contact, "location": {"id": location.id, "name": location.name}},
        config_fingerprint=config.fingerprint,
        created_by=identity,
        updated_by=identity,
        status="queued",
        attempt_count=0,
        updated_at=datetime.now(UTC),
    )
    try:
        session.add(row)
        session.flush()
        audit_delivery(session, row, identity, "queued")
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(IntegrationDelivery).where(
                IntegrationDelivery.client_request_id == client_request_id
            )
        )
        if existing and (existing.call_id, existing.destination, existing.created_by) != (
            call_id,
            destination,
            identity,
        ):
            raise HTTPException(409, "Request ID belongs to a different delivery intent") from None
        if existing is None:
            existing = session.scalar(
                select(IntegrationDelivery).where(
                    IntegrationDelivery.call_id == call_id,
                    IntegrationDelivery.destination == destination,
                )
            )
        if existing is None:
            raise HTTPException(
                409, "Delivery changed while queueing. Refresh before acting."
            ) from None
        return existing, False
    return row, True
