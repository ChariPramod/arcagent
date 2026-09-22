"""Read-only local staging gate. Never starts calls, migrates, or prints credentials."""

from __future__ import annotations

import argparse
import ipaddress
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from arcagent.config import Settings


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_target(value: str) -> str:
    url = urlsplit(value)
    try:
        loopback = ipaddress.ip_address(url.hostname or "").is_loopback
        valid_port = url.port is None or 0 < url.port <= 65535
    except ValueError:
        loopback, valid_port = False, False
    if (
        not loopback
        or not valid_port
        or url.scheme != "http"
        or url.username
        or url.password
        or url.path not in ("", "/")
        or url.query
        or url.fragment
    ):
        raise ValueError("The probe requires an explicit HTTP loopback origin.")
    return value.rstrip("/")


def configuration_issues(settings: Settings) -> list[str]:
    issues = []
    if settings.env != "prod" or not settings.validate_twilio_signature:
        issues.append("Production signature enforcement is required.")
    if settings.echo_enabled or settings.enable_audio_evals:
        issues.append("Echo and audio evaluation ingress must be disabled.")
    tokens = (settings.console_api_token, settings.admin_api_token)
    if any(len(t.strip()) < 32 for t in tokens) or tokens[0] == tokens[1]:
        issues.append(
            "Independent console and admin tokens of at least 32 characters are required."
        )
    if not settings.database_url.startswith("postgresql+psycopg://"):
        issues.append("The staging gate requires PostgreSQL.")
    return issues


def fetch_json(origin: str, path: str, token: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with build_opener(NoRedirects()).open(Request(origin + path, headers=headers), timeout=5) as r:
        raw = r.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("Response exceeds probe size limit.")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("Expected an object response.")
        return value


def verify(origin: str, settings: Settings) -> list[str]:
    issues = configuration_issues(settings)
    if issues:
        return issues
    try:
        if fetch_json(origin, "/health").get("status") != "ok":
            issues.append("Liveness did not report ok.")
        try:
            fetch_json(origin, "/api/console/operations")
            issues.append("Unauthenticated console access was accepted.")
        except HTTPError as exc:
            if exc.code != 401:
                issues.append("Unauthenticated console request did not return 401.")
        status = fetch_json(origin, "/api/console/operations", settings.console_api_token)
        if status.get("readiness", {}).get("ready") is not True:
            issues.append("Configuration/database readiness is blocked.")
    except (URLError, OSError, ValueError, AttributeError):
        issues.append(
            "Local HTTP verification failed; inspect service health without exposing secrets."
        )
    engine = create_engine(
        settings.database_url,
        connect_args={"connect_timeout": 5, "options": "-c statement_timeout=5000"},
    )
    try:
        with engine.connect() as connection:
            current = set(MigrationContext.configure(connection).get_current_heads())
        expected = set(ScriptDirectory.from_config(Config("alembic.ini")).get_heads())
        if current != expected:
            issues.append("Database migration revision does not match this checkout.")
    except SQLAlchemyError:
        issues.append("Database migration revision could not be verified.")
    finally:
        engine.dispose()
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    try:
        origin = validate_target(args.base_url)
        settings = Settings(_env_file=None)
        issues = verify(origin, settings)
    except Exception:
        # Configuration exceptions can embed input values; never print them.
        print("BLOCKED: Invalid staging configuration or probe execution failure.", file=sys.stderr)
        return 1
    for issue in issues:
        print(f"BLOCKED: {issue}")
    if not issues:
        print(
            "PASS: Local configuration, auth, schema, and database checks. Live vendors unverified."
        )
    return int(bool(issues))


if __name__ == "__main__":
    raise SystemExit(main())
