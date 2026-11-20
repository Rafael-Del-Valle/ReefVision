from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import URL, create_engine
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.services.spatial_source_assets_v14 import SpatialSourceAssetService

_REPO = Path(__file__).resolve().parents[4]
_GENERATOR = _REPO / "scripts" / "create_windows_lineage_fixtures.py"
_VERIFIER = _REPO / "scripts" / "verify_windows_lineage_fixture.py"
_PROJECT = "507af087-ff80-458f-9470-9b3bdc980a5b"
_SCIENTIFIC_RECORD = "471a1c20-7afc-4edf-b6c1-023523fef1d7"
_ASSET = "04f9c44e-d30e-494f-ab1e-9aa3b4db02e9"
_REVIEW = "be5cb2db-445f-4a15-8434-5a7d168bd22e"


def _query(database: Path, query: str) -> list[tuple[object, ...]]:
    with closing(sqlite3.connect(database)) as connection:
        return connection.execute(query).fetchall()


def _generate(output: Path) -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, str(_GENERATOR), str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads((output / "manifest.json").read_text(encoding="utf-8"))


def _verify(manifest: Path, profile: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_VERIFIER), str(manifest), "--profile", profile],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def generated_fixtures(tmp_path: Path) -> Path:
    output = tmp_path / "fixtures"
    _generate(output)
    return output


def test_windows_lineage_manifest_has_deterministic_ids_and_complete_hashes(
    generated_fixtures: Path,
) -> None:
    manifest = json.loads((generated_fixtures / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "reefvision-windows-lineage-fixtures-1"
    assert manifest["fixture_kind"] == "synthetic_engineering"
    profiles = {entry["name"]: entry for entry in manifest["profiles"]}
    assert {name: entry["revision"] for name, entry in profiles.items()} == {
        "validated-1.3": "b13_temporal_0001",
        "draft-1.4-0038": "0038",
        "draft-1.4-0039": "0039",
    }
    assert all(entry["project_id"] == _PROJECT for entry in profiles.values())
    assert profiles["validated-1.3"]["records"] == [
        {
            "kind": "scientific_record",
            "id": _SCIENTIFIC_RECORD,
            "sha256": profiles["validated-1.3"]["records"][0]["sha256"],
        }
    ]
    assert [record["id"] for record in profiles["draft-1.4-0038"]["records"]] == [_ASSET]
    assert [record["id"] for record in profiles["draft-1.4-0039"]["records"]] == [
        _ASSET,
        _REVIEW,
    ]
    assert profiles["validated-1.3"]["source_files"] == []
    for entry in profiles.values():
        database = generated_fixtures / entry["database"]
        backup = generated_fixtures / entry["backup"]
        assert hashlib.sha256(database.read_bytes()).hexdigest() == entry["database_sha256"]
        assert hashlib.sha256(backup.read_bytes()).hexdigest() == entry["backup_sha256"]
        assert all(len(record["sha256"]) == 64 for record in entry["records"])
        for source in entry["source_files"]:
            source_path = generated_fixtures / source["path"]
            assert hashlib.sha256(source_path.read_bytes()).hexdigest() == source["sha256"]


def test_windows_lineage_verifier_accepts_each_generated_profile(
    generated_fixtures: Path,
) -> None:
    manifest = generated_fixtures / "manifest.json"
    for profile in ("validated-1.3", "draft-1.4-0038", "draft-1.4-0039"):
        result = _verify(manifest, profile)
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report == {
            "profile": profile,
            "status": "verified",
            "revision": {
                "validated-1.3": "b13_temporal_0001",
                "draft-1.4-0038": "0038",
                "draft-1.4-0039": "0039",
            }[profile],
            "project_id": _PROJECT,
            "record_ids": {
                "validated-1.3": [_SCIENTIFIC_RECORD],
                "draft-1.4-0038": [_ASSET],
                "draft-1.4-0039": [_ASSET, _REVIEW],
            }[profile],
        }


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("database", "database SHA-256 mismatch"),
        ("backup", "backup SHA-256 mismatch"),
        ("source", "source file SHA-256 mismatch"),
        ("revision", "database revision does not match manifest"),
        ("escape", "escapes fixture root"),
    ],
)
def test_windows_lineage_verifier_rejects_tamper_and_unsafe_paths(
    generated_fixtures: Path, tmp_path: Path, mutation: str, message: str
) -> None:
    fixture = tmp_path / f"mutated-{mutation}"
    shutil.copytree(generated_fixtures, fixture)
    manifest_path = fixture / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["profiles"] if item["name"] == "draft-1.4-0038")
    if mutation == "database":
        database = fixture / entry["database"]
        database.write_bytes(database.read_bytes() + b"x")
    elif mutation == "backup":
        backup = fixture / entry["backup"]
        backup.write_bytes(backup.read_bytes() + b"x")
    elif mutation == "source":
        (fixture / entry["source_files"][0]["path"]).write_bytes(b"changed geometry")
    elif mutation == "revision":
        entry["revision"] = "0039"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    else:
        outside = fixture.parent / "outside.db"
        outside.write_bytes((fixture / entry["database"]).read_bytes())
        entry["database"] = "../outside.db"
        entry["database_sha256"] = hashlib.sha256(outside.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    result = _verify(manifest_path, "draft-1.4-0038")
    assert result.returncode != 0
    assert message in result.stderr


def test_windows_lineage_fixtures_upgrade_and_keep_pre_upgrade_backups(
    generated_fixtures: Path,
) -> None:
    manifest = json.loads((generated_fixtures / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["profiles"]:
        database = generated_fixtures / entry["database"]
        backup = generated_fixtures / entry["backup"]
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
            "sqlalchemy.url",
            URL.create("sqlite", database=str(database)).render_as_string().replace("%", "%%"),
        )
        command.upgrade(config, "head")
        assert _query(database, "SELECT version_num FROM alembic_version") == [
            ("b17_workflows_0001",)
        ]
        assert _query(database, evidence_query) == expected
        assert _query(backup, "SELECT version_num FROM alembic_version") == [(entry["revision"],)]
        assert hashlib.sha256(backup.read_bytes()).hexdigest() == entry["backup_sha256"]


def test_windows_lineage_generator_refuses_to_overwrite(generated_fixtures: Path) -> None:
    prior = (generated_fixtures / "manifest.json").read_bytes()
    repeated = subprocess.run(
        [sys.executable, str(_GENERATOR), str(generated_fixtures)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert repeated.returncode != 0
    assert "already exists" in repeated.stderr
    assert (generated_fixtures / "manifest.json").read_bytes() == prior


@pytest.mark.parametrize("name", ("draft-1.4-0038", "draft-1.4-0039"))
def test_migrated_fixture_mesh_opens_through_production_source_service(
    generated_fixtures: Path, name: str
) -> None:
    profile = generated_fixtures / name
    url = URL.create("sqlite", database=str(profile / "reefvision.db"))
    config = Config(str(_REPO / "apps" / "api" / "alembic.ini"))
    config.attributes["configure_logger"] = False
    config.set_main_option("sqlalchemy.url", url.render_as_string().replace("%", "%%"))
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        with Session(engine) as session:
            service = SpatialSourceAssetService(session, Settings(data_dir=profile))
            content = service.read_verified(_PROJECT, _ASSET)
            assert hashlib.sha256(content).hexdigest() == next(
                entry["source_files"][0]["sha256"]
                for entry in json.loads((generated_fixtures / "manifest.json").read_text())[
                    "profiles"
                ]
                if entry["name"] == name
            )
    finally:
        engine.dispose()
