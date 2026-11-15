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
            assert shm.stat().st_size > 0
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
                count = snapshot.execute("SELECT COUNT(*) FROM biological_sentinel").fetchone()
                assert count == (2,)
            assert report["upgrade_authorized"] is False
            assert database.read_bytes() == before_database
            assert wal.read_bytes() == before_wal
            # SQLite may legitimately update its shared-memory reader locks.
            assert shm.exists() and shm.stat().st_size > 0
            assert writer.execute(
                "SELECT note FROM biological_sentinel ORDER BY id"
            ).fetchall() == [("preserve",), ("uncheckpointed",)]
        finally:
            reader.close()
    finally:
        writer.close()


def test_concurrent_wal_commit_cannot_mix_scientific_revision_and_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A single read snapshot must cover integrity, stamp, and table inventory."""
    import runpy

    database = tmp_path / "concurrent-lineage.sqlite"
    writer = sqlite3.connect(database)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)")
        writer.execute("INSERT INTO alembic_version VALUES ('0039')")
        for name in (
            "scientific_records",
            "environmental_cache_entries",
            "computed_metric_definitions",
            "computed_metric_results",
        ):
            writer.execute(f'CREATE TABLE "{name}" (id INTEGER PRIMARY KEY)')
        writer.execute("CREATE TABLE biological_sentinel (note TEXT)")
        writer.execute("INSERT INTO biological_sentinel VALUES ('preserve')")
        writer.commit()

        original_connect = sqlite3.connect
        committed_during_scan = False

        class InjectingConnection:
            def __init__(self, connection: sqlite3.Connection) -> None:
                self.connection = connection

            def __enter__(self) -> "InjectingConnection":
                self.connection.__enter__()
                return self

            def __exit__(self, *args: object) -> bool | None:
                try:
                    return self.connection.__exit__(*args)
                finally:
                    self.connection.close()

            def execute(self, sql: str, *args: object) -> sqlite3.Cursor:
                nonlocal committed_during_scan
                cursor = self.connection.execute(sql, *args)
                if sql == "PRAGMA quick_check(1)" and not committed_during_scan:
                    # The writer commits between the first SQLite probe and
                    # subsequent schema/stamp reads. WAL permits this while a
                    # reader pins the earlier committed scientific state.
                    writer.execute("UPDATE alembic_version SET version_num='0042'")
                    for name in (
                        "environmental_event_definitions",
                        "environmental_analysis_definitions",
                        "environmental_analysis_results",
                    ):
                        writer.execute(f'CREATE TABLE "{name}" (id INTEGER PRIMARY KEY)')
                    writer.commit()
                    committed_during_scan = True
                return cursor

        def intercept_connect(
            *args: object, **kwargs: object
        ) -> sqlite3.Connection | InjectingConnection:
            connection = original_connect(*args, **kwargs)
            if kwargs.get("uri"):
                return InjectingConnection(connection)
            return connection

        inspector = runpy.run_path(str(SCRIPT))["inspect"]
        with monkeypatch.context() as patch:
            patch.setattr(sqlite3, "connect", intercept_connect)
            before_commit_view = inspector(database)

        assert committed_during_scan
        assert before_commit_view["revision_rows"] == ["0039"]
        assert before_commit_view["lineage_hint"] == "scientific"
        assert not before_commit_view["inventory"]["environmental_event_definitions"]["present"]
        assert not before_commit_view["inventory"]["environmental_analysis_results"]["present"]
        assert before_commit_view["upgrade_authorized"] is False

        after_commit_view = inspector(database)
        assert after_commit_view["revision_rows"] == ["0042"]
        assert after_commit_view["inventory"]["environmental_event_definitions"]["present"]
        assert after_commit_view["inventory"]["environmental_analysis_results"]["present"]
        assert writer.execute("SELECT note FROM biological_sentinel").fetchone() == ("preserve",)
    finally:
        writer.close()
