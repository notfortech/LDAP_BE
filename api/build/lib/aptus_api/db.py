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

# Sentinel for maintaining the shared reference library. Only a
# deliberate global-maintenance path sets this; a tenant request always
# sets a numeric organisation id, so it can never reach a global row.
GLOBAL_TENANT = "global"

_TENANT_KEY = "aptus_tenant"


def is_postgres() -> bool:
    return _engine is not None and _engine.dialect.name == "postgresql"


def configure(database_url: str) -> None:
    global _engine, _SessionLocal
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    _engine = create_engine(database_url, connect_args=connect_args, future=True)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)

    if _engine.dialect.name != "postgresql":
        return

    @event.listens_for(_SessionLocal, "after_begin")
    def _apply_tenant(session, transaction, connection):
        """Re-apply the tenant at the start of every transaction.

        SET LOCAL rather than SET, and re-applied per transaction rather
        than once per request. A connection-level SET looks simpler and
        is wrong: the Session releases its connection on commit, so the
        setting is gone for everything after the first commit in a
        request -- which presents as a row that was just written being
        invisible to the very next read.

        Being transaction-scoped also means it cannot outlive the
        request and leak onto a pooled connection.
        """
        tenant = session.info.get(_TENANT_KEY)
        if tenant is None:
            return
        connection.exec_driver_sql(
            "SELECT set_config(%s, %s, true)", (TENANT_SETTING, str(tenant))
        )


def _remember_tenant(session, value) -> None:
    session.info[_TENANT_KEY] = value
    if not is_postgres():
        return
    # Apply now as well: a transaction may already be open, in which case
    # after_begin has been and gone for it.
    session.execute(
        text("SELECT set_config(:name, :value, true)"),
        {"name": TENANT_SETTING, "value": str(value)},
    )


def set_tenant(session, organisation_id: int) -> None:
    """Scope this session to one organisation for the rest of the request."""
    _remember_tenant(session, int(organisation_id))


def set_global_library_context(session) -> None:
    """Scope this session to the shared global reference library.

    Reserved for super-admin maintenance of the central crosswalk. The
    application-layer super-admin check remains the primary control;
    this makes a tenant-scoped session physically unable to write a
    global row even if that check were bypassed.
    """
    _remember_tenant(session, GLOBAL_TENANT)


def clear_tenant(session) -> None:
    session.info.pop(_TENANT_KEY, None)


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
        clear_tenant(session)
        session.close()
