"""Exercise the verified backup and restore path on the integrated schema."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.db.models import EcologyIdentityRevision, ReefPoseReference, ScientificRecord
from reefvision.db.models.reefpose_validation import ReefPoseHeldoutLock
from reefvision.desktop import run_pending_migrations
from reefvision.jobs.backups import process_backup_job
from reefvision.jobs.restores import process_restore_job
from reefvision.main import create_app
from reefvision.schemas.backups import (
    BackupCreateResponse,
    BackupRestoreResponse,
    BackupVerificationResponse,
)

_INTEGRATED_HEAD = "b12_integrated_0001"


@pytest.fixture
def migrated_client(test_settings: Settings) -> Iterator[TestClient]:
    test_settings.ensure_directories()
    run_pending_migrations(test_settings)
    app = create_app(test_settings)
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.state.engine.dispose()


def _scientific_snapshot(database: Path, project_id: str) -> tuple[object, ...]:
    assert database.is_file()
    with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT version_num FROM alembic_version").fetchall() == [
            (_INTEGRATED_HEAD,)
        ]

        records = connection.execute(
            "SELECT * FROM scientific_records WHERE project_id = ?", (project_id,)
        ).fetchall()
        identities = connection.execute(
            "SELECT * FROM ecology_identity_revisions WHERE project_id = ? ORDER BY revision",
            (project_id,),
        ).fetchall()
        references = connection.execute(
            "SELECT * FROM reefpose_references WHERE project_id = ?", (project_id,)
        ).fetchall()
        locks = connection.execute(
            "SELECT * FROM reefpose_heldout_locks WHERE project_id = ?", (project_id,)
        ).fetchall()

    assert tuple(map(len, (records, identities, references, locks))) == (1, 2, 1, 1)
    return records, identities, references, locks


def test_verified_backup_restores_rows_from_all_integrated_histories(
    migrated_client: TestClient, test_settings: Settings, tmp_path: Path
) -> None:
    response = migrated_client.post(
        "/api/v1/projects", json={"name": "Integrated research backup", "template": "blank"}
    )
    assert response.status_code == 201, response.text
    project_id = response.json()["id"]
    factory = migrated_client.app.state.session_factory
    with factory.begin() as session:
        session.add_all(
            [
                ScientificRecord(
                    project_id=project_id,
                    variable="water_temperature",
                    source_kind="observed",
                    observed_at=datetime(2026, 10, 24, 12, tzinfo=UTC),
                    payload_json={"value": 27.5, "unit": "degC"},
                    content_sha256="a" * 64,
                ),
                EcologyIdentityRevision(
                    project_id=project_id,
                    organism_key="coral-41",
                    kind="organism",
                    revision=1,
                    reason="Initial catalogue entry",
                ),
                EcologyIdentityRevision(
                    project_id=project_id,
                    organism_key="coral-41",
                    kind="organism",
                    revision=2,
                    experimental_unit_type="tank",
                    experimental_unit_id="tank-4",
                    reason="Tank assignment",
                ),
                ReefPoseReference(
                    project_id=project_id,
                    name="Independent held-out reference",
                    data_kind="pose",
                    revision=1,
                    manifest={"video_sha256": "c" * 64, "observations": []},
                    manifest_sha256="b" * 64,
                ),
                ReefPoseHeldoutLock(
                    project_id=project_id,
                    scope_sha256="d" * 64,
                    protocol_sha256="e" * 64,
                ),
            ]
        )

    response = migrated_client.post("/api/v1/backups", json={"notes": "Integrated record backup"})
    assert response.status_code == 201, response.text
    created = BackupCreateResponse.model_validate(response.json())
    assert process_backup_job(test_settings, factory, created.job.id)

    response = migrated_client.post(f"/api/v1/backups/{created.backup.id}/verify")
    assert response.status_code == 200, response.text
    verified = BackupVerificationResponse.model_validate(response.json())
    assert verified.status == "valid"
    assert verified.current_schema_revision == _INTEGRATED_HEAD
    assert not verified.errors
    assert not verified.checksum_failures

    response = migrated_client.post(
        f"/api/v1/backups/{created.backup.id}/restore",
        json={"destination_name": "integrated-research"},
    )
    assert response.status_code == 200, response.text
    restored = BackupRestoreResponse.model_validate(response.json())
    assert process_restore_job(test_settings, factory, restored.job.id)

    data_dir = test_settings.resolved_data_dir
    source_db = tmp_path / "test.db"
    backup_db = data_dir / created.backup.destination_path / "database" / source_db.name
    restored_db = data_dir / restored.destination_path / source_db.name
    snapshot = _scientific_snapshot(source_db, project_id)
    assert _scientific_snapshot(backup_db, project_id) == snapshot
    assert _scientific_snapshot(restored_db, project_id) == snapshot
