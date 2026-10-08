"""Row-level security on organisation-scoped tables

Application-layer scoping stays; this adds a second, independent layer
so a single missed WHERE clause cannot leak another tenant's rows.

PostgreSQL only. SQLite has no row-level security, so on SQLite this
migration is a no-op and the application keeps its application-layer
scoping alone -- which is why production refuses to start on SQLite.

Revision ID: 0003_rls
Revises: c0af682919a7
"""
from alembic import op

revision = "0003_rls"
down_revision = "c0af682919a7"
branch_labels = None
depends_on = None

SETTING = "app.current_organisation"

# Tables whose every row belongs to exactly one organisation.
TENANT_TABLES = (
    "candidates",
    "candidate_assignments",
    "assessment_attempts",
    "attempt_construct_scores",
)

# Policies compare against this accessor rather than casting the
# parameter inline. A bare `current_setting(...)::int` raises on any
# non-numeric value -- including the 'global' sentinel below -- which
# turns a tenancy question into a 500 instead of a clean denial. The
# CASE guarantees the cast is only reached for digits; anything else,
# including unset, yields NULL and therefore matches no row.
#
# Default-deny: a connection that forgot to set a tenant sees nothing.
ACCESSOR = """
CREATE OR REPLACE FUNCTION app_current_organisation() RETURNS integer
LANGUAGE sql STABLE AS $fn$
  SELECT CASE
    WHEN current_setting('%s', true) ~ '^[0-9]+$'
    THEN current_setting('%s', true)::integer
    ELSE NULL
  END
$fn$
""" % (SETTING, SETTING)

TENANT_PREDICATE = "organisation_id = app_current_organisation()"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(ACCESSOR)

    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # FORCE applies the policies to the table owner as well. Without
        # it the owner bypasses them, and the application would silently
        # be unprotected whenever it happens to connect as the owner.
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING ({TENANT_PREDICATE})
            WITH CHECK ({TENANT_PREDICATE})
        """)

    # training_references is different: a row with a NULL organisation is
    # the shared global library, readable by every tenant.
    op.execute("ALTER TABLE training_references ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE training_references FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_read ON training_references
        FOR SELECT
        USING (
            organisation_id IS NULL
            OR {TENANT_PREDICATE}
        )
    """)
    # Writes are confined to the tenant's own rows. A global entry is
    # maintained centrally and must never be writable through a tenant
    # connection, so the write policies deliberately omit the NULL case.
    for action in ("INSERT", "UPDATE", "DELETE"):
        clause = "WITH CHECK" if action == "INSERT" else "USING"
        op.execute(f"""
            CREATE POLICY tenant_write_{action.lower()} ON training_references
            FOR {action}
            {clause} ({TENANT_PREDICATE})
        """)

    # Maintaining the global library needs its own path, because FORCE
    # ROW LEVEL SECURITY applies to the table owner too -- without this,
    # nothing can write a global entry at all.
    #
    # The sentinel is deliberate rather than a role name: a connection
    # must set app.current_organisation to the literal 'global' to touch
    # a global row. A request serving a tenant has that parameter set to
    # a number, so it can never match this policy however the
    # application misbehaves. Role names would hard-code one deployment's
    # naming into the schema.
    op.execute(f"""
        CREATE POLICY global_library ON training_references
        FOR ALL
        USING (
            organisation_id IS NULL
            AND current_setting('{SETTING}', true) = 'global'
        )
        WITH CHECK (
            organisation_id IS NULL
            AND current_setting('{SETTING}', true) = 'global'
        )
    """)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    for action in ("insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS tenant_write_{action} ON training_references")
    op.execute("DROP POLICY IF EXISTS global_library ON training_references")
    op.execute("DROP POLICY IF EXISTS tenant_read ON training_references")
    op.execute("ALTER TABLE training_references DISABLE ROW LEVEL SECURITY")

    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.execute("DROP FUNCTION IF EXISTS app_current_organisation()")
