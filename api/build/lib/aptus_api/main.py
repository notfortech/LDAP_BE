"""Application assembly.

Configuration is validated before anything else is constructed, so a
misconfigured production deployment fails at startup rather than
serving requests with security disabled.
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .emails import LoggingEmailAdapter, UnconfiguredEmailAdapter
from .engine_bridge import describe_config_source, get_engine_config, get_item_bank
from .middleware import SecurityHeadersMiddleware
from .ratelimit import RateLimiter
from .rls import verify as verify_rls
from .routers import assessments, auth, orgs
from .settings import ConfigurationError, Settings, describe, load_settings

logger = logging.getLogger("aptus.api")


def create_app(settings: Settings | None = None, email_adapter=None) -> FastAPI:
    settings = settings or load_settings()

    # Configuration checks first. They are cheap, they need no database,
    # and a configuration error should be reportable even when the
    # database is unreachable.
    email = email_adapter or (
        UnconfiguredEmailAdapter() if settings.is_production else LoggingEmailAdapter()
    )
    # Verification that cannot be delivered is not verification. This
    # first appeared as a 500 on every signup in a production smoke
    # test; it belongs at startup.
    if (settings.is_production
            and settings.require_email_verification
            and isinstance(email, UnconfiguredEmailAdapter)):
        raise ConfigurationError(
            "Email verification is required but no email adapter is configured. "
            "Either supply an adapter, or set APTUS_REQUIRE_EMAIL_VERIFICATION=false "
            "for a closed pilot where signup is not publicly reachable."
        )

    db.configure(settings.database_url, transaction_pooler=settings.transaction_pooler)

    app = FastAPI(
        title="Aptus API",
        version="0.1.0",
        # Interactive docs enumerate every endpoint and schema. Useful in
        # development, an unnecessary disclosure in production.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.state.settings = settings

    # Load the engine configuration and item bank now. Both are read-only
    # and cached for the process lifetime, so the only thing deferring
    # this would buy is discovering a missing configuration during a
    # candidate's assessment instead of at boot.
    engine_config = get_engine_config()
    get_item_bank()
    logger.info("Engine configuration %s (%s) from %s",
                engine_config.version, engine_config.short_digest,
                describe_config_source())
    app.state.engine_config = engine_config
    # Enabling policies is not the same as being protected by them: a
    # superuser or BYPASSRLS connection silently ignores every one. In
    # production that is a boot failure, not a warning.
    app.state.rls = verify_rls(db.get_engine(), production=settings.is_production)
    app.state.limiter = RateLimiter(settings.rate_limits)
    app.state.email = email

    app.add_middleware(SecurityHeadersMiddleware, production=settings.is_production)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=True,
        # Enumerated, not wildcarded. A wildcard with credentials enabled
        # is the combination that turns a CORS policy into decoration.
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )

    app.include_router(auth.router)
    app.include_router(orgs.router)
    app.include_router(assessments.router)

    @app.get("/health", tags=["ops"])
    def health():
        """Liveness only — no dependency checks, so it stays answerable
        when the database is down and can distinguish 'process up' from
        'service ready'."""
        return {"status": "ok"}

    @app.get("/version", tags=["ops"])
    def version():
        """What this process is actually running. The engine digest is
        the number that matters: it identifies the exact scoring
        configuration behind every result this deployment produces."""
        return {
            "api": app.version,
            "engine_config_version": engine_config.version,
            "engine_config_digest": engine_config.digest,
        }

    @app.get("/rls", tags=["ops"])
    def rls_status():
        """Whether tenant isolation is actually enforced by the database.

        Deliberately exposed: an institutional reviewer asking "how do
        you know?" deserves an answer they can check themselves rather
        than a claim in a document.
        """
        report = app.state.rls
        return {
            "enforced": report["enforced"],
            "role": (report["role"] or {}).get("name"),
            "tables": [
                {"table": t["table_name"], "enabled": t["enabled"], "forced": t["forced"],
                 "policies": t["policy_count"]}
                for t in report["tables"]
            ],
            "problems": report["problems"],
        }

    @app.get("/ready", tags=["ops"])
    def ready():
        from sqlalchemy import text
        try:
            with db.get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:
            logger.exception("Readiness check failed")
            return {"status": "degraded", "database": "unreachable"}
        return {"status": "ready", "database": "ok"}

    logger.info("Aptus API starting: %s", describe(settings))
    return app
