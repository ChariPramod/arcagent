"""TwiML documents returned to Twilio.

Kept in one module so every document the app can emit is visible in one place and testable
without an HTTP request.
"""

from __future__ import annotations

from twilio.twiml.voice_response import Connect, VoiceResponse


def connect_stream(stream_url: str, parameters: dict[str, str] | None = None) -> str:
    """Answer an inbound call by opening a bidirectional media stream to ``stream_url``.

    ``parameters`` become ``<Parameter>`` children and arrive back as ``customParameters``
    on the ``start`` event. This is how the call sid and the caller's number reach the
    WebSocket handler, which never sees the original webhook request.
    """
    response = VoiceResponse()
    connect = Connect()
    stream = connect.stream(url=stream_url)
    for name, value in (parameters or {}).items():
        stream.parameter(name=name, value=value)
    response.append(connect)
    return str(response)


def dial_coordinator(number: str) -> str:
    """Warm transfer: replace the live call's TwiML with a dial to the coordinator."""
    response = VoiceResponse()
    response.dial(number)
    return str(response)


def say_and_hangup(message: str, language: str = "en-US") -> str:
    """Fallback document used when the media stream cannot be opened."""
    response = VoiceResponse()
    response.say(message, language=language)
    response.hangup()
    return str(response)
