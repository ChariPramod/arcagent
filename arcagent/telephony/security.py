"""Twilio webhook signature validation.

Twilio signs every webhook with ``X-Twilio-Signature``: an HMAC-SHA1 over the full request
URL plus the sorted POST parameters, keyed with the account auth token. Without this check
anyone who learns the ngrok URL can drive the agent.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from twilio.request_validator import RequestValidator

from arcagent.config import Settings, get_settings
from arcagent.logging import get_logger

log = get_logger(__name__)

SIGNATURE_HEADER = "X-Twilio-Signature"


def _public_request_url(request: Request, settings: Settings) -> str:
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
    if not settings.validate_twilio_signature:
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
