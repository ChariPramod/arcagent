import pytest

from arcagent.config import Settings
from scripts.verify_staging import configuration_issues, validate_target, verify


@pytest.mark.parametrize(
    "url",
    [
        "https://example.test",
        "http://127.0.0.1@evil.test",
        "http://127.0.0.1/path",
        "http://127.0.0.1?redirect=elsewhere",
        "http://127.0.0.1:99999",
        "http://localhost:8000",
    ],
)
def test_probe_rejects_nonliteral_loopback_and_ambiguous_targets(url):
    with pytest.raises(ValueError):
        validate_target(url)


def test_probe_accepts_explicit_loopback_origins():
    assert validate_target("http://127.0.0.1:8000/") == "http://127.0.0.1:8000"
    assert validate_target("http://[::1]:8000") == "http://[::1]:8000"


def test_missing_credentials_fail_before_network(monkeypatch):
    monkeypatch.setattr(
        "scripts.verify_staging.fetch_json", lambda *a: pytest.fail("network called")
    )
    settings = Settings(_env_file=None, env="test", console_api_token="", admin_api_token="")
    assert verify("http://127.0.0.1:8000", settings)


def test_production_mode_with_shared_credentials_is_not_ready():
    settings = Settings(
        _env_file=None, env="prod", console_api_token="a" * 32, admin_api_token="a" * 32
    )
    assert configuration_issues(settings)


def test_http_redirects_cannot_forward_credentials():
    from scripts.verify_staging import NoRedirects

    assert NoRedirects().redirect_request(None, None, 302, "", {}, "https://elsewhere.test") is None


def test_ready_http_does_not_mask_wrong_migration_revision(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from urllib.error import HTTPError

    settings = Settings(
        _env_file=None,
        env="prod",
        console_api_token="a" * 32,
        admin_api_token="b" * 32,
        validate_twilio_signature=True,
        echo_enabled=False,
        enable_audio_evals=False,
    )

    def fetch(origin, path, token=None):
        if path == "/health":
            return {"status": "ok"}
        if token is None:
            raise HTTPError(origin + path, 401, "unauthorized", {}, None)
        return {"readiness": {"ready": True}}

    disposed = []
    monkeypatch.setattr("scripts.verify_staging.fetch_json", fetch)
    monkeypatch.setattr(
        "scripts.verify_staging.create_engine",
        lambda *a, **kw: SimpleNamespace(
            connect=lambda: nullcontext(object()), dispose=lambda: disposed.append(True)
        ),
    )
    monkeypatch.setattr(
        "scripts.verify_staging.MigrationContext.configure",
        lambda connection: SimpleNamespace(get_current_heads=lambda: ("old",)),
    )
    monkeypatch.setattr(
        "scripts.verify_staging.ScriptDirectory.from_config",
        lambda config: SimpleNamespace(get_heads=lambda: ["new"]),
    )
    assert verify("http://127.0.0.1:8000", settings) == [
        "Database migration revision does not match this checkout."
    ]
    assert disposed == [True]
