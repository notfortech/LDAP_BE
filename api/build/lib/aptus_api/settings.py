"""Typed configuration, validated once at startup.

The predecessor backend degraded to a no-op authenticator when its
identity environment variables were absent, and separately accepted an
organisation id from the request body as a development convenience.
Either alone is survivable. Together, one missing variable on a public
deployment let any caller read any institution's data by naming it.

This module exists so that cannot happen: in production, missing or
unsafe configuration raises at import, before the application serves a
single request. There is no partial state where security is configured
but optional.
"""

import os
import secrets
from dataclasses import dataclass, field
from typing import Literal

Environment = Literal["development", "production"]


class ConfigurationError(RuntimeError):
    """Configuration is missing or unsafe. Raised at startup only."""


def _as_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(raw: str | None, default: int) -> int:
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"Expected an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    environment: Environment
    secret_key: str
    database_url: str
    allowed_origins: tuple[str, ...]

    # None means "work it out from the database URL". Set explicitly
    # when the host does not look like a pooler but behaves as one, or
    # the reverse.
    transaction_pooler: bool | None = None

    require_email_verification: bool = True
    session_ttl_hours: int = 12
    verification_ttl_hours: int = 48

    # Free tier. An organisation with no subscription row gets this many
    # candidate seats, indefinitely.
    free_tier_seat_cap: int = 2

    # Whether a free-tier organisation may fork reference-library entries.
    # Forking is an organisation-scoped write and costs nothing to serve,
    # so it is open by default; flip this if it should become a paid
    # feature. Either way a locked-out organisation can never write.
    free_tier_may_fork_references: bool = True

    rate_limits: dict = field(default_factory=dict)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


# Per-endpoint-class limits: (max requests, window seconds). Deliberately
# in-process — an external store would break the dependency-free
# single-node appliance profile. Multi-node deployments need a shared
# store, and that is a known limitation recorded here rather than solved
# prematurely.
_DEFAULT_RATE_LIMITS = {
    "signup": (5, 3600),
    "signin": (10, 900),
    "verify": (10, 3600),
    "invite": (60, 3600),
    "public": (120, 60),
}


def load_settings(env: dict | None = None) -> Settings:
    env = os.environ if env is None else env

    environment = (env.get("APTUS_ENV") or "development").strip().lower()
    if environment not in ("development", "production"):
        raise ConfigurationError(
            f"APTUS_ENV must be 'development' or 'production', got {environment!r}"
        )
    production = environment == "production"

    secret_key = (env.get("APTUS_SECRET_KEY") or "").strip()
    if not secret_key:
        if production:
            raise ConfigurationError(
                "APTUS_SECRET_KEY is required in production. Generate one with: "
                "python -c 'import secrets; print(secrets.token_urlsafe(48))'"
            )
        # Ephemeral key for local development. Regenerated every start, so
        # a development secret can never silently become a production one.
        secret_key = secrets.token_urlsafe(48)
    elif production and len(secret_key) < 32:
        raise ConfigurationError("APTUS_SECRET_KEY must be at least 32 characters in production")

    database_url = (env.get("APTUS_DATABASE_URL") or "").strip()
    if not database_url:
        if production:
            raise ConfigurationError("APTUS_DATABASE_URL is required in production")
        database_url = "sqlite:///./aptus-dev.db"
    elif production and database_url.startswith("sqlite"):
        raise ConfigurationError(
            "SQLite is not supported in production: row-level tenant isolation "
            "requires PostgreSQL"
        )

    raw_origins = (env.get("APTUS_ALLOWED_ORIGINS") or "").strip()
    origins = tuple(o.strip() for o in raw_origins.split(",") if o.strip())
    if production:
        if not origins:
            raise ConfigurationError(
                "APTUS_ALLOWED_ORIGINS must list at least one origin in production"
            )
        if "*" in origins:
            raise ConfigurationError("APTUS_ALLOWED_ORIGINS cannot be '*' in production")
    elif not origins:
        origins = ("http://localhost:5173",)

    return Settings(
        environment=environment,
        secret_key=secret_key,
        database_url=database_url,
        allowed_origins=origins,
        transaction_pooler=(
            None if not (env.get("APTUS_DB_TRANSACTION_POOLER") or "").strip()
            else _as_bool(env.get("APTUS_DB_TRANSACTION_POOLER"), False)
        ),
        require_email_verification=_as_bool(
            env.get("APTUS_REQUIRE_EMAIL_VERIFICATION"), True
        ),
        session_ttl_hours=_as_int(env.get("APTUS_SESSION_TTL_HOURS"), 12),
        verification_ttl_hours=_as_int(env.get("APTUS_VERIFICATION_TTL_HOURS"), 48),
        free_tier_seat_cap=_as_int(env.get("APTUS_FREE_TIER_SEAT_CAP"), 2),
        free_tier_may_fork_references=_as_bool(
            env.get("APTUS_FREE_TIER_MAY_FORK_REFERENCES"), True
        ),
        rate_limits=dict(_DEFAULT_RATE_LIMITS),
    )


def describe(settings: Settings) -> str:
    """Startup summary. Reports presence, never a secret's value."""
    return (
        f"environment={settings.environment} "
        f"database={settings.database_url.split('://', 1)[0]} "
        f"origins={len(settings.allowed_origins)} "
        f"secret_key={'set' if settings.secret_key else 'MISSING'} "
        f"email_verification={'on' if settings.require_email_verification else 'OFF'}"
    )
