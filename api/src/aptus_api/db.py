"""Database session management.

Schema is created by Alembic migrations, never by create_all at import.
The predecessor created tables as a side effect of importing the
application, which works exactly once and then offers no way to change
a schema on a running install.
"""

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal = None


# The PostgreSQL run-time parameter the row-level-security policies read.
# Unset means no tenant, and every policy denies -- the default is closed.
TENANT_SETTING = "app.current_organisation"


def is_postgres() -> bool:
    return _engine is not None and _engine.dialect.name == "postgresql"


def configure(database_url: str) -> None:
    global _engine, _SessionLocal
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    _engine = create_engine(database_url, connect_args=connect_args, future=True)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)

    if _engine.dialect.name == "postgresql":
        @event.listens_for(_engine, "checkout")
        def _reset_tenant_on_checkout(dbapi_conn, connection_record, connection_proxy):
            """Clear any tenant left on a pooled connection.

            The request path resets it too, but a connection must never
            arrive at a new request still carrying the previous one's
            tenant. Doing it at checkout makes that impossible regardless
            of how the previous request ended.
            """
            with dbapi_conn.cursor() as cur:
                cur.execute(f"RESET {TENANT_SETTING}")


def set_tenant(session, organisation_id: int) -> None:
    """Scope this connection to one organisation.

    Uses SET rather than SET LOCAL deliberately: services commit
    mid-request, and SET LOCAL would be discarded at the first commit,
    silently leaving later queries with no tenant and therefore no rows.

    set_config's second argument must be text, so the integer is cast on
    the way in and back out in the policy. It is bound as a parameter,
    never interpolated.
    """
    if not is_postgres():
        return
    session.execute(
        text("SELECT set_config(:name, :value, false)"),
        {"name": TENANT_SETTING, "value": str(int(organisation_id))},
    )


# Sentinel for maintaining the shared reference library. Only a
# deliberate global-maintenance path sets this; a tenant request always
# sets a numeric organisation id, so it can never reach a global row.
GLOBAL_TENANT = "global"


def set_global_library_context(session) -> None:
    """Scope this connection to the shared global reference library.

    Reserved for super-admin maintenance of the central crosswalk. The
    application-layer super-admin check remains the primary control;
    this makes a tenant-scoped connection physically unable to write a
    global row even if that check were bypassed.
    """
    if not is_postgres():
        return
    session.execute(
        text("SELECT set_config(:name, :value, false)"),
        {"name": TENANT_SETTING, "value": GLOBAL_TENANT},
    )


def clear_tenant(session) -> None:
    if not is_postgres():
        return
    session.execute(text(f"RESET {TENANT_SETTING}"))


def get_engine():
    if _engine is None:
        raise RuntimeError("Database not configured; call configure() first")
    return _engine


def get_session():
    """FastAPI dependency yielding a session that always closes."""
    if _SessionLocal is None:
        raise RuntimeError("Database not configured; call configure() first")
    session = _SessionLocal()
    try:
        yield session
    finally:
        # Belt and braces with the checkout listener above: whichever
        # runs first, the connection never carries a tenant onward.
        try:
            clear_tenant(session)
        except Exception:  # a failed/closed connection has nothing to reset
            pass
        session.close()
