from __future__ import annotations

import io
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.db.models import ModelRegistration, WorkflowArtifact
from reefvision.services import video_assets as video_assets_module
from reefvision.services.workflow_depth_3d import execute_video_depth_3d_adapter
from reefvision.tests.test_annotations import create_project


def _fake_metadata(_path: object) -> dict[str, float | int]:
    return {
        "width_px": 200,
        "height_px": 100,
        "frame_count": 5,
        "fps": 10.0,
        "duration_seconds": 0.5,
    }


def _import_video(
    client: TestClient,
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_metadata)
    response = client.post(
        f"/api/v1/projects/{project_id}/imports/videos",
        files={"file": ("fish.mp4", io.BytesIO(b"video"), "video/mp4")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_track(
    client: TestClient,
    video_id: str,
    label_class_id: str,
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/videos/{video_id}/tracks",
        json={
            "label_class_id": label_class_id,
            "keyframes": [
                {"frame": 0, "bbox": [0, 0, 10, 10]},
                {"frame": 2, "bbox": [20, 0, 10, 10]},
            ],
            "interpolation": "linear",
            "status": "verified",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _register_detector(client: TestClient, project: dict[str, Any]) -> str:
    app = cast(FastAPI, client.app)
    label_class_id = str(project["label_classes"][0]["id"])
    with app.state.session_factory() as session:
        model = ModelRegistration(
            project_id=str(project["id"]),
            purpose="detector",
            display_name="Workflow fish detector",
            source_filename="fish.pt",
            managed_path=f"{project['storage_root']}/models/fish.pt",
            sha256="d" * 64,
            file_size_bytes=123,
            framework="ultralytics",
            task="detect",
            provider_name="ultralytics",
            provider_version="test",
            class_map_json={"mapping": {"fish": label_class_id}},
            input_size_json={"width": 640, "height": 640},
            metadata_json={},
        )
        session.add(model)
        session.commit()
        session.refresh(model)
        return model.id


def test_metric_depth_3d_node_is_discoverable_and_typed_in_workflow_graph(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "3D workflow graph")
    video = _import_video(client, str(project["id"]), monkeypatch)
    model_id = _register_detector(client, project)

    registry = client.get("/api/v1/workflow-graphs/node-registry")
    assert registry.status_code == 200, registry.text
    node = next(
        item
        for item in registry.json()
        if item["node_type"] == "video_depth_3d_analytics"
    )
    assert node["executable"] is True
    assert node["input_ports"][0]["accepted_types"] == ["video_reference"]
    assert node["input_ports"][1]["accepted_types"] == ["video_tracks"]
    assert node["output_ports"][0]["accepted_types"] == [
        "video_3d_trajectories"
    ]
    assert "depth_samples" in node["required_parameters"]

    graph = {
        "graph_id": "fish-3d-workflow",
        "name": "Fish tracking to metric 3D trajectories",
        "nodes": [
            {"node_id": "project", "node_type": "project_source", "parameters": {}},
            {
                "node_id": "video",
                "node_type": "project_video_source",
                "parameters": {"video_id": video["id"]},
            },
            {
                "node_id": "model",
                "node_type": "registered_model_source",
                "parameters": {"model_id": model_id},
            },
            {
                "node_id": "tracking",
                "node_type": "video_tracking",
                "parameters": {"tracker": "bytetrack.yaml"},
            },
            {
                "node_id": "depth3d",
                "node_type": "video_depth_3d_analytics",
                "parameters": {
                    "unit": "m",
                    "depth_samples": [
                        {"track_number": 1, "frame": 0, "depth": 2.0},
                        {"track_number": 1, "frame": 2, "depth": 2.0},
                    ],
                },
            },
        ],
        "edges": [
            {
                "edge_id": "project-video",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "video",
                "target_port_id": "project",
            },
            {
                "edge_id": "project-model",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "model",
                "target_port_id": "project",
            },
            {
                "edge_id": "video-tracking",
                "source_node_id": "video",
                "source_port_id": "video",
                "target_node_id": "tracking",
                "target_port_id": "video",
            },
            {
                "edge_id": "model-tracking",
                "source_node_id": "model",
                "source_port_id": "model",
                "target_node_id": "tracking",
                "target_port_id": "model",
            },
            {
                "edge_id": "video-depth3d",
                "source_node_id": "video",
                "source_port_id": "video",
                "target_node_id": "depth3d",
                "target_port_id": "video",
            },
            {
                "edge_id": "tracks-depth3d",
                "source_node_id": "tracking",
                "source_port_id": "tracks",
                "target_node_id": "depth3d",
                "target_port_id": "tracks",
            },
        ],
    }
    validation = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs/validate",
        json=graph,
    )
    assert validation.status_code == 200, validation.text
    assert validation.json()["valid"] is True, validation.json()["issues"]
    assert validation.json()["topological_order"][-1] == "depth3d"

    plan = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs/plan",
        json=graph,
    )
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] is True
    assert plan.json()["executable"] is True
    depth_step = next(
        item for item in plan.json()["steps"] if item["node_id"] == "depth3d"
    )
    assert depth_step["executable"] is True
    assert depth_step["output_types"]["trajectories"] == [
        "video_3d_trajectories"
    ]


def test_metric_depth_3d_adapter_executes_existing_video_science_geometry(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    test_settings: Settings,
) -> None:
    project = create_project(client, "3D workflow execution")
    video = _import_video(client, str(project["id"]), monkeypatch)
    label_class_id = str(project["label_classes"][0]["id"])
    track = _create_track(client, str(video["id"]), label_class_id)

    intrinsics = client.put(
        f"/api/v1/videos/{video['id']}/camera-intrinsics",
        json={
            "fx_px": 100,
            "fy_px": 100,
            "cx_px": 5,
            "cy_px": 5,
            "method": "checkerboard",
        },
    )
    assert intrinsics.status_code == 200, intrinsics.text

    app = cast(FastAPI, client.app)
    video_artifact = cast(
        WorkflowArtifact,
        SimpleNamespace(payload_json={"video_id": video["id"]}),
    )
    tracks_artifact = cast(
        WorkflowArtifact,
        SimpleNamespace(
            payload_json={
                "video_id": video["id"],
                "tracks": [
                    {
                        "id": track["id"],
                        "track_number": track["track_number"],
                    }
                ],
            }
        ),
    )
    with app.state.session_factory() as session:
        outputs = execute_video_depth_3d_adapter(
            session,
            test_settings,
            str(project["id"]),
            {
                "unit": "m",
                "depth_samples": [
                    {
                        "track_number": track["track_number"],
                        "frame": 0,
                        "depth": 2.0,
                        "confidence": 0.99,
                    },
                    {
                        "track_number": track["track_number"],
                        "frame": 2,
                        "depth": 2.0,
                        "confidence": 0.98,
                    },
                ],
            },
            {"video": [video_artifact], "tracks": [tracks_artifact]},
        )

    assert len(outputs) == 1
    output = outputs[0]
    assert output["port_id"] == "trajectories"
    assert output["data_type"] == "video_3d_trajectories"
    payload = output["payload_json"]
    analytics = payload["tracks"][0]
    assert analytics["path_length_3d"] == pytest.approx(0.4)
    assert analytics["displacement_3d"] == pytest.approx(0.4)
    assert analytics["mean_speed_3d_per_second"] == pytest.approx(2.0)
    assert payload["workflow_provenance"]["metric_depth_sample_count"] == 2
    assert payload["workflow_provenance"]["relative_monocular_depth_is_metric"] is False


def test_metric_depth_3d_adapter_rejects_depth_for_track_outside_input_artifact(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    test_settings: Settings,
) -> None:
    project = create_project(client, "3D workflow track scope")
    video = _import_video(client, str(project["id"]), monkeypatch)
    label_class_id = str(project["label_classes"][0]["id"])
    track = _create_track(client, str(video["id"]), label_class_id)
    intrinsics = client.put(
        f"/api/v1/videos/{video['id']}/camera-intrinsics",
        json={"fx_px": 100, "fy_px": 100, "cx_px": 5, "cy_px": 5},
    )
    assert intrinsics.status_code == 200

    app = cast(FastAPI, client.app)
    video_artifact = cast(
        WorkflowArtifact,
        SimpleNamespace(payload_json={"video_id": video["id"]}),
    )
    tracks_artifact = cast(
        WorkflowArtifact,
        SimpleNamespace(
            payload_json={
                "tracks": [
                    {
                        "id": track["id"],
                        "track_number": track["track_number"],
                    }
                ]
            }
        ),
    )
    with app.state.session_factory() as session:
        with pytest.raises(ValidationError, match="incoming video_tracks"):
            execute_video_depth_3d_adapter(
                session,
                test_settings,
                str(project["id"]),
                {
                    "unit": "m",
                    "depth_samples": [
                        {"track_number": 999, "frame": 0, "depth": 2.0},
                        {"track_number": 999, "frame": 2, "depth": 2.0},
                    ],
                },
                {"video": [video_artifact], "tracks": [tracks_artifact]},
            )
