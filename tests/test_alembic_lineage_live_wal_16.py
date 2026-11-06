"""Regression: migration preflight must not bless mutable SQLite WAL snapshots."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "inspect-alembic-lineage.py"


@pytest.mark.parametrize("strict", [False, True])
def test_live_wal_sidecar_requires_consistent_snapshot(tmp_path: Path, strict: bool) -> None:
    database = tmp_path / "research.sqlite"
    writer = sqlite3.connect(database)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        writer.execute("INSERT INTO alembic_version VALUES ('0037')")
        writer.execute("CREATE TABLE scientific_records (id INTEGER PRIMARY KEY, value TEXT)")
        writer.execute("INSERT INTO scientific_records VALUES (1, 'coral-sentinel')")
        writer.commit()
        writer.execute("INSERT INTO scientific_records VALUES (2, 'uncheckpointed')")
        writer.commit()
        assert Path(str(database) + "-wal").exists()
        before = database.read_bytes()
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(database), *(["--fail-on-warning"] if strict else [])],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == (2 if strict else 0), result.stderr
        report = json.loads(result.stdout)
        assert "wal_sidecar_requires_consistent_snapshot" in report["warnings"]
        assert report["upgrade_authorized"] is False
        assert database.read_bytes() == before
        assert writer.execute("SELECT value FROM scientific_records WHERE id = 1").fetchone() == (
            "coral-sentinel",
        )
    finally:
        writer.close()
