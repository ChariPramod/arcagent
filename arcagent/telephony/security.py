"""Twilio webhook signature validation.

Twilio signs every webhook with ``X-Twilio-Signature``: an HMAC-SHA1 over the full request
URL plus the sorted POST parameters, keyed with the account auth token. Without this check
anyone who learns the ngrok URL can drive the agent.
"""

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Request, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from twilio.request_validator import RequestValidator

from arcagent.config import Settings, get_settings
from arcagent.logging import get_logger

log = get_logger(__name__)

SIGNATURE_HEADER = "X-Twilio-Signature"


def _public_request_url(request: Request | WebSocket, settings: Settings) -> str:
    """The URL Twilio signed.

    Behind ngrok the app sees ``http://localhost:8000/...`` while Twilio signed the public
    https URL, so the signature is computed against PUBLIC_URL when one is configured.
    """
    if not settings.public_url:
        return str(request.url)
    base = settings.public_url.rstrip("/")
    if not base.startswith("http"):
        base = f"https://{base}"
    return f"{base}{request.url.path}" + (f"?{request.url.query}" if request.url.query else "")


async def validate_twilio_request(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    """FastAPI dependency. Rejects a request that Twilio did not sign.

    Raises:
        HTTPException: 403 when the signature is absent or does not match.
    """
    if not settings.validate_twilio_signature and settings.env != "prod":
        log.warning("twilio_signature_validation_disabled", path=request.url.path)
        return
    if not settings.twilio_auth_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="signature validation is enabled but TWILIO_AUTH_TOKEN is not set",
        )

    signature = request.headers.get(SIGNATURE_HEADER, "")
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}
    url = _public_request_url(request, settings)

    if not RequestValidator(settings.twilio_auth_token).validate(url, params, signature):
        log.warning("twilio_signature_rejected", path=request.url.path)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid signature")


async def validate_twilio_websocket(websocket: WebSocket, settings: Settings) -> bool:
    """Authenticate the upgrade before accepting or opening billed vendor streams.

    Twilio signs the public WSS URL, not the internal proxy host. Its security
    documentation also describes a trailing slash variant for voice handshakes.
    """
    if not settings.validate_twilio_signature and settings.env != "prod":
        log.warning("twilio_signature_validation_disabled", path=websocket.url.path)
        return True
    if not settings.twilio_auth_token:
        await websocket.close(code=1008)
        return False
    url = _public_request_url(websocket, settings)
    url = url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    signature = websocket.headers.get(SIGNATURE_HEADER, "")
    validator = RequestValidator(settings.twilio_auth_token)
    path, separator, query = url.partition("?")
    slash_url = path.rstrip("/") + "/" + (separator + query if separator else "")
    if not any(validator.validate(candidate, {}, signature) for candidate in (url, slash_url)):
        log.warning("twilio_signature_rejected", path=websocket.url.path)
        await websocket.close(code=1008)
        return False
    return True


_admin_bearer = HTTPBearer(auto_error=False)


def validate_admin_request(
    credentials: HTTPAuthorizationCredentials | None = Depends(_admin_bearer),
    settings: Settings = Depends(get_settings),
) -> None:
    """Dedicated administrative capability; the read-only console token cannot mutate calls."""
    if not settings.admin_api_token:
        raise HTTPException(status_code=503, detail="administrative API is not configured")
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode(), settings.admin_api_token.encode()
    ):
        raise HTTPException(status_code=401, detail="invalid administrative credentials")


async def validate_audio_eval_websocket(websocket: WebSocket, settings: Settings) -> bool:
    """An isolated test capability never opens an unsigned production voice route."""
    authorization = websocket.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if (
        settings.env != "test"
        or not settings.enable_audio_evals
        or not settings.audio_eval_token
        or scheme.lower() != "bearer"
        or not secrets.compare_digest(token.encode(), settings.audio_eval_token.encode())
    ):
        await websocket.close(code=1008)
        return False
    return True
