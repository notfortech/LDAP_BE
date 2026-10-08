"""Database session management.

Schema is created by Alembic migrations, never by create_all at import.
The predecessor created tables as a side effect of importing the
application, which works exactly once and then offers no way to change
a schema on a running install.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal = None


def configure(database_url: str) -> None:
    global _engine, _SessionLocal
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    _engine = create_engine(database_url, connect_args=connect_args, future=True)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)


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
        session.close()
