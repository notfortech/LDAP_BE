import pathlib
import sys

import pytest
from fastapi.testclient import TestClient

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
ENGINE_SRC = pathlib.Path(__file__).resolve().parents[2] / "engine" / "src"
sys.path.insert(0, str(SRC))
if ENGINE_SRC.exists():
    sys.path.insert(0, str(ENGINE_SRC))

from aptus_api import db as db_module  # noqa: E402
from aptus_api.emails import LoggingEmailAdapter  # noqa: E402
from aptus_api.main import create_app  # noqa: E402
from aptus_api.settings import load_settings  # noqa: E402


@pytest.fixture
def settings(tmp_path):
    return load_settings({
        "APTUS_ENV": "development",
        "APTUS_SECRET_KEY": "x" * 48,
        "APTUS_DATABASE_URL": f"sqlite:///{tmp_path/'test.db'}",
        "APTUS_ALLOWED_ORIGINS": "http://localhost:5173",
    })


@pytest.fixture
def email():
    return LoggingEmailAdapter()


@pytest.fixture
def client(settings, email):
    app = create_app(settings=settings, email_adapter=email)
    # Tables come from the model metadata here rather than Alembic: the
    # migration chain is verified separately in test_migrations.py, and
    # running it per-test would make the suite slow for no extra signal.
    db_module.Base.metadata.create_all(db_module.get_engine())
    with TestClient(app) as c:
        yield c


def register(client, email_adapter, *, email, org, password="a-long-enough-password"):
    """Sign up, verify, sign in. Returns (auth_header, organisation_id)."""
    r = client.post("/auth/signup", json={
        "email": email, "password": password, "organisation_name": org,
    })
    assert r.status_code == 202, r.text

    token = next(t for addr, t in email_adapter.sent if addr == email)
    assert client.post("/auth/verify", json={"token": token}).status_code == 200

    r = client.post("/auth/signin", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['token']}"}

    me = client.get("/auth/me", headers=headers).json()
    return headers, me["organisations"][0]["id"]
