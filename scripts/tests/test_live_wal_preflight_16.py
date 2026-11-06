"""Real WAL snapshot safety regression for read-only migration preflight."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "inspect-alembic-lineage.py"


@pytest.mark.parametrize("strict", [False, True])
def test_live_wal_is_reported_and_preserved(tmp_path: Path, strict: bool) -> None:
    database = tmp_path / "live-research.sqlite"
    writer = sqlite3.connect(database)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        writer.execute("INSERT INTO alembic_version VALUES ('0037')")
        for name in (
            "scientific_records",
            "environmental_cache_entries",
            "computed_metric_definitions",
            "computed_metric_results",
        ):
            writer.execute(f"CREATE TABLE {name} (id INTEGER PRIMARY KEY)")
        writer.execute("CREATE TABLE biological_sentinel (id INTEGER PRIMARY KEY, note TEXT)")
        writer.execute("INSERT INTO biological_sentinel VALUES (1, 'preserve')")
        writer.commit()
        # Keep an active read transaction so checkpointing cannot discard the WAL.
        reader = sqlite3.connect(database)
        try:
            reader.execute("BEGIN")
            assert reader.execute("SELECT note FROM biological_sentinel").fetchone() == (
                "preserve",
            )
            writer.execute("INSERT INTO biological_sentinel VALUES (2, 'uncheckpointed')")
            writer.commit()
            wal = Path(str(database) + "-wal")
            assert wal.exists() and wal.stat().st_size > 0
            before_database = database.read_bytes()
            before_wal = wal.read_bytes()
            shm = Path(str(database) + "-shm")
            assert shm.exists()
            before_shm = shm.read_bytes()
            command = [sys.executable, str(SCRIPT)]
            if strict:
                command.append("--fail-on-warning")
            result = subprocess.run(
                [*command, str(database)], capture_output=True, text=True, check=False
            )
            assert result.returncode == (2 if strict else 0), result.stderr
            report = json.loads(result.stdout)
            assert "wal_sidecar_requires_consistent_snapshot" in report["warnings"]
            assert "shared_memory_sidecar_requires_consistent_snapshot" in report["warnings"]
            # The inspector must see committed records still resident in the WAL,
            # not merely preserve the files while reading an older main DB image.
            with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as snapshot:
                assert snapshot.execute("SELECT COUNT(*) FROM biological_sentinel").fetchone() == (2,)
            assert report["upgrade_authorized"] is False
            assert database.read_bytes() == before_database
            assert wal.read_bytes() == before_wal
            assert shm.read_bytes() == before_shm
            assert writer.execute(
                "SELECT note FROM biological_sentinel ORDER BY id"
            ).fetchall() == [("preserve",), ("uncheckpointed",)]
        finally:
            reader.close()
    finally:
        writer.close()
