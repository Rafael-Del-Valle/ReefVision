"""Standalone and saved Workflow Builder parity for projected ecological evidence."""

from __future__ import annotations

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import ImageAsset
from reefvision.tests.test_ecology_calibration_evidence_1_2 import (
    _link_calibration,
    _prepared_annotation,
    _save_calibration,
)
from reefvision.tests.test_ecology_image_evidence_1_2 import _workflow


def _get(client: TestClient, project_id: str):
    return client.get(
        f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    )


def test_projected_box_candidates_are_typed_unverified_and_saved(
    client: TestClient,
) -> None:
    project_id, image_id, annotation = _prepared_annotation(client)
    _save_calibration(client, image_id)
    assert _link_calibration(client, project_id, annotation).status_code == 201
    response = _get(client, project_id)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["candidate_count"] == 2
    assert payload["evidence_level"] == "linked_unverified"
    assert payload["review_gate"] == "scientist_review_required"
    assert {row["metric"]: row["value"] for row in payload["candidates"]} == {
        "box_width": 6.25,
        "box_height": 5.0,
    }
    assert {row["unit"] for row in payload["candidates"]} == {"mm"}
    assert all(row["capture_time_status"] == "missing" for row in payload["candidates"])
    assert all(row["capture_timestamp_utc"] is None for row in payload["candidates"])
    assert len(payload["input_sha256"]) == 64

    registry = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry.status_code == 200
    node = next(
        item for item in registry.json()
        if item["node_type"] == "ecology_identity_registry_source"
    )
    assert any(
        port["port_id"] == "measurement_candidates"
        and port["accepted_types"] == ["ecology_measurement_candidates"]
        for port in node["output_ports"]
    )
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    artifacts = [
        item for item in workflow["artifacts"]
        if item["data_type"] == "ecology_measurement_candidates"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == payload


def test_source_change_revokes_candidate_api_and_saved_workflow(
    client: TestClient,
) -> None:
    project_id, image_id, annotation = _prepared_annotation(client)
    _save_calibration(client, image_id)
    assert _link_calibration(client, project_id, annotation).status_code == 201
    assert _get(client, project_id).status_code == 200
    _save_calibration(client, image_id, scale=0.5)
    assert _get(client, project_id).status_code == 400
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "failed"
    assert not any(
        row["data_type"] == "ecology_measurement_candidates"
        for row in workflow["artifacts"]
    )


def test_perspective_transform_is_explicitly_excluded_not_scaled(
    client: TestClient,
) -> None:
    project_id, image_id, annotation = _prepared_annotation(client)
    _save_calibration(client, image_id)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        image = session.get(ImageAsset, image_id)
        assert image is not None
        metadata = dict(image.metadata_json or {})
        saved = dict(metadata["measurement_calibration"])
        saved["perspective_homography"] = [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ]
        metadata["measurement_calibration"] = saved
        image.metadata_json = metadata
        session.commit()
    assert _link_calibration(client, project_id, annotation).status_code == 201
    payload = _get(client, project_id).json()
    assert payload["candidate_count"] == 0
    assert payload["exclusions"][0]["reason"] == "perspective_transform_requires_review"
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    artifacts = [
        row for row in workflow["artifacts"]
        if row["data_type"] == "ecology_measurement_candidates"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == payload
