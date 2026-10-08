"""Row-level security, proven against a real PostgreSQL.

These tests deliberately bypass the application. They connect to the
database directly as the runtime role and try to read and write across
tenants. That is the only way to show the isolation is a property of the
database rather than of the WHERE clauses the application remembers to
write.

Skipped when no PostgreSQL is configured. SQLite has no row-level
security, which is why production refuses to start on it.
"""

import os

import pytest
from sqlalchemy import create_engine, text

APP_URL = os.environ.get("APTUS_TEST_APP_DATABASE_URL")
ADMIN_URL = os.environ.get("APTUS_TEST_ADMIN_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (APP_URL and ADMIN_URL),
    reason="Set APTUS_TEST_APP_DATABASE_URL and APTUS_TEST_ADMIN_DATABASE_URL to run RLS tests",
)


@pytest.fixture(scope="module")
def admin_engine():
    return create_engine(ADMIN_URL)


@pytest.fixture(scope="module")
def app_engine():
    return create_engine(APP_URL)


@pytest.fixture(scope="module")
def tenants(admin_engine):
    """Two organisations, each with one candidate, seeded as the owner."""
    with admin_engine.begin() as c:
        c.execute(text("DELETE FROM candidates"))
        c.execute(text("DELETE FROM organisations WHERE slug IN ('rls-a','rls-b')"))
        a = c.execute(text(
            "INSERT INTO organisations (name,slug,contact_email,status,created_at) "
            "VALUES ('RLS A','rls-a','a@a.edu','ACTIVE',now()) RETURNING id"
        )).scalar_one()
        b = c.execute(text(
            "INSERT INTO organisations (name,slug,contact_email,status,created_at) "
            "VALUES ('RLS B','rls-b','b@b.edu','ACTIVE',now()) RETURNING id"
        )).scalar_one()
        for org, email, digest in ((a, "a@learner.edu", "rls-h-a"), (b, "b@learner.edu", "rls-h-b")):
            c.execute(text("SELECT set_config('app.current_organisation', :o, false)"),
                      {"o": str(org)})
            c.execute(text(
                "INSERT INTO candidates (organisation_id,email,access_token_hash,invited_at) "
                "VALUES (:o,:e,:h,now())"
            ), {"o": org, "e": email, "h": digest})
    return {"a": a, "b": b}


def as_tenant(engine, org_id, sql, params=None):
    with engine.connect() as c:
        if org_id is not None:
            c.execute(text("SELECT set_config('app.current_organisation', :o, false)"),
                      {"o": str(org_id)})
        return c.execute(text(sql), params or {}).fetchall()


def test_the_runtime_role_does_not_bypass_rls(app_engine):
    """If this fails, every other test in this file is meaningless: a
    superuser or BYPASSRLS role sees all rows regardless of policy."""
    with app_engine.connect() as c:
        row = c.execute(text(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )).one()
    assert row.rolsuper is False, "The runtime role is a superuser; RLS does not apply to it."
    assert row.rolbypassrls is False, "The runtime role has BYPASSRLS; RLS does not apply to it."


def test_each_tenant_sees_only_its_own_rows(app_engine, tenants):
    a = as_tenant(app_engine, tenants["a"], "SELECT email FROM candidates")
    b = as_tenant(app_engine, tenants["b"], "SELECT email FROM candidates")
    assert [r.email for r in a] == ["a@learner.edu"]
    assert [r.email for r in b] == ["b@learner.edu"]


def test_an_unfiltered_query_still_returns_only_one_tenant(app_engine, tenants):
    """The case RLS exists for: the application forgot its WHERE clause."""
    rows = as_tenant(app_engine, tenants["a"], "SELECT email FROM candidates WHERE true")
    assert [r.email for r in rows] == ["a@learner.edu"]


def test_naming_another_tenant_explicitly_returns_nothing(app_engine, tenants):
    rows = as_tenant(app_engine, tenants["a"],
                     "SELECT email FROM candidates WHERE organisation_id = :o",
                     {"o": tenants["b"]})
    assert rows == []


def test_no_tenant_set_means_no_rows(app_engine, tenants):
    """Default-deny. current_setting(..., true) is NULL when unset, the
    predicate is NULL, and nothing matches -- so a connection that forgot
    to set a tenant sees nothing rather than everything."""
    assert as_tenant(app_engine, None, "SELECT email FROM candidates") == []


def test_writing_into_another_tenant_is_refused(app_engine, tenants):
    with pytest.raises(Exception) as exc:
        with app_engine.begin() as c:
            c.execute(text("SELECT set_config('app.current_organisation', :o, false)"),
                      {"o": str(tenants["a"])})
            c.execute(text(
                "INSERT INTO candidates (organisation_id,email,access_token_hash,invited_at) "
                "VALUES (:o,'smuggled@a.edu','rls-h-x',now())"
            ), {"o": tenants["b"]})
    assert "row-level security" in str(exc.value).lower()


def test_updating_another_tenants_row_affects_nothing(app_engine, tenants):
    with app_engine.begin() as c:
        c.execute(text("SELECT set_config('app.current_organisation', :o, false)"),
                  {"o": str(tenants["a"])})
        result = c.execute(text("UPDATE candidates SET display_name = 'tampered'"))
        assert result.rowcount <= 1
    rows = as_tenant(app_engine, tenants["b"], "SELECT display_name FROM candidates")
    assert rows[0].display_name is None, "Another tenant's row was modified."


def test_deleting_another_tenants_row_affects_nothing(app_engine, tenants):
    with app_engine.begin() as c:
        c.execute(text("SELECT set_config('app.current_organisation', :o, false)"),
                  {"o": str(tenants["a"])})
        c.execute(text("DELETE FROM candidates WHERE organisation_id = :o"),
                  {"o": tenants["b"]})
    rows = as_tenant(app_engine, tenants["b"], "SELECT email FROM candidates")
    assert len(rows) == 1, "Another tenant's row was deleted."


def test_global_reference_entries_are_readable_by_every_tenant(app_engine, admin_engine, tenants):
    with admin_engine.begin() as c:
        # Global entries are reachable only through the global-maintenance
        # context: FORCE ROW LEVEL SECURITY applies to the owner too.
        c.execute(text("SELECT set_config('app.current_organisation','global',false)"))
        c.execute(text("DELETE FROM training_references WHERE unit_code = 'RLSGLOBAL'"))
        c.execute(text("""
            INSERT INTO training_references
              (lineage_id,version,is_current,organisation_id,construct_id,unit_code,
               unit_title,training_gov_url,verified,created_at)
            VALUES ('lin-rls',1,true,NULL,'SK_ETHICS','RLSGLOBAL','Global unit',
                    'https://training.gov.au/x',false,now())
        """))
    for key in ("a", "b"):
        rows = as_tenant(app_engine, tenants[key],
                         "SELECT unit_code FROM training_references WHERE unit_code='RLSGLOBAL'")
        assert len(rows) == 1, "A global reference entry must be visible to every tenant."


def test_a_tenant_cannot_write_a_global_reference_entry(app_engine, tenants):
    """Global entries are maintained centrally. The write policies omit
    the NULL case deliberately, so a tenant connection cannot create one."""
    with pytest.raises(Exception) as exc:
        with app_engine.begin() as c:
            c.execute(text("SELECT set_config('app.current_organisation', :o, false)"),
                      {"o": str(tenants["a"])})
            c.execute(text("""
                INSERT INTO training_references
                  (lineage_id,version,is_current,organisation_id,construct_id,unit_code,
                   unit_title,training_gov_url,verified,created_at)
                VALUES ('lin-sneak',1,true,NULL,'SK_ETHICS','SNEAKY','x',
                        'https://training.gov.au/y',false,now())
            """))
    assert "row-level security" in str(exc.value).lower()


def test_child_rows_cannot_be_given_a_mismatched_organisation(app_engine, admin_engine, tenants):
    """The composite foreign key that stops the denormalised
    organisation_id from drifting away from its parent's."""
    with admin_engine.begin() as c:
        c.execute(text("SELECT set_config('app.current_organisation', :o, false)"),
                  {"o": str(tenants["a"])})
        candidate_id = c.execute(text(
            "SELECT id FROM candidates WHERE organisation_id = :o"), {"o": tenants["a"]}
        ).scalar_one()

    with pytest.raises(Exception) as exc:
        with admin_engine.begin() as c:
            c.execute(text("SELECT set_config('app.current_organisation', :o, false)"),
                      {"o": str(tenants["b"])})
            c.execute(text(
                "INSERT INTO candidate_assignments (candidate_id,organisation_id,construct_id) "
                "VALUES (:c,:o,'SK_ETHICS')"
            ), {"c": candidate_id, "o": tenants["b"]})
    assert "foreign key" in str(exc.value).lower() or "row-level security" in str(exc.value).lower()


def test_global_maintenance_context_cannot_touch_tenant_rows(app_engine, tenants):
    """The sentinel is not a master key. It reaches global rows only."""
    with app_engine.connect() as c:
        c.execute(text("SELECT set_config('app.current_organisation','global',false)"))
        rows = c.execute(text("SELECT email FROM candidates")).fetchall()
    assert rows == [], "The global-maintenance context exposed tenant rows."


def test_tenant_context_cannot_write_a_global_row_even_as_owner(admin_engine, tenants):
    """Owner plus a numeric tenant must still be refused a global write."""
    with pytest.raises(Exception) as exc:
        with admin_engine.begin() as c:
            c.execute(text("SELECT set_config('app.current_organisation', :o, false)"),
                      {"o": str(tenants["a"])})
            c.execute(text("""
                INSERT INTO training_references
                  (lineage_id,version,is_current,organisation_id,construct_id,unit_code,
                   unit_title,training_gov_url,verified,created_at)
                VALUES ('lin-x',1,true,NULL,'SK_ETHICS','NOPE','x',
                        'https://training.gov.au/z',false,now())
            """))
    assert "row-level security" in str(exc.value).lower()
