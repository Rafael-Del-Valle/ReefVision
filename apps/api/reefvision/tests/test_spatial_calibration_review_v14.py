"""Durable 1.4 review receipts preserve provenance without promoting scientific claims."""

from __future__ import annotations

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import SpatialCalibrationReviewRecord
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_spatial_point_cloud_assets_v14 import PLY
from reefvision.tests.test_spatial_point_cloud_source_binding_v14 import _run_saved_cloud

OBJ = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"


def test_calibration_receipt_replays_standalone_and_persisted_workflow(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Durable spatial review")["id"])
    base = f"/api/v1/projects/{project_id}"
    imported = client.post(f"{base}/spatial/assets", files={"file": ("colony.obj", OBJ)})
    assert imported.status_code == 201, imported.text
    asset = imported.json()
    params = {
        "asset_id": asset["id"],
        "expected_source_payload_sha256": asset["sha256"],
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Field scale bar not independently verified",
        "relative_scale_uncertainty": 0.05,
        "specimen_id": "colony-16",
        "observation_id": "survey-1",
        "observed_at_utc": "2026-10-01T12:00:00Z",
        "coordinate_frame_id": "local-survey-A",
    }
    baseline = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert baseline.status_code == 200, baseline.text
    evidence = {
        "calibration_operator_id": "operator-1",
        "independent_reviewer_id": "reviewer-2",
        "independent_review_decision": "inconclusive",
        "independent_review_note": "Survey ruler still requires field verification",
        "reviewed_at_utc": "2026-10-02T12:00:00Z",
        "reviewed_geometry_sha256": baseline.json()["provenance"]["geometry_sha256"],
        "reviewed_source_payload_sha256": asset["sha256"],
        "reviewed_spatial_source_asset_id": asset["id"],
        "reviewed_coordinate_frame_id": params["coordinate_frame_id"],
        "reviewed_specimen_id": params["specimen_id"],
        "reviewed_observation_id": params["observation_id"],
        "reviewed_observed_at_utc": params["observed_at_utc"],
        "reviewed_meters_per_unit": 0.01,
        "reviewed_calibration_method": params["calibration_method"],
        "reviewed_calibration_evidence": params["calibration_evidence"],
        "reviewed_relative_scale_uncertainty": 0.05,
    }
    reviews_url = f"{base}/spatial/assets/{asset['id']}/calibration-reviews"
    created = client.post(reviews_url, json={"evidence": evidence})
    assert created.status_code == 201, created.text
    receipt = created.json()
    assert receipt["review_status"] == "attributed_unverified"
    assert receipt["reviewer_authenticated"] is False
    assert receipt["calibration_verified"] is False
    assert receipt["specimen_identity_verified"] is False
    assert receipt["source_integrity_checked"] is True
    assert receipt["evidence_sha256"] != asset["sha256"]
    repeated = client.post(reviews_url, json={"evidence": evidence})
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["id"] == receipt["id"]
    assert client.get(reviews_url).json() == [receipt]
    fetched = client.get(f"{reviews_url}/{receipt['id']}")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json() == receipt

    # Every revision remains addressable; paging must not silently hide older
    # scientific review receipts or change their chronological ordering.
    for note in ("Second provisional assessment", "Third provisional assessment"):
        revised = client.post(
            reviews_url,
            json={"evidence": {**evidence, "independent_review_note": note}},
        )
        assert revised.status_code == 201, revised.text
    all_reviews = client.get(reviews_url)
    assert all_reviews.status_code == 200, all_reviews.text
    reviews = all_reviews.json()
    assert len(reviews) == 3
    first_page = client.get(reviews_url, params={"limit": 2, "offset": 0})
    last_page = client.get(reviews_url, params={"limit": 2, "offset": 2})
    assert first_page.json() == reviews[:2]
    assert last_page.json() == reviews[2:]
    assert client.get(reviews_url, params={"offset": 3}).json() == []
    cursor_page = client.get(
        reviews_url, params={"limit": 2, "after_review_id": reviews[0]["id"]}
    )
    assert cursor_page.status_code == 200, cursor_page.text
    assert cursor_page.json() == reviews[1:]
    assert client.get(
        reviews_url, params={"after_review_id": reviews[-1]["id"]}
    ).json() == []
    assert client.get(
        reviews_url, params={"after_review_id": "missing-review"}
    ).status_code == 404
    assert client.get(
        reviews_url, params={"after_review_id": reviews[0]["id"], "offset": 1}
    ).status_code == 400
    for invalid in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        assert client.get(reviews_url, params=invalid).status_code == 422

    # A saved review is evidence, not an authentication or verification token.
    # The same evidence must pass the existing geometry/scale binding checks
    # in both the standalone API and the executable persisted typed graph.
    inline = client.post(
        f"{base}/spatial/mesh-preview",
        json={**params, "calibration_review": fetched.json()["evidence"]},
    )
    assert inline.status_code == 200, inline.text
    params["calibration_review_id"] = receipt["id"]
    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["provenance"]["calibration_verified"] is False
    assert expected["provenance"]["specimen_identity_verified"] is False
    assert expected["provenance"]["calibration_review_record_id"] == receipt["id"]
    evidence_digest = expected["provenance"]["calibration_review_evidence_sha256"]
    assert evidence_digest == receipt["evidence_sha256"]
    assert "persisted_calibration_review_unverified" in expected["qc_warnings"]
    assert expected["surface_area_m2"] == inline.json()["surface_area_m2"]
    assert (
        client.post(
            f"{base}/spatial/mesh-preview",
            json={**params, "calibration_review": receipt["evidence"]},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{base}/spatial/mesh-preview",
            json={**params, "asset_id": None, "vertices": [[0, 0, 0]], "faces": [[0, 0, 0]]},
        ).status_code
        == 422
    )
    graph = {
        "graph_id": "durable-review-replay-v14",
        "name": "Review receipt with project-owned source",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "mesh", "node_type": "mesh_surface_preview", "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "project-mesh",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "mesh",
                "target_port_id": "project",
            }
        ],
    }
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifacts = [
        item["payload_json"]
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    ]
    assert artifacts == [expected]

    # A later, cursor-discovered revision must also replay through the same
    # standalone measurement engine and an independently persisted typed graph.
    later_params = {**params, "calibration_review_id": reviews[-1]["id"]}
    later = client.post(f"{base}/spatial/mesh-preview", json=later_params)
    assert later.status_code == 200, later.text
    assert later.json()["provenance"]["calibration_verified"] is False
    assert later.json()["provenance"]["calibration_review_record_id"] == reviews[-1]["id"]
    graph["graph_id"] = "durable-review-cursor-replay-v14"
    graph["nodes"][1]["parameters"] = later_params
    saved_later = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved_later.status_code == 201, saved_later.text
    run_later = client.post(
        f"{base}/workflow-runs", json={"graph_record_id": saved_later.json()["id"]}
    )
    assert run_later.status_code == 202, run_later.text
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run_later.json()["job_id"])
    )
    detail_later = client.get(f"/api/v1/workflow-runs/{run_later.json()['id']}")
    assert detail_later.status_code == 200, detail_later.text
    assert detail_later.json()["run"]["status"] == "succeeded"
    assert [
        item["payload_json"]
        for item in detail_later.json()["artifacts"]
        if item["data_type"] == "mesh_measurement_preview"
    ] == [later.json()]


def test_calibration_receipts_fail_closed_on_cross_project_and_tampering(
    client: TestClient,
) -> None:
    first = str(create_project(client, "First spatial review project")["id"])
    second = str(create_project(client, "Second spatial review project")["id"])
    imported = client.post(
        f"/api/v1/projects/{first}/spatial/assets", files={"file": ("colony.obj", OBJ)}
    )
    assert imported.status_code == 201, imported.text
    asset = imported.json()
    reviews_url = f"/api/v1/projects/{first}/spatial/assets/{asset['id']}/calibration-reviews"
    evidence = {
        "calibration_operator_id": "operator-1",
        "independent_reviewer_id": "reviewer-2",
        "independent_review_decision": "disputes_scale",
        "independent_review_note": "Scale is not supported",
        "reviewed_at_utc": "2026-10-02T12:00:00Z",
        "reviewed_geometry_sha256": "a" * 64,
        "reviewed_source_payload_sha256": asset["sha256"],
        "reviewed_spatial_source_asset_id": asset["id"],
        "reviewed_meters_per_unit": 0.01,
        "reviewed_calibration_method": "ruler",
        "reviewed_calibration_evidence": "Unverified scale",
        "reviewed_relative_scale_uncertainty": 0.05,
    }
    for altered in (
        {**evidence, "reviewed_spatial_source_asset_id": None},
        {**evidence, "reviewed_source_payload_sha256": "0" * 64},
    ):
        rejected = client.post(reviews_url, json={"evidence": altered})
        assert rejected.status_code == 400, rejected.text
    assert client.get(reviews_url).json() == []
    created = client.post(reviews_url, json={"evidence": evidence})
    assert created.status_code == 201, created.text
    review_id = created.json()["id"]
    assert (
        client.get(
            f"/api/v1/projects/{second}/spatial/assets/{asset['id']}/calibration-reviews/{review_id}"
        ).status_code
        == 404
    )

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        record = session.get(SpatialCalibrationReviewRecord, review_id)
        assert record is not None
        record.evidence_json = {**record.evidence_json, "independent_review_note": "Altered"}
        session.commit()
    tampered = client.get(f"{reviews_url}/{review_id}")
    assert tampered.status_code == 400, tampered.text
    assert "integrity validation" in tampered.text
    # A modified persisted review cannot be used as a pagination cursor.
    cursor_rejected = client.get(reviews_url, params={"after_review_id": review_id})
    assert cursor_rejected.status_code == 400, cursor_rejected.text
    assert "integrity validation" in cursor_rejected.text


def test_point_cloud_saved_calibration_receipt_replays_and_fails_closed(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "Saved point-cloud calibration receipt")["id"])
    base = f"/api/v1/projects/{project_id}"
    imported = client.post(f"{base}/spatial/assets", files={"file": ("cloud.ply", PLY)})
    assert imported.status_code == 201, imported.text
    asset = imported.json()
    params = {
        "asset_id": asset["id"],
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified ruler on PLY survey",
        "relative_scale_uncertainty": 0.05,
        "expected_source_payload_sha256": asset["sha256"],
    }
    baseline = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert baseline.status_code == 200, baseline.text
    evidence = {
        "calibration_operator_id": "operator-1",
        "independent_reviewer_id": "reviewer-2",
        "independent_review_decision": "inconclusive",
        "independent_review_note": "Source scale not independently verified",
        "reviewed_at_utc": "2026-10-02T12:00:00Z",
        "reviewed_geometry_sha256": baseline.json()["provenance"]["geometry_sha256"],
        "reviewed_source_payload_sha256": asset["sha256"],
        "reviewed_spatial_source_asset_id": asset["id"],
        "reviewed_meters_per_unit": params["meters_per_unit"],
        "reviewed_calibration_method": params["calibration_method"],
        "reviewed_calibration_evidence": params["calibration_evidence"],
        "reviewed_relative_scale_uncertainty": params["relative_scale_uncertainty"],
    }
    reviews_url = f"{base}/spatial/assets/{asset['id']}/calibration-reviews"
    created = client.post(reviews_url, json={"evidence": evidence})
    assert created.status_code == 201, created.text
    receipt = created.json()
    params["calibration_review_id"] = receipt["id"]
    standalone = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["provenance"]["calibration_review_record_id"] == receipt["id"]
    assert expected["provenance"]["calibration_verified"] is False
    assert "persisted_calibration_review_unverified" in expected["qc_warnings"]
    saved = _run_saved_cloud(client, project_id, params)
    assert saved["completed"] is True
    assert saved["run"]["status"] == "succeeded"
    artifacts = [
        a["payload_json"]
        for a in saved["artifacts"]
        if a["data_type"] == "point_cloud_measurement_preview"
    ]
    assert artifacts == [expected]

    # The saved receipt cannot be used with inline geometry or an unowned asset.
    rejected = client.post(
        f"{base}/spatial/point-cloud-preview",
        json={**params, "asset_id": None, "points": [[0, 0, 0]]},
    )
    assert rejected.status_code == 422
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        record = session.get(SpatialCalibrationReviewRecord, receipt["id"])
        assert record is not None
        record.evidence_json = {**record.evidence_json, "independent_review_note": "Altered"}
        session.commit()
    rejected = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    assert rejected.status_code == 400
    failed = _run_saved_cloud(client, project_id, params)
    assert failed["run"]["status"] == "failed"
    assert not any(a["data_type"] == "point_cloud_measurement_preview" for a in failed["artifacts"])
