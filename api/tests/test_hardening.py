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
