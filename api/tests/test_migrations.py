"""The migration chain must produce exactly the schema the models declare.

Without this, migrations and models drift and an upgraded install ends
up with a schema the code does not expect.
"""

import pathlib
import subprocess
import sys

from sqlalchemy import create_engine, inspect

API_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_migrations_produce_the_model_schema(tmp_path):
    db_path = tmp_path / "migrated.db"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API_ROOT, capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin",
             "APTUS_DATABASE_URL": f"sqlite:///{db_path}",
             "APTUS_ENV": "development"},
    )
    assert result.returncode == 0, result.stderr

    from aptus_api.db import Base
    from aptus_api import models  # noqa: F401

    migrated = set(inspect(create_engine(f"sqlite:///{db_path}")).get_table_names())
    declared = set(Base.metadata.tables)

    missing = declared - migrated
    assert not missing, f"Models declare tables no migration creates: {sorted(missing)}"
