"""Configuration must fail closed. These tests exist because the
predecessor's auth became a no-op when a variable was absent."""

import pytest
from aptus_api.settings import ConfigurationError, load_settings

BASE = {
    "APTUS_ENV": "production",
    "APTUS_SECRET_KEY": "k" * 48,
    "APTUS_DATABASE_URL": "postgresql://localhost/aptus",
    "APTUS_ALLOWED_ORIGINS": "https://app.example.edu.au",
}


def test_production_config_loads():
    s = load_settings(BASE)
    assert s.is_production and len(s.allowed_origins) == 1


@pytest.mark.parametrize("key,value,expected", [
    ("APTUS_SECRET_KEY", "", "SECRET_KEY is required"),
    ("APTUS_SECRET_KEY", "short", "at least 32 characters"),
    ("APTUS_DATABASE_URL", "", "DATABASE_URL is required"),
    ("APTUS_DATABASE_URL", "sqlite:///x.db", "SQLite is not supported"),
    ("APTUS_ALLOWED_ORIGINS", "", "at least one origin"),
    ("APTUS_ALLOWED_ORIGINS", "*", "cannot be '*'"),
])
def test_production_rejects_unsafe_config(key, value, expected):
    with pytest.raises(ConfigurationError, match=expected):
        load_settings({**BASE, key: value})


def test_unknown_environment_is_rejected():
    with pytest.raises(ConfigurationError, match="must be 'development' or 'production'"):
        load_settings({**BASE, "APTUS_ENV": "staging"})


def test_development_defaults_are_permissive_but_ephemeral():
    """Development needs no setup, but its generated secret differs every
    load, so a development secret can never become a production one."""
    a = load_settings({"APTUS_ENV": "development"})
    b = load_settings({"APTUS_ENV": "development"})
    assert a.secret_key != b.secret_key
    assert a.database_url.startswith("sqlite")


def test_describe_never_reveals_the_secret():
    from aptus_api.settings import describe
    assert "k" * 48 not in describe(load_settings(BASE))


def test_production_refuses_to_boot_without_a_way_to_send_verification(tmp_path):
    """Verification that cannot be delivered is not verification. This
    surfaced as a 500 on every signup in a production smoke test; it
    belongs at startup."""
    from aptus_api.main import create_app
    from aptus_api.settings import ConfigurationError

    settings = load_settings({
        **BASE,
        "APTUS_DATABASE_URL": f"sqlite:///{tmp_path/'x.db'}",
        "APTUS_ENV": "development",
    })
    production_like = type(settings)(
        **{**settings.__dict__, "environment": "production"}
    )
    with pytest.raises(ConfigurationError, match="no email adapter"):
        create_app(settings=production_like)


def test_disabling_verification_removes_that_requirement(tmp_path):
    """With verification off, boot gets past the email check. It still
    fails on SQLite, but on the row-level-security check -- which is the
    correct next objection, and proves the email gate was cleared."""
    from aptus_api.main import create_app
    from aptus_api.rls import RLSPostureError
    from aptus_api.settings import ConfigurationError

    settings = load_settings({
        **BASE,
        "APTUS_DATABASE_URL": f"sqlite:///{tmp_path/'y.db'}",
        "APTUS_ENV": "development",
        "APTUS_REQUIRE_EMAIL_VERIFICATION": "false",
    })
    production_like = type(settings)(
        **{**settings.__dict__, "environment": "production"}
    )
    with pytest.raises((RLSPostureError, ConfigurationError)) as exc:
        create_app(settings=production_like)
    assert "email adapter" not in str(exc.value)
