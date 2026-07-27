from __future__ import annotations

import hashlib
from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import ArtifactRecord, Project, WorkflowArtifact, WorkflowRun
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_workflow_recovery_phase10 import _create_run


def _terminal_run_with_file(
    client: TestClient,
    *,
    filename: str = "export.json",
) -> tuple[str, str, Path, str]:
    _workflow_id, run_id = _create_run(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        run = session.get(WorkflowRun, run_id)
        assert run is not None
        project = session.get(Project, run.project_id)
        assert project is not None
        run.status = "succeeded"
        run.stage = "completed"
        relative = f"{project.storage_root}/workflows/{run.id}/{filename}"
        path = resolve_managed_project_path(app.state.settings, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"result": true}', encoding="utf-8")
        artifact = WorkflowArtifact(
            workflow_run_id=run.id,
            node_id="export",
            port_name="archive",
            artifact_type="export_archive",
            checksum="a" * 64,
            payload_json={"managed_path": relative, "_cache_key": "old-cache"},
            managed_path=relative,
            size_bytes=path.stat().st_size,
        )
        session.add(artifact)
        session.commit()
        return run.id, artifact.id, path, relative


def _quarantine_artifact(
    client: TestClient,
    run_id: str,
) -> dict[str, object]:
    preview = client.post(
        f"/api/v1/workflow-runs/{run_id}/artifact-cleanup/preview",
        json={},
    )
    assert preview.status_code == 200, preview.text
    action = preview.json()["actions"][0]
    applied = client.post(
        f"/api/v1/workflow-runs/{run_id}/artifact-cleanup/apply",
        json={
            "preview_checksum": preview.json()["preview_checksum"],
            "action_ids": [action["action_id"]],
        },
    )
    assert applied.status_code == 200, applied.text
    return applied.json()


def test_cleanup_preview_requires_terminal_run(client: TestClient) -> None:
    _workflow_id, run_id = _create_run(client)
    response = client.post(
        f"/api/v1/workflow-runs/{run_id}/artifact-cleanup/preview",
        json={},
    )
    assert response.status_code == 409, response.text


def test_selected_workflow_file_is_quarantined_and_reference_is_cleared(
    client: TestClient,
) -> None:
    run_id, artifact_id, source_path, original_relative = _terminal_run_with_file(client)
    preview = client.post(
        f"/api/v1/workflow-runs/{run_id}/artifact-cleanup/preview",
        json={"node_ids": ["export"]},
    )
    assert preview.status_code == 200, preview.text
    payload = preview.json()
    assert payload["action_count"] == 1
    assert payload["eligible_action_count"] == 1
    action = payload["actions"][0]
    assert action["action_kind"] == "quarantine_file"
    assert action["managed_path"] == original_relative
    assert action["file_sha256"] == hashlib.sha256(source_path.read_bytes()).hexdigest()

    applied = client.post(
        f"/api/v1/workflow-runs/{run_id}/artifact-cleanup/apply",
        json={
            "preview_checksum": payload["preview_checksum"],
            "action_ids": [action["action_id"]],
            "node_ids": ["export"],
        },
    )
    assert applied.status_code == 200, applied.text
    result = applied.json()
    assert result["quarantined_file_count"] == 1
    assert result["reclaimed_bytes"] > 0
    assert source_path.exists() is False
    quarantine = resolve_managed_project_path(
        cast(FastAPI, client.app).state.settings,
        result["quarantine_paths"][0],
    )
    assert quarantine.is_file()

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        artifact = session.get(WorkflowArtifact, artifact_id)
        assert artifact is not None
        assert artifact.managed_path is None
        assert artifact.size_bytes is None
        cleanup = dict(artifact.payload_json or {})["_cleanup"]
        assert cleanup["original_managed_path"] == original_relative
        assert cleanup["original_artifact_checksum"] == "a" * 64
        assert cleanup["quarantine_path"] == result["quarantine_paths"][0]
        assert "_cache_key" not in artifact.payload_json


def test_quarantined_workflow_artifact_can_be_restored(client: TestClient) -> None:
    run_id, artifact_id, original_path, original_relative = _terminal_run_with_file(client)
    original_bytes = original_path.read_bytes()
    result = _quarantine_artifact(client, run_id)
    quarantine_path = resolve_managed_project_path(
        cast(FastAPI, client.app).state.settings,
        str(result["quarantine_paths"][0]),
    )
    assert quarantine_path.is_file()
    assert not original_path.exists()

    listed = client.get(f"/api/v1/workflow-runs/{run_id}/artifact-quarantine")
    assert listed.status_code == 200, listed.text
    payload = listed.json()
    assert payload["item_count"] == 1
    assert payload["restorable_count"] == 1
    item = payload["items"][0]
    assert item["artifact_id"] == artifact_id
    assert item["original_managed_path"] == original_relative
    assert item["restorable"] is True

    restored = client.post(
        f"/api/v1/workflow-runs/{run_id}/artifact-quarantine/restore",
        json={"artifact_ids": [artifact_id]},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["restored_artifact_count"] == 1
    assert restored.json()["restored_paths"] == [original_relative]
    assert original_path.read_bytes() == original_bytes
    assert not quarantine_path.exists()

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        artifact = session.get(WorkflowArtifact, artifact_id)
        assert artifact is not None
        assert artifact.managed_path == original_relative
        assert artifact.size_bytes == len(original_bytes)
        assert artifact.checksum == "a" * 64
        payload_json = dict(artifact.payload_json or {})
        assert "_cleanup" not in payload_json
        assert payload_json["_cleanup_history"][-1]["restored_managed_path"] == original_relative


def test_restore_is_blocked_when_original_destination_reappears(client: TestClient) -> None:
    run_id, artifact_id, original_path, _relative = _terminal_run_with_file(client)
    _quarantine_artifact(client, run_id)
    original_path.parent.mkdir(parents=True, exist_ok=True)
    original_path.write_text("new output", encoding="utf-8")

    listed = client.get(f"/api/v1/workflow-runs/{run_id}/artifact-quarantine")
    assert listed.status_code == 200
    item = listed.json()["items"][0]
    assert item["artifact_id"] == artifact_id
    assert item["restorable"] is False
    assert any("destination already exists" in value for value in item["blockers"])

    restored = client.post(
        f"/api/v1/workflow-runs/{run_id}/artifact-quarantine/restore",
        json={"artifact_ids": [artifact_id]},
    )
    assert restored.status_code == 400
    assert "Blocked workflow quarantine items cannot be restored" in restored.text
    assert original_path.read_text(encoding="utf-8") == "new output"


def test_cleanup_rejects_stale_preview_after_file_changes(client: TestClient) -> None:
    run_id, _artifact_id, path, _relative = _terminal_run_with_file(client)
    preview = client.post(
        f"/api/v1/workflow-runs/{run_id}/artifact-cleanup/preview",
        json={},
    )
    assert preview.status_code == 200
    action = preview.json()["actions"][0]
    path.write_text("changed after preview", encoding="utf-8")

    applied = client.post(
        f"/api/v1/workflow-runs/{run_id}/artifact-cleanup/apply",
        json={
            "preview_checksum": preview.json()["preview_checksum"],
            "action_ids": [action["action_id"]],
        },
    )
    assert applied.status_code == 409, applied.text
    assert path.is_file()


def test_shared_managed_file_is_blocked(client: TestClient) -> None:
    run_id, _artifact_id, path, relative = _terminal_run_with_file(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        run = session.get(WorkflowRun, run_id)
        assert run is not None
        session.add(
            ArtifactRecord(
                project_id=run.project_id,
                artifact_type="shared-test",
                created_by="test",
                reefvision_version="test",
                source_kind="workflow",
                source_id=run.id,
                parameters_json={},
                postprocessing_json={},
                review_status="unreviewed",
                managed_path=relative,
                checksum=hashlib.sha256(path.read_bytes()).hexdigest(),
                size_bytes=path.stat().st_size,
                metadata_json={},
            )
        )
        session.commit()

    preview = client.post(
        f"/api/v1/workflow-runs/{run_id}/artifact-cleanup/preview",
        json={},
    )
    assert preview.status_code == 200
    action = preview.json()["actions"][0]
    assert action["eligible"] is False
    assert any("registered project artifact" in item for item in action["blockers"])


def test_missing_file_reference_can_be_cleared(client: TestClient) -> None:
    run_id, artifact_id, path, _relative = _terminal_run_with_file(client)
    path.unlink()
    preview = client.post(
        f"/api/v1/workflow-runs/{run_id}/artifact-cleanup/preview",
        json={},
    )
    assert preview.status_code == 200
    payload = preview.json()
    action = payload["actions"][0]
    assert action["action_kind"] == "clear_missing_reference"
    assert action["eligible"] is True

    applied = client.post(
        f"/api/v1/workflow-runs/{run_id}/artifact-cleanup/apply",
        json={
            "preview_checksum": payload["preview_checksum"],
            "action_ids": [action["action_id"]],
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["cleared_reference_count"] == 1
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        artifact = session.get(WorkflowArtifact, artifact_id)
        assert artifact is not None
        assert artifact.managed_path is None
