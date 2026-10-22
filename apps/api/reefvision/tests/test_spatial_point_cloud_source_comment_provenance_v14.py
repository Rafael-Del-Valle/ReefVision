"""PLY comment provenance is not point-cloud geometric identity."""

from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project

PLY = (
    "ply\nformat ascii 1.0\nelement vertex 2\n"
    "property float x\nproperty float y\nproperty float z\n"
    "end_header\n0 0 0\n1 2 3\n"
)
COMMENTED_PLY = PLY.replace("end_header", "comment field survey A\nend_header")


def test_comments_change_source_evidence_not_geometry_or_verification(
    client: TestClient,
) -> None:
    project_id = str(create_project(client, "PLY comment provenance")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        "ply_text": PLY,
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified reference",
        "relative_scale_uncertainty": 0.1,
        "point_index_pairs": [[0, 1]],
    }
    plain_response = client.post(f"{base}/spatial/point-cloud-preview", json=params)
    commented_response = client.post(
        f"{base}/spatial/point-cloud-preview",
        json={**params, "ply_text": COMMENTED_PLY},
    )
    assert plain_response.status_code == 200, plain_response.text
    assert commented_response.status_code == 200, commented_response.text
    plain = plain_response.json()
    commented = commented_response.json()
    assert plain["axis_aligned_dimensions_m"] == commented["axis_aligned_dimensions_m"]
    assert plain["provenance"]["geometry_sha256"] == commented["provenance"]["geometry_sha256"]
    assert (
        plain["provenance"]["ordered_geometry_sha256"]
        == commented["provenance"]["ordered_geometry_sha256"]
    )
    assert plain["provenance"]["source_text_sha256"] == hashlib.sha256(PLY.encode()).hexdigest()
    assert (
        commented["provenance"]["source_text_sha256"]
        == hashlib.sha256(COMMENTED_PLY.encode()).hexdigest()
    )
    assert (
        plain["provenance"]["source_text_sha256"] != commented["provenance"]["source_text_sha256"]
    )
    assert (
        plain["selected_point_chords"][0]["endpoint_ordered_geometry_sha256"]
        == commented["selected_point_chords"][0]["endpoint_ordered_geometry_sha256"]
    )
    assert commented["provenance"]["calibration_verified"] is False
    assert commented["surface_area_m2"] is None
    assert commented["branch_length_m"] is None

    graph = {
        "graph_id": "point-cloud-source-comment-v14",
        "name": "PLY source comment provenance",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "cloud",
                "node_type": "point_cloud_preview",
                "parameters": {**params, "ply_text": COMMENTED_PLY},
            },
        ],
        "edges": [
            {
                "edge_id": "project-cloud",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "cloud",
                "target_port_id": "project",
            }
        ],
    }
    planned = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert planned.status_code == 200, planned.text
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = client.app
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifact = next(
        a for a in detail.json()["artifacts"] if a["data_type"] == "point_cloud_measurement_preview"
    )
    assert artifact["payload_json"]["provenance"] == commented["provenance"]
    assert artifact["payload_json"]["selected_point_chords"] == commented["selected_point_chords"]
    assert (
        artifact["payload_json"]["axis_aligned_dimensions_m"]
        == commented["axis_aligned_dimensions_m"]
    )
    assert artifact["payload_json"]["surface_area_m2"] is None
    assert artifact["payload_json"]["branch_length_m"] is None
    assert artifact["payload_json"]["measurement_status"] == "caller_supplied_unverified"
    assert artifact["payload_json"]["project_id"] == project_id

    # Re-running the same saved graph must reproduce the scientific payload
    # and its content digest, not silently promote calibration verification.
    repeated = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert repeated.status_code == 202, repeated.text
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(repeated.json()["job_id"])
    )
    replay = client.get(f"/api/v1/workflow-runs/{repeated.json()['id']}")
    assert replay.status_code == 200, replay.text
    assert replay.json()["run"]["status"] == "succeeded"
    replay_artifact = next(
        a for a in replay.json()["artifacts"] if a["data_type"] == "point_cloud_measurement_preview"
    )
    assert replay_artifact["payload_sha256"] == artifact["payload_sha256"]
    assert replay_artifact["payload_json"] == artifact["payload_json"]
    assert replay_artifact["payload_json"]["provenance"]["calibration_verified"] is False
