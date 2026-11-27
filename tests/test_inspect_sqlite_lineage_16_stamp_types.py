"""Non-text Alembic revision declarations cannot establish trusted lineage."""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "inspect_sqlite_lineage_16.py"


@pytest.mark.parametrize("column_type", ["INTEGER", "BLOB", "NUMERIC", "VARCHAR(64)"])
def test_noncanonical_stamp_type_is_diagnostic_and_fails_strict_gates(
    tmp_path: Path, column_type: str
) -> None:
    database = tmp_path / "science.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(
            f"CREATE TABLE alembic_version (version_num {column_type} NOT NULL PRIMARY KEY)"
        )
        connection.execute("INSERT INTO alembic_version VALUES ('0038')")
        connection.execute("CREATE TABLE observations (id INTEGER PRIMARY KEY, note TEXT)")
        connection.execute("INSERT INTO observations (note) VALUES ('private coral data')")
    original = database.read_bytes()
    for options, expected in [
        ([], 0),
        (["--fail-on-noncanonical-stamp"], 2),
        (["--fail-on-integrity-error"], 2),
    ]:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(database), *options],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == expected, result.stderr
        report = json.loads(result.stdout)
        assert report["alembic_stamp_constraint_error"] == (
            "invalid_alembic_version_column_constraints"
        )
        assert report["classification"] == "requires_researcher_review"
        assert "private coral data" not in result.stdout
        assert database.read_bytes() == original


@pytest.mark.parametrize(
    ("declaration", "canonical"),
    [
        ("version_num TEXT NOT NULL PRIMARY KEY", True),
        ("version_num VARCHAR(32) NOT NULL PRIMARY KEY", True),
        ("version_num TEXT COLLATE BINARY NOT NULL PRIMARY KEY", True),
        ("version_num TEXT COLLATE NOCASE NOT NULL PRIMARY KEY", False),
        ("version_num TEXT COLLATE RTRIM NOT NULL PRIMARY KEY", False),
        ("version_num TEXT NOT NULL PRIMARY KEY DESC", False),
        ("version_num TEXT NOT NULL, PRIMARY KEY(version_num DESC)", False),
        ("version_num TEXT NOT NULL, PRIMARY KEY(version_num COLLATE NOCASE)", False),
        ("version_num TEXT NOT NULL, PRIMARY KEY(version_num ASC)", True),
    ],
)
def test_stamp_primary_key_semantics_in_both_comparison_inputs(
    tmp_path: Path, declaration: str, canonical: bool
) -> None:
    databases = [tmp_path / "source.sqlite", tmp_path / "copy.sqlite"]
    for database in databases:
        with sqlite3.connect(database) as connection:
            connection.execute(f"CREATE TABLE alembic_version ({declaration})")
            connection.execute("INSERT INTO alembic_version VALUES ('0038')")
            connection.execute("CREATE TABLE observations (note TEXT)")
            connection.execute("INSERT INTO observations VALUES ('private coral data')")
            assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    originals = [database.read_bytes() for database in databases]
    for options in [
        [],
        ["--fail-on-noncanonical-stamp"],
        ["--fail-on-integrity-error"],
        ["--fail-on-lineage-collision"],
    ]:
        result = subprocess.run(
            [
                sys.executable, str(SCRIPT), str(databases[0]),
                "--compare-to", str(databases[1]), *options,
            ],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == (0 if canonical or not options else 2), result.stderr
        report = json.loads(result.stdout)
        expected = None if canonical else "invalid_alembic_version_column_constraints"
        assert report["alembic_stamp_constraint_error"] == expected
        assert report["classification"] == "requires_researcher_review"
        assert "private coral data" not in result.stdout
        assert [database.read_bytes() for database in databases] == originals


@pytest.mark.parametrize(
    ("declaration", "index_sql", "error"),
    [
        ("version_num TEXT NOT NULL PRIMARY KEY", None, None),
        (
            'version_num VARCHAR(32) NOT NULL, CONSTRAINT "CHECK" PRIMARY KEY (version_num)',
            None, None,
        ),
        ("version_num TEXT NOT NULL PRIMARY KEY /* CHECK is a comment */", None, None),
        (
            "version_num TEXT NOT NULL PRIMARY KEY, UNIQUE(version_num COLLATE NOCASE)",
            None, "alembic_version_indexes_require_review",
        ),
        (
            "version_num TEXT NOT NULL PRIMARY KEY, UNIQUE(version_num COLLATE RTRIM)",
            None, "alembic_version_indexes_require_review",
        ),
        (
            'version_num TEXT NOT NULL PRIMARY KEY, CONSTRAINT "private coral data" '
            "UNIQUE(version_num COLLATE NOCASE)",
            None, "alembic_version_indexes_require_review",
        ),
        (
            "version_num TEXT NOT NULL PRIMARY KEY, UNIQUE(version_num)",
            None, None,
        ),
        (
            "version_num TEXT NOT NULL PRIMARY KEY, UNIQUE(version_num COLLATE BINARY)",
            None, None,
        ),
        (
            "version_num TEXT NOT NULL PRIMARY KEY CHECK(version_num = '0039')",
            None, "alembic_version_checks_require_review",
        ),
        (
            "version_num TEXT NOT NULL PRIMARY KEY, CHECK/* hidden */(version_num = '0039')",
            None, "alembic_version_checks_require_review",
        ),
        (
            "version_num TEXT NOT NULL PRIMARY KEY",
            "CREATE INDEX extra ON alembic_version(version_num)",
            "alembic_version_indexes_require_review",
        ),
        (
            "version_num TEXT NOT NULL PRIMARY KEY",
            "CREATE UNIQUE INDEX extra ON alembic_version(version_num)",
            "alembic_version_indexes_require_review",
        ),
        (
            "version_num TEXT NOT NULL PRIMARY KEY",
            "CREATE INDEX extra ON alembic_version("
            "abs(CASE WHEN version_num = '0040' THEN -9223372036854775808 ELSE 1 END))",
            "alembic_version_indexes_require_review",
        ),
        (
            "version_num TEXT NOT NULL PRIMARY KEY",
            "CREATE INDEX extra ON alembic_version(version_num) WHERE "
            "abs(CASE WHEN version_num = '0040' THEN -9223372036854775808 ELSE 1 END)>0",
            "alembic_version_indexes_require_review",
        ),
    ],
)
def test_stamp_check_and_index_contracts_in_both_comparison_inputs(
    tmp_path: Path, declaration: str, index_sql: str | None, error: str | None
) -> None:
    databases = [tmp_path / "source.sqlite", tmp_path / "copy.sqlite"]
    for database in databases:
        with sqlite3.connect(database) as connection:
            connection.execute(f"CREATE TABLE alembic_version ({declaration})")
            connection.execute("INSERT INTO alembic_version VALUES ('0039')")
            connection.execute("CREATE TABLE observations (note TEXT)")
            connection.execute("INSERT INTO observations VALUES ('private coral data')")
            if index_sql is not None:
                connection.execute(index_sql)
            assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    originals = [database.read_bytes() for database in databases]
    for options in [
        [],
        ["--fail-on-noncanonical-stamp"],
        ["--fail-on-integrity-error"],
        ["--fail-on-lineage-collision"],
        ["--fail-on-revision-mismatch"],
    ]:
        result = subprocess.run(
            [
                sys.executable, str(SCRIPT), str(databases[0]),
                "--compare-to", str(databases[1]), *options,
            ],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == (0 if error is None or not options else 2), result.stderr
        report = json.loads(result.stdout)
        assert report["alembic_stamp_constraint_error"] == error
        comparison = report["schema_comparison"]
        assert comparison["matches"] is True
        assert comparison["revision_markers_match"] is (error is None)
        assert comparison["reference_integrity"]["alembic_stamp_constraint_error"] == error
        assert report["classification"] == "requires_researcher_review"
        assert "private coral data" not in result.stdout + result.stderr
        assert "9223372036854775808" not in result.stdout + result.stderr
        assert [database.read_bytes() for database in databases] == originals


@pytest.mark.parametrize(
    ("declaration", "suffix", "error"),
    [
        ("version_num TEXT NOT NULL PRIMARY KEY", "", None),
        ("version_num VARCHAR(32) NOT NULL PRIMARY KEY", "", None),
        ("version_num TEXT NOT NULL PRIMARY KEY /* ON CONFLICT IGNORE */", "", None),
        (
            'version_num TEXT NOT NULL, CONSTRAINT "WITHOUT ROWID" PRIMARY KEY(version_num)',
            "", None,
        ),
        (
            "version_num TEXT NOT NULL PRIMARY KEY ON CONFLICT REPLACE",
            "", "alembic_version_write_storage_options_require_review",
        ),
        (
            "version_num TEXT NOT NULL PRIMARY KEY ON /* comment */ CONFLICT IGNORE",
            "", "alembic_version_write_storage_options_require_review",
        ),
        (
            "version_num TEXT NOT NULL ON CONFLICT FAIL PRIMARY KEY",
            "", "alembic_version_write_storage_options_require_review",
        ),
        (
            "version_num TEXT NOT NULL PRIMARY KEY", " WITHOUT ROWID",
            "alembic_version_write_storage_options_require_review",
        ),
        (
            "version_num TEXT NOT NULL PRIMARY KEY", " WITHOUT /* comment */ ROWID",
            "alembic_version_write_storage_options_require_review",
        ),
        (
            "version_num TEXT NOT NULL DEFAULT 'private stamp default' PRIMARY KEY",
            "", "alembic_version_default_requires_review",
        ),
        (
            "version_num TEXT NOT NULL DEFAULT NULL PRIMARY KEY",
            "", "alembic_version_default_requires_review",
        ),
        (
            "version_num TEXT NOT NULL DEFAULT (lower('X')) PRIMARY KEY",
            "", "alembic_version_default_requires_review",
        ),
    ],
)
def test_stamp_write_storage_options_in_both_comparison_inputs(
    tmp_path: Path, declaration: str, suffix: str, error: str | None
) -> None:
    databases = [tmp_path / "source.sqlite", tmp_path / "copy.sqlite"]
    for database in databases:
        with sqlite3.connect(database) as connection:
            connection.execute(f"CREATE TABLE alembic_version ({declaration}){suffix}")
            connection.execute("INSERT INTO alembic_version VALUES ('0039')")
            connection.execute("CREATE TABLE observations (note TEXT)")
            connection.execute("INSERT INTO observations VALUES ('private coral data')")
            assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    originals = [database.read_bytes() for database in databases]
    for options in [
        [],
        ["--fail-on-noncanonical-stamp"],
        ["--fail-on-integrity-error"],
        ["--fail-on-lineage-collision"],
        ["--fail-on-revision-mismatch"],
    ]:
        result = subprocess.run(
            [
                sys.executable, str(SCRIPT), str(databases[0]),
                "--compare-to", str(databases[1]), *options,
            ],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == (0 if error is None or not options else 2), result.stderr
        report = json.loads(result.stdout)
        assert report["alembic_stamp_constraint_error"] == error
        comparison = report["schema_comparison"]
        assert comparison["matches"] is True
        assert comparison["revision_markers_match"] is (error is None)
        assert comparison["reference_integrity"]["alembic_stamp_constraint_error"] == error
        assert report["classification"] == "requires_researcher_review"
        assert "private coral data" not in result.stdout + result.stderr
        assert "private stamp default" not in result.stdout + result.stderr
        assert [database.read_bytes() for database in databases] == originals


@pytest.mark.parametrize(
    ("marker", "valid"),
    [
        ("0038", True),
        ("0041", True),
        ("legacy_revision", True),
        ("a" * 32, True),
        ("abc-123", True),
        ("00 38", False),
        ("0038\u200b", False),
        ("0038\u202e", False),
        ("0038\u0085", False),
        ("\uff10\uff10\uff13\uff18", False),
        ("a" * 33, False),
        ("00\t38", False),
        ("00\\38", False),
        (" 0038", False),
        ("0038 ", False),
        ("", False),
        ("private coral observation coordinates", False),
        ("private coral data", False),
        ("secret\x00field", False),
    ],
)
def test_revision_marker_token_contract_in_either_copy(
    tmp_path: Path, marker: str, valid: bool
) -> None:
    databases = [tmp_path / "source.sqlite", tmp_path / "copy.sqlite"]
    for database in databases:
        with sqlite3.connect(database) as connection:
            connection.execute(
                "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
            connection.execute("INSERT INTO alembic_version VALUES (?)", (marker,))
            connection.execute("CREATE TABLE observations (note TEXT)")
            connection.execute("INSERT INTO observations VALUES ('private coral data')")
            assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    originals = [database.read_bytes() for database in databases]
    for options in [
        [],
        ["--fail-on-noncanonical-stamp"],
        ["--fail-on-integrity-error"],
        ["--fail-on-lineage-collision"],
        ["--fail-on-revision-mismatch"],
    ]:
        result = subprocess.run(
            [
                sys.executable, str(SCRIPT), str(databases[0]),
                "--compare-to", str(databases[1]), *options,
            ],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == (0 if valid or not options else 2), result.stderr
        report = json.loads(result.stdout)
        expected = None if valid else "invalid_revision_marker_type_or_value"
        assert report["alembic_stamp_validation_error"] == expected
        comparison = report["schema_comparison"]
        assert comparison["matches"] is True
        assert comparison["revision_markers_match"] is valid
        assert report["alembic_stamps"] == [marker if valid else None]
        assert comparison["reference_alembic_stamps"] == [marker if valid else None]
        assert comparison["reference_integrity"]["alembic_stamp_validation_error"] == expected
        assert report["classification"] == "requires_researcher_review"
        assert "private coral data" not in result.stdout + result.stderr
        assert [database.read_bytes() for database in databases] == originals


@pytest.mark.parametrize("invalid_index", [0, 1])
def test_invalid_revision_marker_is_redacted_on_either_side(
    tmp_path: Path, invalid_index: int
) -> None:
    databases = [tmp_path / "source.sqlite", tmp_path / "copy.sqlite"]
    private_marker = "private coral field location"
    for index, database in enumerate(databases):
        with sqlite3.connect(database) as connection:
            connection.execute(
                "CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)"
            )
            marker = private_marker if index == invalid_index else "0039"
            connection.execute("INSERT INTO alembic_version VALUES (?)", (marker,))
            connection.execute("CREATE TABLE observations (note TEXT)")
            connection.execute("INSERT INTO observations VALUES ('private observation')")
    originals = [database.read_bytes() for database in databases]
    for options in [
        [],
        ["--fail-on-noncanonical-stamp"],
        ["--fail-on-integrity-error"],
        ["--fail-on-lineage-collision"],
        ["--fail-on-revision-mismatch"],
    ]:
        result = subprocess.run(
            [
                sys.executable, str(SCRIPT), str(databases[0]),
                "--compare-to", str(databases[1]), *options,
            ],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == (2 if options else 0), result.stderr
        report = json.loads(result.stdout)
        comparison = report["schema_comparison"]
        assert report["alembic_stamps"] == [None if invalid_index == 0 else "0039"]
        assert comparison["reference_alembic_stamps"] == [
            None if invalid_index == 1 else "0039"
        ]
        assert comparison["matches"] is True
        assert comparison["revision_markers_match"] is False
        assert report["classification"] == "requires_researcher_review"
        assert private_marker not in result.stdout + result.stderr
        assert "private observation" not in result.stdout + result.stderr
        assert [database.read_bytes() for database in databases] == originals
