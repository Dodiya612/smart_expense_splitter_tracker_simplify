"""Unit tests for the shared rate limiter core (T-39).

Run on the in-memory counter store and frozen clock from tests/rate_limit_fakes.py (see
conftest). The SQL store itself is verified on real PostgreSQL in tests/test_rate_limit_pg.py.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core import rate_limiter
from app.core.config import settings
from app.core.rate_limiter import (
    Policy,
    RateLimiterUnavailable,
    clear,
    get_client_ip,
    get_policy,
    hash_identifier,
    hit,
    purge_expired,
    refund,
    reserve,
    window_bounds,
)
from app.main import app, http_exception_handler
from tests import rate_limit_fakes as fakes

POLICY = Policy(scope="unit", limit=3, window_seconds=900)


def make_request(headers: dict[str, str] | None = None, client: tuple[str, int] = ("10.0.0.1", 1234)) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": raw, "client": client})


# ---- hashing and windows ----------------------------------------------------------------


def test_identifiers_are_stored_only_as_keyed_hashes():
    digest = hash_identifier("login_account", "victim@example.com")
    assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
    assert "victim" not in digest
    assert digest == hash_identifier("login_account", "victim@example.com")
    assert digest != hash_identifier("login_ip", "victim@example.com")  # scope is part of the hash


def test_hash_depends_on_the_server_secret(monkeypatch):
    before = hash_identifier("s", "x")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "another-secret-key-with-at-least-32-bytes!!")
    assert hash_identifier("s", "x") != before


def test_windows_are_epoch_aligned_and_identical_on_every_worker():
    start, end = window_bounds(POLICY, fakes.START + timedelta(minutes=10, seconds=30))
    assert (start, end) == (fakes.START, fakes.START + timedelta(minutes=15))
    assert window_bounds(POLICY, fakes.START + timedelta(minutes=15)) [0] == end


# ---- hit / reserve ----------------------------------------------------------------------


@pytest.mark.anyio
async def test_hit_counts_and_reports_the_remaining_window_as_retry_after():
    first = await hit(POLICY, "a")
    assert (first.count, first.retry_after) == (1, 900)
    fakes.advance(100)
    second = await hit(POLICY, "a")
    assert (second.count, second.retry_after) == (2, 800)
    fakes.advance(799.5)
    assert (await hit(POLICY, "a")).retry_after == 1  # always a positive integer


@pytest.mark.anyio
async def test_identifiers_do_not_share_counters():
    for _ in range(3):
        await hit(POLICY, "a")
    assert (await hit(POLICY, "b")).count == 1


@pytest.mark.anyio
async def test_reserve_allows_up_to_the_limit_then_raises_429_with_a_positive_retry_after():
    for _ in range(3):
        await reserve([(POLICY, "a")])
    with pytest.raises(HTTPException) as exc:
        await reserve([(POLICY, "a")])
    assert exc.value.status_code == 429
    assert exc.value.detail["code"] == "RATE_LIMIT_EXCEEDED"
    retry_after = int(exc.value.headers["Retry-After"])
    assert retry_after == 900 and retry_after > 0
    assert "900 seconds" in exc.value.detail["message"]


@pytest.mark.anyio
async def test_custom_message_and_largest_retry_after_win_across_checks():
    short = Policy("short", 1, 60)
    long = Policy("long", 1, 3600)
    await reserve([(short, "a"), (long, "a")])
    with pytest.raises(HTTPException) as exc:
        await reserve([(short, "a"), (long, "a")], message="Slow down for {n}s.")
    assert exc.value.headers["Retry-After"] == "3600"
    assert exc.value.detail["message"] == "Slow down for 3600s."


@pytest.mark.anyio
async def test_limit_resets_when_the_window_ends():
    for _ in range(3):
        await reserve([(POLICY, "a")])
    with pytest.raises(HTTPException):
        await reserve([(POLICY, "a")])
    fakes.advance(900)
    hits = await reserve([(POLICY, "a")])
    assert hits[0].count == 1


@pytest.mark.anyio
async def test_disabled_limiter_counts_nothing(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    assert await reserve([(POLICY, "a")]) == []
    assert fakes.count_for("unit") == 0


# ---- failure policy ---------------------------------------------------------------------


@pytest.mark.anyio
async def test_fail_closed_returns_503_not_429_when_counters_are_unavailable(caplog):
    fakes.set_failing(True)
    with caplog.at_level(logging.ERROR, logger="app.rate_limit"):
        with pytest.raises(HTTPException) as exc:
            await reserve([(POLICY, "a")])
    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "RATE_LIMITER_UNAVAILABLE"
    assert "Retry-After" not in (exc.value.headers or {})
    assert "Rate limiter unavailable" in caplog.text and "simulated" not in caplog.text


@pytest.mark.anyio
async def test_hit_wraps_store_errors():
    fakes.set_failing(True)
    with pytest.raises(RateLimiterUnavailable):
        await hit(POLICY, "a")


@pytest.mark.anyio
async def test_there_is_no_fail_open_option():
    import inspect

    assert "fail_closed" not in inspect.signature(reserve).parameters
    fakes.set_failing(True)
    with pytest.raises(HTTPException) as exc:
        await reserve([(POLICY, "a")])
    assert exc.value.status_code == 503


# ---- refund, clear, purge ---------------------------------------------------------------


@pytest.mark.anyio
async def test_refund_gives_back_only_the_selected_scopes_and_never_goes_below_zero():
    a, b = Policy("a", 5, 900), Policy("b", 5, 900)
    hits = await reserve([(a, "x"), (b, "x")])
    await refund(hits, {"a"})
    assert (fakes.count_for("a"), fakes.count_for("b")) == (0, 1)
    await refund(hits, {"a"})
    assert fakes.count_for("a") == 0


@pytest.mark.anyio
async def test_clear_removes_every_window_of_one_counter_only():
    await hit(POLICY, "a")
    fakes.advance(900)
    await hit(POLICY, "a")
    await hit(POLICY, "b")
    await clear(POLICY, "a")
    assert fakes.count_for("unit", hash_identifier("unit", "a")) == 0
    assert fakes.count_for("unit", hash_identifier("unit", "b")) == 1


@pytest.mark.anyio
async def test_refund_and_clear_never_raise_on_store_errors():
    hits = await reserve([(POLICY, "a")])
    fakes.set_failing(True)
    await refund(hits)
    await clear(POLICY, "a")


@pytest.mark.anyio
async def test_purge_removes_only_expired_buckets_in_batches():
    for ident in ("a", "b", "c"):
        await hit(POLICY, ident)
    assert await purge_expired() == 0  # nothing expired yet
    fakes.advance(900 + 61)  # past window end + 60s grace
    await hit(POLICY, "fresh")
    assert await purge_expired(batch=2) == 2
    assert await purge_expired(batch=2) == 1
    assert fakes.count_for("unit") == 1  # only "fresh" is left


@pytest.mark.anyio
async def test_a_failing_purge_never_affects_the_request(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_PURGE_PROBABILITY", 1.0)

    async def broken(*_a, **_k):
        raise RuntimeError("purge down")

    monkeypatch.setattr(rate_limiter, "_store_purge", broken)
    assert len(await reserve([(POLICY, "a")])) == 1


# ---- policies ---------------------------------------------------------------------------


def test_policies_come_from_settings_and_have_sane_defaults():
    expected = {
        "login_pair": (5, 900), "login_ip": (20, 900), "login_account": (30, 900),
        "signup_ip": (5, 3600), "refresh_ip": (120, 900), "invite_user": (20, 3600),
        "join_user": (10, 900), "join_code_user": (10, 3600), "invite_respond_user": (30, 900),
        "ai_burst_user": (20, 60), "ai_feedback_user": (60, 60),
    }
    for name, (limit, window) in expected.items():
        policy = get_policy(name)
        assert (policy.scope, policy.limit, policy.window_seconds) == (name, limit, window)


# ---- client address ---------------------------------------------------------------------


def test_no_trusted_header_means_the_address_is_unknown_and_a_warning_is_logged_once(caplog):
    request = make_request({"X-Forwarded-For": "198.51.100.7"})
    with caplog.at_level(logging.WARNING, logger="app.rate_limit"):
        assert get_client_ip(request) is None
        assert get_client_ip(request) is None
    assert caplog.text.count("TRUSTED_CLIENT_IP_HEADER is not set") == 1


def test_forwarded_for_and_the_socket_peer_are_never_trusted(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_CLIENT_IP_HEADER", "CF-Connecting-IP")
    spoofed = make_request({"X-Forwarded-For": "198.51.100.7", "X-Real-IP": "198.51.100.8"})
    assert get_client_ip(spoofed) is None  # header absent: unknown, not the peer or XFF


def test_trusted_header_is_used_and_normalised(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_CLIENT_IP_HEADER", "CF-Connecting-IP")
    assert get_client_ip(make_request({"CF-Connecting-IP": " 203.0.113.9 "})) == "203.0.113.9"
    assert get_client_ip(make_request({"CF-Connecting-IP": "2001:DB8:0:0:0:0:0:1"})) == "2001:db8::1"
    # The header wins over a spoofed X-Forwarded-For sent alongside it.
    both = make_request({"CF-Connecting-IP": "203.0.113.9", "X-Forwarded-For": "1.2.3.4"})
    assert get_client_ip(both) == "203.0.113.9"


@pytest.mark.parametrize("value", ["", "garbage", "1.2.3.4, 5.6.7.8", "999.1.1.1", "1.2.3.4:80"])
def test_invalid_or_multi_valued_trusted_header_is_treated_as_unknown(monkeypatch, value):
    monkeypatch.setattr(settings, "TRUSTED_CLIENT_IP_HEADER", "CF-Connecting-IP")
    assert get_client_ip(make_request({"CF-Connecting-IP": value})) is None


# ---- error envelope and OpenAPI ----------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status_code", "code", "retryable"),
    [
        (429, "RATE_LIMIT_EXCEEDED", True),   # T-39: carries Retry-After, safe to retry later
        (429, "AI_QUOTA_EXCEEDED", False),    # daily quota: retrying cannot help until midnight UTC
        (503, "RATE_LIMITER_UNAVAILABLE", True),
        (404, "NOT_FOUND", False),
        (401, "UNAUTHORIZED", False),
    ],
)
async def test_is_retryable_in_the_error_envelope(status_code, code, retryable):
    exc = HTTPException(status_code=status_code, detail={"code": code, "message": "m"}, headers={"Retry-After": "7"})
    response = await http_exception_handler(make_request(), exc)
    import json

    body = json.loads(response.body)
    assert body["code"] == code and body["isRetryable"] is retryable
    assert response.headers["retry-after"] == "7"  # headers survive the handler


def test_openapi_documents_429_503_and_retry_after_on_guarded_routes():
    paths = app.openapi()["paths"]
    guarded = [
        ("/api/v1/auth/login", "post"), ("/api/v1/auth/signup", "post"), ("/api/v1/auth/register", "post"),
        ("/api/v1/auth/refresh", "post"), ("/api/v1/groups/join", "post"),
        ("/api/v1/groups/{group_id}/join-code", "post"), ("/api/v1/groups/{group_id}/invitations", "post"),
        ("/api/v1/invitations/{invitation_id}/accept", "post"), ("/api/v1/invitations/{invitation_id}/decline", "post"),
        # The /ai/suggestions aliases are include_in_schema=False; they are still limited
        # (see tests/test_rate_limits_ai.py).
        ("/api/v1/ai/category-suggestion", "post"), ("/api/v1/ai/category-suggestion/feedback", "post"),
    ]
    for path, method in guarded:
        responses = paths[path][method]["responses"]
        assert "429" in responses and "503" in responses, path
        assert "Retry-After" in responses["429"]["headers"], path


# ---- migration chain ---------------------------------------------------------------------


def test_migration_012_extends_t36_011_and_there_is_a_single_alembic_head():
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend = Path(__file__).resolve().parent.parent
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["012_create_rate_limit_buckets"]
    revision = script.get_revision("012_create_rate_limit_buckets")
    assert revision.down_revision == "011_create_notifications"
    assert script.get_revision("011_create_notifications").down_revision == "010_create_settlements"


# ---- the limiter cannot be switched off by accident --------------------------------------


def test_rate_limiting_is_on_by_default():
    from app.core.config import Settings

    assert Settings(_env_file=None).RATE_LIMIT_ENABLED is True


@pytest.mark.parametrize("environment", ["production", "staging", "test", ""])
@pytest.mark.parametrize("flag", ["false", "0", "False", "no", "off"])
def test_disabling_rate_limits_is_rejected_outside_development(environment, flag):
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError, match="RATE_LIMIT_ENABLED"):
        Settings(
            _env_file=None,
            ENVIRONMENT=environment,
            JWT_SECRET_KEY="a-production-grade-secret-key-of-at-least-32-chars",
            RATE_LIMIT_ENABLED=flag,
        )


def test_disabling_rate_limits_is_allowed_only_in_development():
    from app.core.config import Settings

    assert Settings(_env_file=None, ENVIRONMENT="development", RATE_LIMIT_ENABLED="false").RATE_LIMIT_ENABLED is False
    prod = Settings(
        _env_file=None, ENVIRONMENT="production", RATE_LIMIT_ENABLED="true",
        JWT_SECRET_KEY="a-production-grade-secret-key-of-at-least-32-chars",
    )
    assert prod.RATE_LIMIT_ENABLED is True


def test_the_render_blueprint_does_not_set_the_switch_or_trust_forwarded_headers():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / "render.yaml").read_text(encoding="utf8")
    command = next(line for line in text.splitlines() if line.strip().startswith("startCommand:"))
    assert "--forwarded-allow-ips" not in command and "--proxy-headers" not in command
    assert "RATE_LIMIT_ENABLED" not in text
    assert "FORWARDED_ALLOW_IPS" not in text
