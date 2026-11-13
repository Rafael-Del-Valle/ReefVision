"""Scientific heatmap API and spatial semantics regressions."""

from __future__ import annotations

from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.scientific_heatmaps import scientific_heatmap_content_hash
from reefvision.tests.test_annotations import (
    create_project,
    import_one,
)
from reefvision.tests.test_scientific_project_exchange import (
    database_counts,
    export_archive,
    import_archive,
    rewrite,
)
from reefvision.tests.test_workflow_computed_metrics import save_and_queue
from reefvision.tests.test_workflow_environmental_analysis import analysis_graph


def _url(project_id: str, image_id: str) -> str:
    return f"/api/v1/projects/{project_id}/images/{image_id}/scientific-heatmaps"


def test_empty_heatmap_is_zero_and_repeatable(
    client: TestClient,
) -> None:
    project = create_project(client, "Empty heatmaps")
    image_id = import_one(client, project["id"])["successful"][0]["image_id"]

    response = client.get(
        _url(project["id"], image_id),
        params={"columns": 4, "rows": 3},
    )
    assert response.status_code == 200, response.text
    data = response.json()

    assert len(data["layers"]) == 3
    assert [layer["kind"] for layer in data["layers"]] == [
        "reviewed_boxes",
        "verified_masks",
        "pending_predictions",
    ]

    for layer in data["layers"]:
        assert layer["object_count"] == 0
        assert layer["max_cell_count"] == 0
        assert layer["counts"] == [[0] * 4 for _ in range(3)]
        assert layer["normalized"] == [[0.0] * 4 for _ in range(3)]

    assert len(data["source_sha256"]) == 64
    assert len(data["content_sha256"]) == 64
    assert (
        client.get(
            _url(project["id"], image_id),
            params={"columns": 4, "rows": 3},
        ).json()["content_sha256"]
        == data["content_sha256"]
    )


@pytest.mark.parametrize("calibrated", [False, True])
def test_saved_heatmap_workflow_matches_standalone_physical_density(
    client: TestClient, test_settings, calibrated: bool
) -> None:
    project = create_project(client, "Calibrated heatmap")
    project_id = project["id"]
    image_id = import_one(client, project_id)["successful"][0]["image_id"]
    saved = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [
                {
                    "id": str(uuid4()),
                    "label_class_id": project["label_classes"][0]["id"],
                    "x_min": 2,
                    "y_min": 2,
                    "x_max": 12,
                    "y_max": 12,
                }
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    if calibrated:
        scale = client.put(
            f"/api/v1/images/{image_id}/measurement-calibration",
            json={"distance_per_pixel": 0.5, "unit": "cm"},
        )
        assert scale.status_code == 200, scale.text
    params = {"columns": 4, "rows": 3, "include_physical_density": True}
    result = client.get(_url(project_id, image_id), params=params)
    assert result.status_code == 200, result.text
    expected = result.json()
    assert expected["layers"][0]["counts"][0][0] == 1
    if calibrated:
        assert expected["physical_density"]["area_unit"] == "cm2"
        assert expected["physical_density"]["cell_areas"][0][0] == 100
        assert expected["physical_density"]["layers"]["reviewed_boxes"][0][0] == 0.01
    else:
        assert expected["physical_density"] is None
        assert expected["physical_unavailable_reason"] == "missing_calibration"

    graph = analysis_graph("scientific_heatmap", {"image_id": image_id, **params})
    queued = save_and_queue(client, project_id, graph)
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(app.state.settings, app.state.session_factory, queued["job_id"])
    detail = client.get(f"/api/v1/workflow-runs/{queued['id']}").json()
    assert detail["run"]["status"] == "succeeded"
    artifact = next(
        item for item in detail["artifacts"] if item["data_type"] == "scientific_heatmap"
    )
    assert artifact["payload_json"] == expected
    replay = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": queued["workflow_graph_record_id"]},
    )
    assert replay.status_code == 202, replay.text
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, replay.json()["job_id"]
    )
    detail = client.get(f"/api/v1/workflow-runs/{replay.json()['id']}").json()
    replay_artifact = next(
        item for item in detail["artifacts"] if item["data_type"] == "scientific_heatmap"
    )
    assert replay_artifact["payload_sha256"] == artifact["payload_sha256"]
    if calibrated:
        archive = export_archive(client, test_settings, project_id)
        imported = import_archive(client, archive)
        assert imported.status_code == 201, imported.text
        imported_id = imported.json()["project_id"]
        runs = client.get(f"/api/v1/projects/{imported_id}/workflow-runs").json()
        restored = client.get(f"/api/v1/workflow-runs/{runs[0]['id']}").json()
        payload = next(
            item["payload_json"]
            for item in restored["artifacts"]
            if item["data_type"] == "scientific_heatmap"
        )
        assert payload["project_id"] == imported_id
        assert payload["image_id"] != image_id
        assert payload["physical_density"] == expected["physical_density"]
        assert payload["source_sha256"] == expected["source_sha256"]
        assert payload["content_sha256"] == scientific_heatmap_content_hash(payload)

        def tamper(_manifest: dict, sections: dict) -> None:
            artifact = next(
                item
                for item in sections["workflow_artifacts"]
                if item["data_type"] == "scientific_heatmap"
            )
            artifact["payload_json"]["source_snapshot"]["image_sha256"] = "0" * 64

        before = database_counts(client)
        corrupt = import_archive(client, rewrite(archive, tamper))
        assert corrupt.status_code == 400, corrupt.text
        assert database_counts(client) == before


def test_reviewed_boxes_and_verified_masks_remain_separate(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "Coral heatmaps")
    image_id = import_one(client, project["id"])["successful"][0]["image_id"]
    label_id = project["label_classes"][0]["id"]

    saved = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [
                {
                    "id": str(uuid4()),
                    "label_class_id": label_id,
                    "x_min": 2,
                    "y_min": 2,
                    "x_max": 12,
                    "y_max": 12,
                }
            ],
            "mask_annotations": [
                {
                    "id": str(uuid4()),
                    "label_class_id": label_id,
                    "geometry_kind": "polygon",
                    "points": [
                        {"x": 25, "y": 20},
                        {"x": 45, "y": 20},
                        {"x": 45, "y": 40},
                        {"x": 25, "y": 40},
                    ],
                },
                {
                    "id": str(uuid4()),
                    "label_class_id": label_id,
                    "geometry_kind": "polygon",
                    "status": "draft",
                    "points": [
                        {"x": 50, "y": 10},
                        {"x": 60, "y": 10},
                        {"x": 60, "y": 20},
                        {"x": 50, "y": 20},
                    ],
                },
            ],
        },
    )
    assert saved.status_code == 200, saved.text

    # The draft mask is retained in provenance but must not consume the
    # two-object counting budget (one reviewed box plus one verified mask).
    monkeypatch.setattr("reefvision.services.scientific_heatmaps.MAX_OBJECTS", 2)
    response = client.get(
        _url(project["id"], image_id),
        params={"columns": 4, "rows": 3},
    )
    assert response.status_code == 200, response.text

    layers = {item["kind"]: item for item in response.json()["layers"]}

    boxes = layers["reviewed_boxes"]
    masks = layers["verified_masks"]
    predictions = layers["pending_predictions"]

    assert boxes["object_count"] == 1
    assert boxes["counts"][0][0] == 1

    assert masks["object_count"] == 1
    assert masks["counts"][1][1] == 1

    assert predictions["object_count"] == 0

    filtered = client.get(
        _url(project["id"], image_id),
        params={
            "columns": 4,
            "rows": 3,
            "label_class_id": label_id,
        },
    )
    assert filtered.status_code == 200
    assert filtered.json()["label_class_id"] == label_id


def test_wrong_project_and_invalid_grid_rejected(
    client: TestClient,
) -> None:
    first = create_project(client, "First")
    other = create_project(client, "Other")

    image_id = import_one(client, first["id"])["successful"][0]["image_id"]

    assert client.get(_url(other["id"], image_id)).status_code == 404

    assert (
        client.get(
            _url(first["id"], image_id),
            params={"columns": 1000},
        ).status_code
        == 422
    )

    assert (
        client.get(
            _url(first["id"], image_id),
            params={
                "label_class_id": other["label_classes"][0]["id"],
            },
        ).status_code
        == 404
    )


def test_unreviewed_image_boxes_do_not_claim_reviewed_status(
    client: TestClient,
) -> None:
    project = create_project(client, "Review gate")
    image_id = import_one(client, project["id"])["successful"][0]["image_id"]

    save = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "annotated",
            "annotations": [
                {
                    "id": str(uuid4()),
                    "label_class_id": project["label_classes"][0]["id"],
                    "x_min": 5,
                    "y_min": 5,
                    "x_max": 15,
                    "y_max": 15,
                }
            ],
        },
    )
    assert save.status_code == 200, save.text

    data = client.get(_url(project["id"], image_id)).json()

    reviewed = next(layer for layer in data["layers"] if layer["kind"] == "reviewed_boxes")
    assert reviewed["object_count"] == 0
    assert data["annotation_status"] == "annotated"
