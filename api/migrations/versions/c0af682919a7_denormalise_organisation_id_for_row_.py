"""Denormalise organisation_id onto assignment and score tables

Row-level security policies should be a predicate on an indexed column
of the row being filtered. A policy that reaches through a subquery to
the parent is slower and easy to get subtly wrong.

The copy cannot drift: each child carries a composite foreign key to
(id, organisation_id) on its parent, so a row whose organisation does
not match its parent's cannot be inserted at all.

Written by hand. Autogenerate emitted drop_constraint(None) for the
unnamed single-column foreign keys it was replacing, which does not
execute.

Revision ID: c0af682919a7
Revises: ccfccc3f9fc9
"""
import sqlalchemy as sa
from alembic import op

revision = "c0af682919a7"
down_revision = "ccfccc3f9fc9"
branch_labels = None
depends_on = None

# (child, parent, child_fk_column)
LINKS = (
    ("candidate_assignments", "candidates", "candidate_id"),
    ("attempt_construct_scores", "assessment_attempts", "attempt_id"),
)


def _fk_names(bind, table, column):
    """Existing foreign keys on `table` that constrain exactly `column`."""
    return [
        fk["name"]
        for fk in sa.inspect(bind).get_foreign_keys(table)
        if fk.get("name") and fk["constrained_columns"] == [column]
    ]


def upgrade() -> None:
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"

    # Composite unique constraints on the parents: the targets the child
    # foreign keys below need.
    with op.batch_alter_table("candidates") as batch:
        batch.create_unique_constraint("uq_candidate_id_org", ["id", "organisation_id"])
    with op.batch_alter_table("assessment_attempts") as batch:
        batch.create_unique_constraint("uq_attempt_id_org", ["id", "organisation_id"])

    for child, parent, fk_column in LINKS:
        # Added nullable, backfilled, then tightened -- so the migration
        # is safe against a table that already holds rows.
        op.add_column(child, sa.Column("organisation_id", sa.Integer(), nullable=True))
        op.execute(
            f"UPDATE {child} SET organisation_id = ("
            f"  SELECT p.organisation_id FROM {parent} p WHERE p.id = {child}.{fk_column}"
            f")"
        )

        if postgres:
            op.alter_column(child, "organisation_id", nullable=False)
            op.create_index(f"ix_{child}_organisation_id", child, ["organisation_id"])
            for name in _fk_names(bind, child, fk_column):
                op.drop_constraint(name, child, type_="foreignkey")
            op.create_foreign_key(
                f"fk_{'assignment_candidate' if child.startswith('candidate') else 'score_attempt'}_org",
                child, parent, [fk_column, "organisation_id"], ["id", "organisation_id"],
                ondelete="CASCADE",
            )
        else:
            # SQLite rewrites the table for any of this. copy_from gives
            # batch mode the shape to rebuild from, which is how the old
            # unnamed foreign key is dropped without naming it.
            meta = sa.MetaData()
            old = sa.Table(child, meta, autoload_with=bind)
            old.constraints = {
                c for c in old.constraints
                if not (isinstance(c, sa.ForeignKeyConstraint)
                        and [e.parent.name for e in c.elements] == [fk_column])
            }
            old.foreign_keys = set()
            with op.batch_alter_table(child, copy_from=old) as batch:
                batch.alter_column("organisation_id", nullable=False,
                                   existing_type=sa.Integer())
                batch.create_index(f"ix_{child}_organisation_id", ["organisation_id"])
                batch.create_foreign_key(
                    f"fk_{'assignment_candidate' if child.startswith('candidate') else 'score_attempt'}_org",
                    parent, [fk_column, "organisation_id"], ["id", "organisation_id"],
                    ondelete="CASCADE",
                )


def downgrade() -> None:
    bind = op.get_bind()
    for child, parent, fk_column in LINKS:
        name = f"fk_{'assignment_candidate' if child.startswith('candidate') else 'score_attempt'}_org"
        with op.batch_alter_table(child) as batch:
            batch.drop_constraint(name, type_="foreignkey")
            batch.drop_index(f"ix_{child}_organisation_id")
            batch.drop_column("organisation_id")
        with op.batch_alter_table(child) as batch:
            batch.create_foreign_key(
                f"fk_{child}_{fk_column}", parent, [fk_column], ["id"], ondelete="CASCADE"
            )
    with op.batch_alter_table("assessment_attempts") as batch:
        batch.drop_constraint("uq_attempt_id_org", type_="unique")
    with op.batch_alter_table("candidates") as batch:
        batch.drop_constraint("uq_candidate_id_org", type_="unique")
