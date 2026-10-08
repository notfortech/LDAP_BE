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
from .middleware import SecurityHeadersMiddleware
from .ratelimit import RateLimiter
from .routers import assessments, auth, orgs
from .settings import Settings, describe, load_settings

logger = logging.getLogger("aptus.api")


def create_app(settings: Settings | None = None, email_adapter=None) -> FastAPI:
    settings = settings or load_settings()
    db.configure(settings.database_url)

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
    app.state.limiter = RateLimiter(settings.rate_limits)
    app.state.email = email_adapter or (
        UnconfiguredEmailAdapter() if settings.is_production else LoggingEmailAdapter()
    )

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
