"""Portable profile recovery retains checkpoint bytes and requests fresh local approval."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.jobs import backups
from reefvision.jobs.restores import process_restore_job
from reefvision.main import create_app
from reefvision.schemas.models import ModelRegistrationResponse
from reefvision.services.models import ModelService
from reefvision.storage.backups import BackupFileCandidate, BackupPlan
from reefvision.storage.checkpoint_approvals import verified_registered_checkpoint
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_model_inference import FakeDetectorRegistrationProvider, register_model


@pytest.mark.parametrize("legacy_media", [False, True], ids=["new-backup", "older-backup"])
def test_profile_restore_preserves_weights_without_transferring_local_checkpoint_consent(
    client: TestClient, test_settings: Settings, monkeypatch: pytest.MonkeyPatch, legacy_media: bool
) -> None:
    app = cast(FastAPI, client.app)
    root = test_settings.resolved_data_dir
    project_id = create_project(client, "Checkpoint preservation")["id"]
    monkeypatch.setattr(
        ModelService, "_provider_for_purpose", lambda *_: FakeDetectorRegistrationProvider()
    )
    model = ModelRegistrationResponse.model_validate(
        register_model(
            client, project_id, purpose="detector", filename="fixture.pt", display_name="Generated"
        )
    )
    original = verified_registered_checkpoint(test_settings, model).read_bytes()
    assert original == b"fixture-model"
    [receipt] = (root / "checkpoint-approvals").iterdir()
    asset_path = root / "projects" / project_id / "checkpoint-approvals" / "field-notes.txt"
    asset_path.parent.mkdir(parents=True)
    asset_path.write_bytes(b"ordinary project data")

    if legacy_media:
        # Generate older media through the normal backup writer using its former inventory.
        modern_plan = backups.build_backup_plan

        def previous_plan(
            settings: Settings, *, database_path: Path, include_exports: bool, include_logs: bool
        ) -> BackupPlan:
            plan = modern_plan(
                settings,
                database_path=database_path,
                include_exports=include_exports,
                include_logs=include_logs,
            )
            member = BackupFileCandidate(
                source_path=receipt,
                backup_path=f"data/checkpoint-approvals/{receipt.name}",
                size_bytes=receipt.stat().st_size,
            )
            return replace(
                plan,
                data_files=[
                    item for item in plan.data_files if item.backup_path != member.backup_path
                ]
                + [member],
                estimated_total_size_bytes=plan.estimated_total_size_bytes + member.size_bytes,
            )

        monkeypatch.setattr(backups, "build_backup_plan", previous_plan)

    requested = client.post("/api/v1/backups", json={}).raise_for_status().json()
    assert backups.process_backup_job(
        test_settings, app.state.session_factory, requested["job"]["id"]
    )
    backup = requested["backup"]
    manifest = json.loads((root / backup["manifest_path"]).read_bytes())
    inventory = {entry["path"] for entry in manifest["file_inventory"]}
    assert (f"data/checkpoint-approvals/{receipt.name}" in inventory) == legacy_media
    assert f"data/{model.managed_path}" in inventory
    assert "data/" + asset_path.relative_to(root).as_posix() in inventory

    route = f"/api/v1/backups/{backup['id']}"
    assert client.post(route + "/verify").raise_for_status().json()["status"] == "valid"
    queued = (
        client.post(route + "/restore", json={"destination_name": "recovered"})
        .raise_for_status()
        .json()
    )
    assert process_restore_job(test_settings, app.state.session_factory, queued["job"]["id"])
    destination = root / queued["destination_path"]
    assert (destination / model.managed_path).read_bytes() == original
    assert (destination / asset_path.relative_to(root)).read_bytes() == b"ordinary project data"
    assert not (destination / "checkpoint-approvals").exists()
    assert receipt.is_file()
    assert verified_registered_checkpoint(test_settings, model).read_bytes() == original

    settings = test_settings.model_copy(
        update={
            "data_dir": destination,
            "database_url": f"sqlite:///{(destination / manifest['database_filename']).as_posix()}",
        }
    )
    reopened_app = create_app(settings)
    try:
        with TestClient(reopened_app) as recovered:
            recovered_model = ModelRegistrationResponse.model_validate(
                recovered.get(f"/api/v1/models/{model.id}").raise_for_status().json()
            )
            assert recovered_model.sha256 == model.sha256
            with pytest.raises(ValidationError, match="Approve"):
                verified_registered_checkpoint(settings, recovered_model)
            approval = recovered.post(
                f"/api/v1/projects/{project_id}/models/{model.id}/approve-checkpoint",
                json={"sha256": model.sha256},
            )
            assert approval.status_code == 200, approval.text
            assert (
                verified_registered_checkpoint(settings, recovered_model).read_bytes() == original
            )
    finally:
        reopened_app.state.engine.dispose()
