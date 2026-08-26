from __future__ import annotations

import io
from types import SimpleNamespace
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import Job, WorkflowArtifact
from reefvision.services import video_assets as video_assets_module
from reefvision.services import workflow_metric_depth_3d as adapter
from reefvision.services.workflow_node_registry_v1 import workflow_node_registry
from reefvision.tests.test_annotations import create_project


def _fake_metadata(_path: object) -> dict[str, float | int]:
    return {
        "width_px": 100,
        "height_px": 60,
        "frame_count": 3,
        "fps": 10.0,
        "duration_seconds": 0.3,
    }


def test_automatic_scientific_3d_node_is_registered() -> None:
    node = workflow_node_registry()["video_metric_depth_3d"]
    assert node.executable is True
    assert node.input_ports[0].accepted_types == ["video_reference"]
    assert node.input_ports[1].accepted_types == ["video_tracks"]
    assert node.output_ports[0].accepted_types == ["video_3d_trajectories"]
    assert node.required_parameters == []


def test_automatic_scientific_3d_workflow_adapter_runs_child_job(
    client: TestClient,
    monkeypatch,
) -> None:
    project = create_project(client, "Automatic Scientific 3D workflow")
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    video_response = client.post(
        f"/api/v1/projects/{project['id']}/imports/videos",
        files={"file": ("fish.mp4", io.BytesIO(b"fake-video"), "video/mp4")},
    )
    assert video_response.status_code == 201, video_response.text
    video = video_response.json()
    label_class_id = str(project["label_classes"][0]["id"])
    track_response = client.post(
        f"/api/v1/videos/{video['id']}/tracks",
        json={
            "label_class_id": label_class_id,
            "keyframes": [
                {"frame": 0, "bbox": [10, 10, 20, 10]},
                {"frame": 2, "bbox": [30, 10, 20, 10]},
            ],
            "interpolation": "linear",
            "status": "verified",
        },
    )
    assert track_response.status_code == 201, track_response.text
    track = track_response.json()

    def fake_processor(settings, factory, job_id: str) -> bool:
        del settings
        with factory() as session:
            job = session.get(Job, job_id)
            assert job is not None
            job.status = "succeeded"
            job.progress_current = job.progress_total
            job.result_json = {
                "schema_version": "video-metric-depth-3d-job-0001",
                "stage": "complete",
                "video_id": video["id"],
                "depth_tier": "model_estimated_metric",
                "physical_measurement_claim_allowed": False,
                "analytics": {"tracks": []},
                "group_3d_frames": [],
                "warnings": [],
            }
            session.commit()
        return True

    monkeypatch.setattr(adapter, "process_video_metric_depth_job", fake_processor)
    app = cast(FastAPI, client.app)
    video_artifact = cast(
        WorkflowArtifact,
        SimpleNamespace(
            payload_json={
                "project_id": project["id"],
                "video_id": video["id"],
            }
        ),
    )
    track_artifact = cast(
        WorkflowArtifact,
        SimpleNamespace(
            payload_json={
                "project_id": project["id"],
                "video_id": video["id"],
                "track_ids": [track["id"]],
                "tracks": [
                    {
                        "track_id": track["id"],
                        "track_number": track["track_number"],
                    }
                ],
            }
        ),
    )

    with app.state.session_factory() as session:
        outputs = adapter.execute_video_metric_depth_3d_adapter(
            session,
            app.state.settings,
            str(project["id"]),
            {"device": "cpu", "input_size": 392},
            {"video": [video_artifact], "tracks": [track_artifact]},
        )

    assert outputs[0]["data_type"] == "video_3d_trajectories"
    payload = outputs[0]["payload_json"]
    assert payload["depth_tier"] == "model_estimated_metric"
    assert payload["physical_measurement_claim_allowed"] is False
    assert payload["workflow_provenance"]["source_track_ids"] == [track["id"]]
    assert payload["workflow_provenance"]["automatic_model_download_allowed"] is False
