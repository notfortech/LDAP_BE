"""Row-level security posture checks.

Enabling RLS is not the same as being protected by it. PostgreSQL lets
three things silently bypass every policy:

  * a superuser connection -- bypasses unconditionally;
  * a role with BYPASSRLS -- same;
  * the table owner, unless the table is set to FORCE ROW LEVEL SECURITY.

All three fail open and none of them produces a warning. A deployment
can have policies in place, pass a casual inspection, and isolate
nothing. This module exists so that state cannot reach production: the
application refuses to start in it.
"""

import logging

from sqlalchemy import text

logger = logging.getLogger("aptus.rls")

# Must match the tables the RLS migration protects.
PROTECTED_TABLES = (
    "candidates",
    "candidate_assignments",
    "assessment_attempts",
    "attempt_construct_scores",
    "training_references",
)


class RLSPostureError(RuntimeError):
    """The database is configured so row-level security does not apply."""


def inspect_posture(connection) -> dict:
    role = connection.execute(text("""
        SELECT current_user AS name,
               rolsuper     AS is_superuser,
               rolbypassrls AS bypasses_rls
        FROM pg_roles WHERE rolname = current_user
    """)).mappings().one()

    tables = connection.execute(text("""
        SELECT c.relname       AS table_name,
               c.relrowsecurity      AS enabled,
               c.relforcerowsecurity AS forced,
               pg_get_userbyid(c.relowner) AS owner,
               (SELECT count(*) FROM pg_policies p
                 WHERE p.tablename = c.relname AND p.schemaname = n.nspname) AS policy_count
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = current_schema() AND c.relname = ANY(:names)
    """), {"names": list(PROTECTED_TABLES)}).mappings().all()

    problems = []
    if role["is_superuser"]:
        problems.append(
            f"The application connects as {role['name']!r}, a superuser. "
            "Superusers bypass every row-level-security policy, so tenant "
            "isolation is not enforced at all."
        )
    if role["bypasses_rls"]:
        problems.append(
            f"Role {role['name']!r} has BYPASSRLS. Policies do not apply to it."
        )

    found = {row["table_name"] for row in tables}
    for missing in sorted(set(PROTECTED_TABLES) - found):
        problems.append(f"Table {missing!r} not found; its policies cannot be verified.")

    for row in tables:
        if not row["enabled"]:
            problems.append(f"Row-level security is not enabled on {row['table_name']!r}.")
        if not row["policy_count"]:
            problems.append(f"Table {row['table_name']!r} has RLS enabled but no policy.")
        if row["owner"] == role["name"] and not row["forced"]:
            problems.append(
                f"The application owns {row['table_name']!r} and the table is not set to "
                "FORCE ROW LEVEL SECURITY, so the owner bypasses its policies."
            )

    return {
        "role": dict(role),
        "tables": [dict(row) for row in tables],
        "problems": problems,
        "enforced": not problems,
    }


def verify(engine, *, production: bool) -> dict:
    """Check posture at startup. Fails the boot in production."""
    if engine.dialect.name != "postgresql":
        report = {
            "enforced": False,
            "problems": ["Not PostgreSQL; row-level security is unavailable."],
            "role": None, "tables": [],
        }
        if production:
            raise RLSPostureError(report["problems"][0])
        logger.warning("Row-level security unavailable on %s (development only)",
                       engine.dialect.name)
        return report

    with engine.connect() as connection:
        report = inspect_posture(connection)

    if report["enforced"]:
        logger.info("Row-level security enforced for role %r across %d tables",
                    report["role"]["name"], len(report["tables"]))
        return report

    message = "Row-level security is not enforced:\n  - " + "\n  - ".join(report["problems"])
    if production:
        raise RLSPostureError(message)
    logger.warning("%s", message)
    return report
