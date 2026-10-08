"""Rate limiting, security headers and CORS."""

from aptus_api.ratelimit import RateLimiter


def test_limiter_allows_up_to_the_limit_then_blocks():
    limiter = RateLimiter({"signup": (3, 60)})
    assert [limiter.check("signup", "1.2.3.4", now=0)[0] for _ in range(3)] == [True] * 3
    allowed, retry_after = limiter.check("signup", "1.2.3.4", now=0)
    assert allowed is False and retry_after > 0


def test_limiter_window_slides():
    limiter = RateLimiter({"signup": (2, 60)})
    limiter.check("signup", "ip", now=0)
    limiter.check("signup", "ip", now=1)
    assert limiter.check("signup", "ip", now=2)[0] is False
    # Both hits have aged out by now=70.
    assert limiter.check("signup", "ip", now=70)[0] is True


def test_limiter_isolates_identities_and_buckets():
    limiter = RateLimiter({"signup": (1, 60), "signin": (1, 60)})
    assert limiter.check("signup", "a", now=0)[0] is True
    assert limiter.check("signup", "a", now=0)[0] is False
    assert limiter.check("signup", "b", now=0)[0] is True
    assert limiter.check("signin", "a", now=0)[0] is True


def test_unknown_bucket_is_not_limited():
    assert RateLimiter({}).check("whatever", "ip")[0] is True


def test_signup_is_rate_limited_over_http(client):
    limit = client.app.state.settings.rate_limits["signup"][0]
    codes = [
        client.post("/auth/signup", json={
            "email": f"user{n}@rto.edu.au", "password": "a-long-enough-password",
            "organisation_name": f"Org {n}",
        }).status_code
        for n in range(limit + 1)
    ]
    assert codes[:limit] == [202] * limit
    assert codes[-1] == 429


def test_security_headers_present(client):
    headers = client.get("/health").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]


def test_hsts_only_in_production(client):
    """Sending HSTS over plain HTTP in development would pin a developer's
    browser to HTTPS on localhost."""
    assert "Strict-Transport-Security" not in client.get("/health").headers


def test_cors_rejects_an_unlisted_origin(client):
    allowed = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    denied = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in denied.headers


def test_health_needs_no_database_but_ready_reports_it(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json()["status"] == "ready"


# --- Transaction-pooler compatibility -------------------------------------
#
# A free-tier Postgres almost always sits behind a transaction pooler.
# Getting this wrong does not fail at startup; it fails later with
# "prepared statement _pg3_0 already exists", which is an unpleasant way
# to discover it.

import pytest
from aptus_api.db import looks_like_transaction_pooler
from aptus_api.settings import load_settings


@pytest.mark.parametrize("url,pooled", [
    # Supabase transaction mode.
    ("postgresql+psycopg://u:p@aws-0-ap-southeast-2.pooler.supabase.com:6543/postgres", True),
    # Supabase session mode: prepared statements do work here, but the
    # host is a pooler and treating it as one is the safe default.
    ("postgresql+psycopg://u:p@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres", True),
    # Supabase direct connection is a real Postgres backend.
    ("postgresql+psycopg://u:p@db.abcdefgh.supabase.co:5432/postgres", False),
    ("postgresql+psycopg://u:p@mydb.postgres.database.azure.com:5432/aptus", False),
    ("postgresql+psycopg://u:p@localhost:5432/aptus", False),
    ("sqlite:///./x.db", False),
])
def test_pooler_detection(url, pooled):
    assert looks_like_transaction_pooler(url) is pooled


def test_malformed_url_does_not_raise():
    """Detection runs before the engine exists, so it must never be the
    thing that breaks startup."""
    assert looks_like_transaction_pooler("not a url at all") is False


def test_pooler_setting_is_tri_state():
    base = {"APTUS_ENV": "development"}
    assert load_settings(base).transaction_pooler is None, "unset must mean auto-detect"
    assert load_settings({**base, "APTUS_DB_TRANSACTION_POOLER": "true"}).transaction_pooler is True
    assert load_settings({**base, "APTUS_DB_TRANSACTION_POOLER": "false"}).transaction_pooler is False


def test_pooled_engine_disables_prepared_statements_and_client_pooling(monkeypatch):
    """The two settings that matter, asserted on what is actually passed
    to create_engine rather than on the detection alone."""
    from sqlalchemy.pool import NullPool

    from aptus_api import db as db_module

    captured = {}

    def fake_create_engine(url, **kwargs):
        captured.update(kwargs)
        class _Stub:
            class dialect: name = "postgresql"
        return _Stub()

    monkeypatch.setattr(db_module, "create_engine", fake_create_engine)
    monkeypatch.setattr(db_module, "sessionmaker", lambda **kw: object())
    monkeypatch.setattr(db_module, "_install_tenant_listener", lambda: None)

    db_module.configure(
        "postgresql+psycopg://u:p@aws-0-ap-southeast-2.pooler.supabase.com:6543/postgres"
    )
    assert captured["connect_args"]["prepare_threshold"] is None
    assert captured["poolclass"] is NullPool

    captured.clear()
    db_module.configure("postgresql+psycopg://u:p@mydb.postgres.database.azure.com:5432/aptus")
    assert "prepare_threshold" not in captured["connect_args"]
    assert "poolclass" not in captured
