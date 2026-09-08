"""TwiML documents returned to Twilio.

Kept in one module so every document the app can emit is visible in one place and testable
without an HTTP request.
"""

from __future__ import annotations

from twilio.twiml.voice_response import Connect, VoiceResponse


def connect_stream(stream_url: str) -> str:
    """Answer an inbound call by opening a bidirectional media stream to ``stream_url``."""
    response = VoiceResponse()
    connect = Connect()
    connect.stream(url=stream_url)
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
