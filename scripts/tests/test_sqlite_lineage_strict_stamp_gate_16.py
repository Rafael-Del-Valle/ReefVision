"""Strict Alembic stamp acceptance must not silently pass missing or invalid metadata."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "inspect_sqlite_lineage_16.py"


@pytest.mark.parametrize(
    ("schema", "revision", "expected_exit"),
    [
        (
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)",
            "0037",
            0,
        ),
        (None, None, 2),
        ("CREATE TABLE alembic_version (version_num TEXT)", "0037", 2),
        ("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)", None, 2),
        ("CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)", " 0037 ", 2),
    ],
)
def test_strict_stamp_gate_is_read_only_and_fail_closed(
    tmp_path: Path, schema: str | None, revision: str | None, expected_exit: int
) -> None:
    database = tmp_path / "research.sqlite"
    with sqlite3.connect(database) as connection:
        if schema is not None:
            connection.execute(schema)
            if revision is not None:
                connection.execute(
                    "INSERT INTO alembic_version(version_num) VALUES (?)", (revision,)
                )
        connection.execute("CREATE TABLE biological_sentinel (note TEXT)")
        connection.execute(
            "INSERT INTO biological_sentinel VALUES ('private biological observation')"
        )
    before = database.read_bytes()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(database), "--fail-on-noncanonical-stamp"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected_exit, result.stderr
    report = json.loads(result.stdout)
    assert report["classification"] == "requires_researcher_review"
    assert report["read_only"] is True
    assert "private biological observation" not in result.stdout
    assert database.read_bytes() == before


@pytest.mark.parametrize("event", ["INSERT", "UPDATE", "DELETE"])
@pytest.mark.parametrize(
    "flag",
    ["--fail-on-noncanonical-stamp", "--fail-on-integrity-error", "--fail-on-lineage-collision"],
)
def test_stamp_trigger_rejected_even_with_matching_schema(
    tmp_path: Path, event: str, flag: str
) -> None:
    databases = [tmp_path / "study.sqlite", tmp_path / "reference.sqlite"]
    for database in databases:
        with sqlite3.connect(database) as connection:
            connection.execute(
                "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
            connection.execute("INSERT INTO alembic_version VALUES ('0038')")
            connection.execute("CREATE TABLE observations (note TEXT)")
            connection.execute("INSERT INTO observations VALUES ('original coral')")
            connection.execute(
                f"CREATE TRIGGER unexpected_stamp_write AFTER {event} ON ALEMBIC_VERSION "
                "BEGIN UPDATE observations SET note = 'private trigger body'; END"
            )
    before = [database.read_bytes() for database in databases]
    command = [
        sys.executable, str(SCRIPT), str(databases[0]),
        "--compare-to", str(databases[1]),
    ]
    result = subprocess.run(
        command + [flag], capture_output=True, text=True, check=False
    )
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["schema_comparison"]["matches"] is True
    assert report["schema_comparison"]["revision_markers_match"] is False
    assert report["alembic_stamp_constraint_error"] == (
        "alembic_version_triggers_require_review"
    )
    assert report["classification"] == "requires_researcher_review"
    assert "private trigger body" not in result.stdout + result.stderr
    assert [database.read_bytes() for database in databases] == before


def test_unrelated_trigger_does_not_invalidate_stamp_contract(tmp_path: Path) -> None:
    database = tmp_path / "study.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
        connection.execute("INSERT INTO alembic_version VALUES ('0038')")
        connection.execute("CREATE TABLE observations (note TEXT)")
        connection.execute(
            "CREATE TRIGGER unrelated AFTER INSERT ON observations BEGIN SELECT 1; END"
        )
    before = database.read_bytes()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(database), "--fail-on-noncanonical-stamp"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["alembic_stamp_constraint_error"] is None
    assert database.read_bytes() == before

@pytest.mark.parametrize("relationship", ["update", "delete", "outgoing"])
@pytest.mark.parametrize(
    "flag",
    [
        "--fail-on-noncanonical-stamp",
        "--fail-on-integrity-error",
        "--fail-on-lineage-collision",
    ],
)
def test_stamp_foreign_keys_rejected_even_when_integrity_and_schema_match(
    tmp_path: Path, relationship: str, flag: str
) -> None:
    databases = [tmp_path / "study.sqlite", tmp_path / "reference.sqlite"]
    for database in databases:
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            if relationship == "outgoing":
                connection.execute("CREATE TABLE observations (id TEXT PRIMARY KEY)")
                connection.execute("INSERT INTO observations VALUES ('0038')")
                connection.execute(
                    "CREATE TABLE alembic_version (version_num VARCHAR(32) "
                    "NOT NULL PRIMARY KEY REFERENCES observations(id))"
                )
                connection.execute("INSERT INTO alembic_version VALUES ('0038')")
            else:
                connection.execute(
                    "CREATE TABLE alembic_version "
                    "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
                )
                connection.execute("INSERT INTO alembic_version VALUES ('0038')")
                action = "UPDATE" if relationship == "update" else "DELETE"
                connection.execute(
                    "CREATE TABLE \"observer's records\" (revision TEXT "
                    f"REFERENCES ALEMBIC_VERSION(version_num) ON {action} CASCADE)"
                )
                connection.execute("INSERT INTO \"observer's records\" VALUES ('0038')")
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    before = [database.read_bytes() for database in databases]
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(databases[0]),
            "--compare-to",
            str(databases[1]),
            flag,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["foreign_key_violation_count"] == 0
    comparison = report["schema_comparison"]
    assert comparison["matches"] is True
    assert comparison["revision_markers_match"] is False
    assert report["alembic_stamp_constraint_error"] == (
        "alembic_version_foreign_keys_require_review"
    )
    assert comparison["reference_integrity"]["alembic_stamp_constraint_error"] == (
        "alembic_version_foreign_keys_require_review"
    )
    assert report["classification"] == "requires_researcher_review"
    assert [database.read_bytes() for database in databases] == before


def test_unrelated_foreign_keys_do_not_invalidate_stamp_contract(tmp_path: Path) -> None:
    database = tmp_path / "study.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
        connection.execute("INSERT INTO alembic_version VALUES ('0038')")
        connection.execute("CREATE TABLE specimens (id TEXT PRIMARY KEY)")
        connection.execute("CREATE TABLE observations (id TEXT REFERENCES specimens(id))")
        connection.execute("INSERT INTO specimens VALUES ('private specimen')")
        connection.execute("INSERT INTO observations VALUES ('private specimen')")
    before = database.read_bytes()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(database), "--fail-on-noncanonical-stamp"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["alembic_stamp_constraint_error"] is None
    assert "private specimen" not in result.stdout
    assert database.read_bytes() == before
