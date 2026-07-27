from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import ImageAsset, Project
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project, import_one


def _make_old(path: Path, *, seconds: int = 180) -> None:
    timestamp = (datetime.now(UTC) - timedelta(seconds=seconds)).timestamp()
    os.utime(path, (timestamp, timestamp))


def test_repair_plan_quarantines_only_old_unreferenced_files(
    client: TestClient,
) -> None:
    project = create_project(client, "Repair orphan project")
    project_id = str(project["id"])
    imported = import_one(client, project_id)
    image_id = str(imported["successful"][0]["image_id"])
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        image = session.get(ImageAsset, image_id)
        assert image is not None
        protected_path = resolve_managed_project_path(
            app.state.settings,
            image.managed_path,
        )
    _make_old(protected_path)

    orphan_relative = f"projects/{project_id}/misc/orphan.bin"
    orphan_path = resolve_managed_project_path(app.state.settings, orphan_relative)
    orphan_path.parent.mkdir(parents=True, exist_ok=True)
    orphan_path.write_bytes(b"unreferenced")
    _make_old(orphan_path)

    recent_relative = f"projects/{project_id}/misc/recent.bin"
    recent_path = resolve_managed_project_path(app.state.settings, recent_relative)
    recent_path.write_bytes(b"recent")

    preview = client.get(
        f"/api/v1/projects/{project_id}/integrity/repair-plan",
        params={"minimum_orphan_age_seconds": 60},
    )
    assert preview.status_code == 200, preview.text
    payload = preview.json()
    assert payload["orphan_file_count"] == 1
    assert payload["orphan_file_bytes"] == len(b"unreferenced")
    action = payload["actions"][0]
    assert action["action_kind"] == "quarantine_orphan_file"
    assert action["managed_path"] == orphan_relative

    applied = client.post(
        f"/api/v1/projects/{project_id}/integrity/repairs",
        json={
            "action_ids": [action["action_id"]],
            "minimum_orphan_age_seconds": 60,
        },
    )
    assert applied.status_code == 200, applied.text
    result = applied.json()
    assert result["applied_action_ids"] == [action["action_id"]]
    assert result["skipped_action_ids"] == []
    assert len(result["quarantined_paths"]) == 1
    quarantine_path = resolve_managed_project_path(
        app.state.settings,
        result["quarantined_paths"][0],
    )
    assert quarantine_path.read_bytes() == b"unreferenced"
    assert not orphan_path.exists()
    assert protected_path.is_file()
    assert recent_path.is_file()

    second_preview = client.get(
        f"/api/v1/projects/{project_id}/integrity/repair-plan",
        params={"minimum_orphan_age_seconds": 60},
    )
    assert second_preview.status_code == 200, second_preview.text
    assert second_preview.json()["orphan_file_count"] == 0


def test_changed_orphan_requires_a_new_preview(client: TestClient) -> None:
    project = create_project(client, "Stale repair plan")
    project_id = str(project["id"])
    app = cast(FastAPI, client.app)
    orphan_relative = f"projects/{project_id}/orphan.dat"
    orphan_path = resolve_managed_project_path(app.state.settings, orphan_relative)
    orphan_path.parent.mkdir(parents=True, exist_ok=True)
    orphan_path.write_bytes(b"first")
    _make_old(orphan_path)

    preview = client.get(
        f"/api/v1/projects/{project_id}/integrity/repair-plan",
        params={"minimum_orphan_age_seconds": 60},
    )
    assert preview.status_code == 200, preview.text
    action_id = preview.json()["actions"][0]["action_id"]

    orphan_path.write_bytes(b"changed after preview")
    _make_old(orphan_path)
    applied = client.post(
        f"/api/v1/projects/{project_id}/integrity/repairs",
        json={
            "action_ids": [action_id],
            "minimum_orphan_age_seconds": 60,
        },
    )
    assert applied.status_code == 400, applied.text
    assert "repair plan changed" in applied.text.lower()
    assert orphan_path.read_bytes() == b"changed after preview"


def test_missing_project_root_can_be_previewed_and_created(
    client: TestClient,
) -> None:
    project = create_project(client, "Missing project root")
    project_id = str(project["id"])
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        record = session.get(Project, project_id)
        assert record is not None
        project_root = resolve_managed_project_path(
            app.state.settings,
            record.storage_root,
        )
    shutil.rmtree(project_root)

    preview = client.get(f"/api/v1/projects/{project_id}/integrity/repair-plan")
    assert preview.status_code == 200, preview.text
    actions = preview.json()["actions"]
    assert len(actions) == 1
    assert actions[0]["action_kind"] == "create_project_root"

    applied = client.post(
        f"/api/v1/projects/{project_id}/integrity/repairs",
        json={"action_ids": [actions[0]["action_id"]]},
    )
    assert applied.status_code == 200, applied.text
    assert project_root.is_dir()
    assert applied.json()["created_paths"] == [f"projects/{project_id}"]
