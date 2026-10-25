"""Prevent failed imports from deleting an existing scientific image original."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.services import images as image_services
from reefvision.tests.test_images import create_project, image_bytes, import_one


def test_import_destination_collision_preserves_existing_original(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Immutable camera original collision")
    image_id = UUID("00000000-0000-4000-8000-000000000103")
    staging_id = UUID("00000000-0000-4000-8000-000000000104")
    original = (
        Path(test_settings.resolved_data_dir)
        / project["storage_root"]
        / "images"
        / "originals"
        / f"{image_id}.png"
    )
    original.parent.mkdir(parents=True, exist_ok=True)
    sentinel = b"previously persisted scientific image - never delete"
    original.write_bytes(sentinel)

    generated_ids = iter((staging_id, image_id))
    monkeypatch.setattr(image_services, "uuid4", lambda: next(generated_ids))

    report = import_one(
        client,
        project["id"],
        filename="new-camera-exposure.PNG",
        content=image_bytes(size=(41, 31)),
    )

    assert not report["successful"]
    assert len(report["failed"]) == 1
    assert "already exists" in report["failed"][0]["detail"]
    assert original.read_bytes() == sentinel
    assert client.get(f"/api/v1/projects/{project['id']}/images").json()["total"] == 0
    assert not (original.parent.parent.parent / ".imports" / f"{staging_id}.part").exists()
