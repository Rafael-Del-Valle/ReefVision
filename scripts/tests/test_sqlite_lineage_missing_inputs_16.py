"""Missing SQLite inputs must fail safely before opening or creating databases."""

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "inspect_sqlite_lineage_16.py"


@pytest.mark.parametrize("missing_side", ["primary", "reference"])
def test_missing_database_is_usage_error_without_writes(
    tmp_path: Path, missing_side: str
) -> None:
    existing = tmp_path / "existing.sqlite"
    missing = tmp_path / "missing.sqlite"
    with sqlite3.connect(existing) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT)")
        connection.execute("INSERT INTO alembic_version VALUES ('0038')")
        connection.execute("CREATE TABLE observations (private_note TEXT)")
        connection.execute("INSERT INTO observations VALUES ('confidential')")
    before = existing.read_bytes()
    primary, reference = (
        (missing, existing) if missing_side == "primary" else (existing, missing)
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(primary), "--compare-to", str(reference),
         "--fail-on-integrity-error"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2
    assert "database must be an existing file" in result.stderr
    assert "Traceback" not in result.stderr
    assert "confidential" not in result.stderr + result.stdout
    assert result.stdout == ""
    assert not missing.exists()
    assert existing.read_bytes() == before
