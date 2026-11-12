from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from reefvision.jobs.pose_identity_tracking import process_pose_identity_tracking_job
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_pose_identity_tracking_api import (
    SCHEMA_HASH,
    SCHEMA_ID,
    _first_class,
    _submit,
    _track,
    _video,
)


def test_verified_truth_evaluation_is_immutable_and_provenance_complete(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "Pose identity evaluation")
    video = _video(client, str(project["id"]), monkeypatch, "evaluation")
    track = _track(client, str(video["id"]), _first_class(project), offset=10, prefix="truth")
    job = _submit(client, str(project["id"]), str(video["id"]), [str(track["id"])])
    run_id = str(job["result_json"]["run_id"])
    assert process_pose_identity_tracking_job(
        client.app.state.settings, client.app.state.session_factory, str(job["id"])
    )

    truth = client.post(
        f"/api/v1/projects/{project['id']}/pose-identity-truth-datasets",
        json={
            "name": "Synthetic perfect identity truth",
            "video_id": video["id"],
            "pose_schema_id": SCHEMA_ID,
            "pose_schema_revision": 1,
            "pose_schema_content_hash": SCHEMA_HASH,
            "scientific_context": "synthetic_engineering",
            "verified_by": "fixture-author",
            "observations": [
                {
                    "identity_id": "truth-fish",
                    "frame_index": frame,
                    "bbox": [10 + frame * 4, 20, 30, 15],
                }
                for frame in (0, 1, 2)
            ],
        },
    )
    assert truth.status_code == 201, truth.text
    truth_payload = truth.json()
    assert truth_payload["verification_state"] == "scientist_verified"
    assert len(truth_payload["manifest_sha256"]) == 64

    evaluation = client.post(
        f"/api/v1/pose-identity-runs/{run_id}/evaluations",
        json={"truth_dataset_id": truth_payload["id"], "spatial_iou_threshold": 0.5},
    )
    assert evaluation.status_code == 201, evaluation.text
    report = evaluation.json()
    assert report["metrics_json"]["id_f1"] == 1.0
    assert report["metrics_json"]["identity_switches"] == 0
    assert report["provenance_json"]["truth_manifest_sha256"] == truth_payload["manifest_sha256"]
    assert report["provenance_json"]["association_run_revision"] == 1
    assert any("localization" in warning.lower() for warning in report["warnings_json"])
    assert any("synthetic" in warning.lower() for warning in report["warnings_json"])

    loaded = client.get(f"/api/v1/pose-identity-evaluations/{report['id']}")
    assert loaded.status_code == 200
    assert loaded.json()["result_sha256"] == report["result_sha256"]


def test_truth_creation_rejects_unverified_or_schema_incompatible_data(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "Pose identity truth validation")
    video = _video(client, str(project["id"]), monkeypatch, "truth-validation")
    base = {
        "name": "Invalid truth",
        "video_id": video["id"],
        "pose_schema_id": SCHEMA_ID,
        "pose_schema_revision": 1,
        "pose_schema_content_hash": SCHEMA_HASH,
        "scientific_context": "synthetic_engineering",
        "verified_by": "fixture-author",
        "observations": [{"identity_id": "fish", "frame_index": 0, "bbox": [0, 0, 10, 10]}],
    }
    unverified = client.post(
        f"/api/v1/projects/{project['id']}/pose-identity-truth-datasets",
        json={**base, "verification_state": "model_generated"},
    )
    assert unverified.status_code == 422

    out_of_bounds = client.post(
        f"/api/v1/projects/{project['id']}/pose-identity-truth-datasets",
        json={
            **base,
            "observations": [{"identity_id": "fish", "frame_index": 99, "bbox": [0, 0, 10, 10]}],
        },
    )
    assert out_of_bounds.status_code == 400
    assert "frame" in out_of_bounds.json()["detail"].lower()
