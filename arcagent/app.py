"""FastAPI application: Twilio webhooks and the media stream WebSocket."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from arcagent import __version__
from arcagent.config import get_settings
from arcagent.logging import configure_logging, get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.env == "prod")
    log.info("startup", env=settings.env, version=__version__)
    yield
    log.info("shutdown")


app = FastAPI(title="ArcAgent", version=__version__, lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe. Reports nothing about configuration or credentials."""
    return {"status": "ok", "version": __version__}
