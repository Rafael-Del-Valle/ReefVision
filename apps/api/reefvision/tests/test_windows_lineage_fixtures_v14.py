from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import URL

_REPO = Path(__file__).resolve().parents[4]
_SCRIPT = _REPO / "scripts" / "create_windows_lineage_fixtures.py"


def _query(database: Path, query: str) -> list[tuple[object, ...]]:
    with closing(sqlite3.connect(database)) as connection:
        return connection.execute(query).fetchall()


def test_windows_lineage_fixtures_upgrade_and_keep_pre_upgrade_backups(tmp_path: Path) -> None:
    output = tmp_path / "fixtures"
    args = [sys.executable, str(_SCRIPT), str(output)]
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert {entry["revision"] for entry in manifest["profiles"]} == {
        "b13_temporal_0001",
        "0038",
        "0039",
    }
    for entry in manifest["profiles"]:
        database = output / entry["database"]
        backup = output / entry["backup"]
        assert hashlib.sha256(backup.read_bytes()).hexdigest() == entry["backup_sha256"]
        assert _query(backup, "PRAGMA integrity_check") == [("ok",)]
        assert _query(database, "SELECT version_num FROM alembic_version") == [(entry["revision"],)]
        evidence_query = {
            "b13_temporal_0001": "SELECT id, variable FROM scientific_records",
            "0038": "SELECT id, original_filename FROM spatial_source_assets",
            "0039": "SELECT id, source_sha256 FROM spatial_calibration_reviews",
        }[entry["revision"]]
        expected = _query(backup, evidence_query)
        assert len(expected) == 1
        assert _query(database, evidence_query) == expected

        config = Config(str(_REPO / "apps" / "api" / "alembic.ini"))
        config.attributes["configure_logger"] = False
        config.set_main_option(
            "sqlalchemy.url", URL.create("sqlite", database=str(database)).render_as_string()
        )
        command.upgrade(config, "head")
        assert _query(database, "SELECT version_num FROM alembic_version") == [
            ("b14_spatial_0040",)
        ]
        assert _query(database, evidence_query) == expected
        assert _query(backup, "SELECT version_num FROM alembic_version") == [(entry["revision"],)]
        assert hashlib.sha256(backup.read_bytes()).hexdigest() == entry["backup_sha256"]

    prior = (output / "manifest.json").read_bytes()
    repeated = subprocess.run(args, capture_output=True, text=True, check=False)
    assert repeated.returncode != 0
    assert "already exists" in repeated.stderr
    assert (output / "manifest.json").read_bytes() == prior
