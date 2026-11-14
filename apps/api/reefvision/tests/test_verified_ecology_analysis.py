from __future__ import annotations

from io import BytesIO
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from reefvision.db.models.ecology_analysis import EcologyAnalysisRecord
from reefvision.services.ecology_analysis import EcologyAnalysisService
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_ecology_annotation_evidence_1_2 import _annotation_link
from reefvision.tests.test_ecology_calibration_evidence_1_2 import (
    _link_calibration,
    _save_calibration,
)
from reefvision.tests.test_ecology_image_evidence_1_2 import _link, _register
from reefvision.tests.test_workflow_connected_branch_preview_1_2 import _run


def test_abundance_pins_reviewed_counts_separates_density_and_detects_staleness(
    client: TestClient,
) -> None:
    project = create_project(client)
    project_id = project["id"]
    image_id = import_one(client, project_id)["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]
    path = f"/api/v1/images/{image_id}/annotations"
    first_save = client.put(
        path, json={"base_revision": 0, "annotation_status": "reviewed", "annotations": []}
    )
    assert first_save.status_code == 200, first_save.text
    endpoint = f"/api/v1/projects/{project_id}/ecology/verified-analyses"
    selection: dict[str, object] = {
        "kind": "abundance",
        "class_id": class_id,
        "sources": [
            {
                "image_id": image_id,
                "sample_id": "quadrat-1",
                "experimental_unit_type": "site",
                "experimental_unit_id": "site-1",
                "observed_at": "2026-11-01T12:00:00Z",
                "surveyed_area_m2": 0.25,
            }
        ],
    }
    selected_sources = cast(list[dict[str, object]], selection["sources"])
    payload = {
        "selection": selection,
        "reviewed_by": "Researcher",
        "review_note": "Confirmed annotation completeness and surveyed quadrat area.",
        "confirm_reviewed_selection": True,
    }
    verified = client.post(endpoint, json=payload)
    assert verified.status_code == 201, verified.text
    analysis = verified.json()
    assert analysis["stale"] is False
    row = analysis["snapshot"]["result"]["visits"][0]
    assert row["count"] == 0
    assert row["density_per_m2"] == 0
    assert client.get(f"{endpoint}/{analysis['id']}/results.csv").status_code == 200
    assert client.get(f"{endpoint}/{analysis['id']}/result.json").json() == analysis["snapshot"]
    missing = {
        "sample_id": "quadrat-2",
        "experimental_unit_type": "site",
        "experimental_unit_id": "site-1",
        "observed_at": "2026-11-01T12:00:00Z",
        "exclusion_reason": "Sample obscured in this visit",
    }
    with_missing = client.post(
        endpoint,
        json={**payload, "selection": {**selection, "sources": [*selected_sources, missing]}},
    )
    assert with_missing.status_code == 201, with_missing.text
    partial = with_missing.json()["snapshot"]["result"]["unit_summaries"][0]
    assert partial["excluded_sample_count"] == 1
    assert partial["density_per_m2"] is None

    duplicate = client.post(
        endpoint,
        json={**payload, "selection": {**selection, "sources": selected_sources * 2}},
    )
    assert duplicate.status_code == 400, duplicate.text
    assert "Duplicate survey sample" in duplicate.json()["detail"]

    changed = client.put(
        path,
        json={
            "base_revision": first_save.json()["image"]["annotation_revision"],
            "annotation_status": "reviewed",
            "annotations": [
                {
                    "id": str(uuid4()),
                    "label_class_id": class_id,
                    "x_min": 1,
                    "y_min": 1,
                    "x_max": 4,
                    "y_max": 5,
                }
            ],
        },
    )
    assert changed.status_code == 200, changed.text
    historical = client.get(f"{endpoint}/{analysis['id']}").json()
    assert historical["stale"] is True
    assert historical["snapshot"] == analysis["snapshot"]
    recalculated = client.post(endpoint, json={**payload, "supersedes_id": analysis["id"]})
    assert recalculated.status_code == 201, recalculated.text
    fresh_row = recalculated.json()["snapshot"]["result"]["visits"][0]
    assert fresh_row["count"] == 1
    assert fresh_row["density_per_m2"] == 4

    replacement_project = create_project(client, "Imported study")
    replacement_project_id = replacement_project["id"]
    replacement_class = replacement_project["label_classes"][0]["id"]
    replacement_image = import_one(client, replacement_project_id)["successful"][0]["image_id"]
    replacement_saved = client.put(
        f"/api/v1/images/{replacement_image}/annotations",
        json={"base_revision": 0, "annotation_status": "reviewed", "annotations": []},
    )
    assert replacement_saved.status_code == 200, replacement_saved.text
    snapshot = analysis["snapshot"]
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        row = EcologyAnalysisRecord(
            project_id=replacement_project_id,
            kind="abundance",
            snapshot_json=snapshot,
            source_id_map_json={class_id: replacement_class, image_id: replacement_image},
            content_sha256=canonical_json_sha256(snapshot),
        )
        session.add(row)
        session.commit()
        recreated = EcologyAnalysisService(session).get(replacement_project_id, row.id)
        assert recreated.stale is False
        assert recreated.snapshot.model_dump(mode="json") == snapshot


def test_abundance_rejects_foreign_images_and_unreviewed_selection(client: TestClient) -> None:
    project = create_project(client, "Study")
    foreign = create_project(client, "Other")
    foreign_id = import_one(client, foreign["id"])["successful"][0]["image_id"]
    endpoint = f"/api/v1/projects/{project['id']}/ecology/verified-analyses"
    payload = {
        "selection": {
            "kind": "abundance",
            "class_id": project["label_classes"][0]["id"],
            "sources": [
                {
                    "image_id": foreign_id,
                    "sample_id": "quadrat-1",
                    "experimental_unit_type": "site",
                    "experimental_unit_id": "site-1",
                    "observed_at": "2026-11-01T12:00:00Z",
                }
            ],
        },
        "reviewed_by": "Reviewer",
        "review_note": "Complete surveyed quadrat.",
        "confirm_reviewed_selection": True,
    }
    assert client.post(endpoint, json=payload).status_code == 400
    assert (
        client.post(endpoint, json={**payload, "confirm_reviewed_selection": False}).status_code
        == 422
    )


@pytest.mark.parametrize("perspective", [False, True])
def test_verified_growth_replays_through_saved_workflow_with_elapsed_utc_time(
    client: TestClient,
    perspective: bool,
) -> None:
    project = create_project(client, "Repeated coral photographs")
    project_id = str(project["id"])
    label_id = project["label_classes"][0]["id"]
    _register(client, project_id, "colony-a")
    sources = []
    for day, width in ((1, 20), (3, 28)):
        exif = Image.Exif()
        exif[36867] = f"2026:11:{day:02d} 12:00:00"
        exif[36881] = "-04:00"
        fixture = BytesIO()
        Image.new("RGB", (80, 60), color=(day, 0, 0)).save(fixture, format="JPEG", exif=exif)
        imported = client.post(
            f"/api/v1/projects/{project_id}/imports/images",
            files={"files": (f"visit-{day}.jpg", fixture.getvalue(), "image/jpeg")},
        )
        assert imported.status_code == 200, imported.text
        image_id = imported.json()["successful"][0]["image_id"]
        link = _link(client, project_id, "colony-a", image_id)
        assert link.status_code == 201, link.text
        annotation_id = str(uuid4())
        annotated = client.put(
            f"/api/v1/images/{image_id}/annotations",
            json={
                "base_revision": 0,
                "annotation_status": "reviewed",
                "annotations": [
                    {
                        "id": annotation_id,
                        "label_class_id": label_id,
                        "x_min": 5,
                        "x_max": 5 + width,
                        "y_min": 8,
                        "y_max": 20,
                    }
                ],
            },
        )
        assert annotated.status_code == 200, annotated.text
        annotation_link = _annotation_link(
            client, project_id, link.json()["id"], "box", annotation_id
        )
        assert annotation_link.status_code == 201, annotation_link.text
        if perspective:
            calibrated = client.put(
                f"/api/v1/images/{image_id}/measurement-calibration",
                json={
                    "distance_per_pixel": 0.25,
                    "unit": "mm",
                    "source": "reference-plane",
                    "perspective_homography": [[0.5, 0, 0], [0, 0.2, 0], [0, 0, 1]],
                },
            )
            assert calibrated.status_code == 200, calibrated.text
        else:
            _save_calibration(client, image_id)
        calibration = _link_calibration(client, project_id, annotation_link.json())
        assert calibration.status_code == 201, calibration.text
        sources.append({"calibration_evidence_id": calibration.json()["id"]})
    path = f"/api/v1/projects/{project_id}/ecology/verified-analyses"
    response = client.post(
        path,
        json={
            "selection": {"kind": "growth", "metric": "box_width", "sources": sources},
            "reviewed_by": "Scientist",
            "review_note": "Confirmed same colony, view and physical scale.",
            "confirm_reviewed_selection": True,
        },
    )
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["snapshot"]["evidence_level"] == "scientist_confirmed_project_evidence"
    result = saved["snapshot"]["result"]
    assert len(result["observations"]) == 2
    assert result["changes"][0]["absolute_change"] == pytest.approx(4 if perspective else 2)
    assert result["changes"][0]["change_per_day"] == pytest.approx(2 if perspective else 1)
    assert result["observations"][0]["measurement_method"] == (
        "reference_plane_homography" if perspective else "scalar_image_plane"
    )
    graph = {
        "graph_id": "reviewed-growth",
        "name": "Reviewed growth",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "reviewed",
                "node_type": "ecology_verified_analysis",
                "parameters": {"analysis_id": saved["id"]},
            },
        ],
        "edges": [
            {
                "edge_id": "project-reviewed",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "reviewed",
                "target_port_id": "project",
            }
        ],
    }
    workflow = _run(client, project_id, graph)
    assert workflow["run"]["status"] == "succeeded", workflow
    assert (
        next(
            row["payload_json"]
            for row in workflow["artifacts"]
            if row["data_type"] == "verified_ecology_analysis"
        )
        == saved
    )
