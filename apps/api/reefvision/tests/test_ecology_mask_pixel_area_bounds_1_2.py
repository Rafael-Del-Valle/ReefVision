"""Reject impossible mask pixel counts before ecological projected-area analysis."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import MaskAnnotation
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_ecology_annotation_evidence_1_2 import _annotation_link, _mask
from reefvision.tests.test_ecology_image_evidence_1_2 import _link, _register, _workflow


def _source(client: TestClient) -> tuple[str, str, str]:
    project = create_project(client, "Ecological mask pixel-count plausibility")
    project_id = str(project["id"])
    image_id = str(import_one(client, project_id)["successful"][0]["image_id"])
    _register(client, project_id, "colony-a")
    linked_image = _link(client, project_id, "colony-a", image_id)
    assert linked_image.status_code == 201, linked_image.text
    mask_id = _mask(client, image_id, str(project["label_classes"][0]["id"]))
    return project_id, linked_image.json()["id"], mask_id


@pytest.mark.parametrize(
    ("area_pixels", "message"),
    [
        (5000, "exceeds source image dimensions"),
        (1000, "exceeds its source-pixel bounds"),
    ],
)
def test_impossible_mask_area_rejected_before_source_link(
    client: TestClient, area_pixels: int, message: str
) -> None:
    # The 80x60 source contains 4800 pixels; the 20x15 mask's inclusive
    # pixel envelope is far smaller. Neither inflated count can be evidence.
    project_id, image_link_id, mask_id = _source(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        mask = session.get(MaskAnnotation, mask_id)
        assert mask is not None
        mask.area_pixels = area_pixels
        session.commit()

    rejected = _annotation_link(client, project_id, image_link_id, "mask", mask_id)
    assert rejected.status_code == 400, rejected.text
    assert message in rejected.json()["detail"]
    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 200, registry.text
    assert registry.json()["annotation_evidence_count"] == 0


@pytest.mark.parametrize(
    ("area_pixels", "message"),
    [
        (5000, "exceeds source image dimensions"),
        (1000, "exceeds its source-pixel bounds"),
    ],
)
def test_corrupted_linked_mask_area_revokes_api_and_saved_workflow(
    client: TestClient, area_pixels: int, message: str
) -> None:
    project_id, image_link_id, mask_id = _source(client)
    linked = _annotation_link(client, project_id, image_link_id, "mask", mask_id)
    assert linked.status_code == 201, linked.text
    registry_url = f"/api/v1/projects/{project_id}/ecology/identity-registry"
    before = client.get(registry_url)
    assert before.status_code == 200, before.text
    assert before.json()["annotation_evidence_count"] == 1

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        mask = session.get(MaskAnnotation, mask_id)
        assert mask is not None
        mask.area_pixels = area_pixels
        session.commit()

    rejected = client.get(registry_url)
    assert rejected.status_code == 400, rejected.text
    assert message in rejected.json()["detail"]
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "failed"
    assert message in workflow["run"]["error_message"]
    assert not any(row["data_type"] == "ecology_identity_registry" for row in workflow["artifacts"])


def test_plausible_mask_area_keeps_unverified_saved_workflow_parity(
    client: TestClient,
) -> None:
    project_id, image_link_id, mask_id = _source(client)
    linked = _annotation_link(client, project_id, image_link_id, "mask", mask_id)
    assert linked.status_code == 201, linked.text
    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 200, registry.text
    assert registry.json()["review_gate"] == "scientist_review_required"
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    artifacts = [
        row for row in workflow["artifacts"] if row["data_type"] == "ecology_identity_registry"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == registry.json()
