"""Guard read-only 1.6 Alembic lineage evidence against disappearing SQLite sidecars."""

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "inspect-alembic-lineage.py"

SIDECAR_WARNINGS = {
    "-wal": "wal_sidecar_requires_consistent_snapshot",
    "-shm": "shared_memory_sidecar_requires_consistent_snapshot",
    "-journal": "rollback_journal_requires_consistent_snapshot",
}


@pytest.mark.parametrize("suffix", list(SIDECAR_WARNINGS))
@pytest.mark.parametrize(
    ("seen_before", "seen_after"),
    [(False, False), (True, False), (False, True), (True, True)],
)
def test_transient_sqlite_sidecars_fail_closed_without_mutating_science(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
    seen_before: bool,
    seen_after: bool,
) -> None:
    database = tmp_path / "science.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES ('0039')")
        for table in (
            "scientific_records",
            "environmental_cache_entries",
            "computed_metric_definitions",
            "computed_metric_results",
        ):
            connection.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY, note TEXT)")
        connection.execute(
            "INSERT INTO scientific_records VALUES ('coral-1', 'private biological evidence')"
        )
    before = database.read_bytes()

    spec = importlib.util.spec_from_file_location("lineage_sidecar_evidence_16", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    snapshots = []
    for present in (seen_before, seen_after):
        snapshots.append({key: present if key == suffix else False for key in SIDECAR_WARNINGS})
    observed_paths: list[Path] = []

    def sidecar_snapshot(path: Path) -> dict[str, bool]:
        observed_paths.append(path)
        return snapshots[len(observed_paths) - 1].copy()

    monkeypatch.setattr(module, "_sidecar_presence", sidecar_snapshot)
    report = module.inspect(database)

    assert observed_paths == [database.resolve(), database.resolve()]
    assert report["sqlite_sidecars_before"] == snapshots[0]
    assert report["sqlite_sidecars_after"] == snapshots[1]
    expected_warnings = [SIDECAR_WARNINGS[suffix]] if seen_before or seen_after else []
    assert report["warnings"] == expected_warnings
    assert report["upgrade_authorized"] is False
    assert report["sqlite_integrity_ok"] is True
    assert report["sqlite_full_integrity_ok"] is True
    assert report["inventory"]["scientific_records"]["rows"] == 1
    assert "private biological evidence" not in json.dumps(report)
    assert database.read_bytes() == before
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT note FROM scientific_records WHERE id='coral-1'"
        ).fetchone() == ("private biological evidence",)


@pytest.mark.parametrize(
    ("stat_before", "stat_after", "expected_match"),
    [
        ((1, 2, 3, 4, 5), (1, 2, 3, 4, 5), True),
        ((1, 2, 3, 4, 5), (1, 2, 4, 4, 5), False),
        ((1, 2, 3, 4, 5), (1, 9, 3, 4, 5), False),
        ((1, 2, 3, 4, 5), (1, 2, 3, 4, 9), False),
        ((1, 2, 3, 4, 5), None, False),
        (None, (1, 2, 3, 4, 5), False),
    ],
)
def test_main_database_identity_churn_fails_closed_without_exposing_science(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stat_before: tuple[int, int, int, int, int] | None,
    stat_after: tuple[int, int, int, int, int] | None,
    expected_match: bool,
) -> None:
    database = tmp_path / "science.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES ('0039')")
        for table in (
            "scientific_records",
            "environmental_cache_entries",
            "computed_metric_definitions",
            "computed_metric_results",
        ):
            connection.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY, note TEXT)")
        connection.execute(
            "INSERT INTO scientific_records VALUES ('coral-1', 'confidential field sample')"
        )
    before_bytes = database.read_bytes()

    spec = importlib.util.spec_from_file_location("lineage_main_file_evidence_16", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    observations = [stat_before, stat_after]
    probed_paths: list[Path] = []

    def fake_stat_signature(path: Path) -> tuple[int, int, int, int, int] | None:
        probed_paths.append(path)
        return observations[len(probed_paths) - 1]

    monkeypatch.setattr(module, "_database_stat_signature", fake_stat_signature)
    monkeypatch.setattr(
        module, "_sidecar_presence", lambda path: {suffix: False for suffix in SIDECAR_WARNINGS}
    )
    report = module.inspect(database)

    assert probed_paths == [database.resolve(), database.resolve()]
    assert report["sqlite_database_stat_observations_match"] is expected_match
    assert report["warnings"] == (
        [] if expected_match else ["database_file_changed_during_inspection"]
    )
    assert report["upgrade_authorized"] is False
    assert report["sqlite_integrity_ok"] is True
    assert report["sqlite_full_integrity_ok"] is True
    assert report["inventory"]["scientific_records"]["rows"] == 1
    assert "confidential field sample" not in json.dumps(report)
    assert database.read_bytes() == before_bytes
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT note FROM scientific_records WHERE id='coral-1'"
        ).fetchone() == ("confidential field sample",)
