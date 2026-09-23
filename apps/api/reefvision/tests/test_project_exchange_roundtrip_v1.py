from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.db.models import (
    ImageAsset,
    Project,
    VideoAsset,
    VideoTrack,
    WorkflowArtifact,
    WorkflowGraphRecord,
    WorkflowNodeRun,
    WorkflowRun,
)
from reefvision.jobs.project_exchange import process_project_exchange_export_job
from reefvision.main import create_app
from reefvision.services import video_assets as video_assets_module
from reefvision.services.workflow_depth_3d import execute_video_depth_3d_adapter
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_images import create_project, image_bytes, import_one


def test_project_exchange_round_trip_remaps_ids_media_artifacts_and_workflows(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project = create_project(client, "Round-trip reef project")
    configured = client.patch(
        f"/api/v1/projects/{project['id']}",
        json={
            "georeference_height_offset_m": 5.0,
            "georeference_height_evidence": "Surveyed takeoff pad is 5 m above the surface",
        },
    )
    assert configured.status_code == 200, configured.text
    project = configured.json()

    report = import_one(
        client,
        project["id"],
        filename="reef.png",
        relative_path="survey/reef.png",
    )
    image_id = str(report["successful"][0]["image_id"])

    source_project_root = test_settings.resolved_data_dir / Path(str(project["storage_root"]))
    generated_relative_path = Path("derived") / "measurements" / "metrics.csv"
    generated_path = source_project_root / generated_relative_path
    generated_path.parent.mkdir(parents=True, exist_ok=True)
    generated_payload = b"image_id,area_px\nreef,1234\n"
    generated_path.write_bytes(generated_payload)

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        graph_json = {
            "schema_version": "workflow-graph-0001",
            "nodes": [
                {
                    "id": "source-image",
                    "type": "current_project",
                    "parameters": {
                        "project_id": project["id"],
                        "selected_image_id": image_id,
                    },
                }
            ],
            "edges": [],
        }
        graph = WorkflowGraphRecord(
            project_id=str(project["id"]),
            graph_key="round-trip-graph",
            name="Round-trip graph",
            schema_version="workflow-graph-0001",
            revision=1,
            graph_json=graph_json,
            graph_sha256=canonical_json_sha256(graph_json),
        )
        session.add(graph)
        session.commit()
        source_graph_id = graph.id
        source_graph_sha = graph.graph_sha256

    created = client.post(
        f"/api/v1/projects/{project['id']}/exchange-packages",
        json={
            "include_media": True,
            "include_model_weights": False,
            "include_generated_artifacts": True,
            "notes": "1.0 round-trip acceptance",
        },
    )
    assert created.status_code == 202, created.text
    export_payload = created.json()
    assert process_project_exchange_export_job(
        test_settings,
        app.state.session_factory,
        export_payload["job_id"],
    )

    package_response = client.get(f"/api/v1/exchange-packages/{export_payload['package']['id']}")
    assert package_response.status_code == 200, package_response.text
    package = package_response.json()
    assert package["manifest_json"]["import_policy"]["mode"] == ("import_as_new_project")
    assert package["manifest_json"]["sections"]["workflow_graphs"]["count"] == 1
    assert "jobs" in package["manifest_json"]["sections"]
    generated_descriptors = package["manifest_json"]["generated_artifacts"]
    assert any(
        item["source_relative_path"] == generated_relative_path.as_posix()
        for item in generated_descriptors
    )

    archive_path = test_settings.resolved_data_dir / Path(package["archive_path"])
    archive_bytes = archive_path.read_bytes()
    inspected = client.post(
        "/api/v1/exchange-packages/inspect",
        files={
            "file": (
                "round-trip.reefvision.zip",
                archive_bytes,
                "application/zip",
            )
        },
    )
    assert inspected.status_code == 200, inspected.text
    assert inspected.json()["compatible"] is True
    assert inspected.json()["included_generated_artifact_count"] >= 1

    imported = client.post(
        "/api/v1/exchange-packages/import",
        files={
            "file": (
                "round-trip.reefvision.zip",
                archive_bytes,
                "application/zip",
            )
        },
        data={"project_name": "Round-trip reef project imported"},
    )
    assert imported.status_code == 201, imported.text
    result = imported.json()
    imported_project_id = str(result["project_id"])
    assert imported_project_id != project["id"]
    assert result["project_name"] == "Round-trip reef project imported"
    assert result["imported_counts"]["images"] == 1
    assert result["imported_counts"]["workflow_graphs"] == 1
    assert result["copied_media_count"] == 1
    assert result["copied_generated_artifact_count"] >= 1
    assert result["package"]["direction"] == "import"
    assert result["package"]["status"] == "complete"

    imported_images = client.get(f"/api/v1/projects/{imported_project_id}/images")
    assert imported_images.status_code == 200, imported_images.text
    assert imported_images.json()["total"] == 1
    imported_image_id = str(imported_images.json()["items"][0]["id"])
    assert imported_image_id != image_id

    imported_content = client.get(f"/api/v1/images/{imported_image_id}/content")
    assert imported_content.status_code == 200, imported_content.text
    assert imported_content.content == image_bytes()

    with app.state.session_factory() as session:
        imported_project = session.get(Project, imported_project_id)
        assert imported_project is not None
        assert imported_project.georeference_height_offset_m == 5.0
        assert imported_project.georeference_height_evidence == (
            "Surveyed takeoff pad is 5 m above the surface"
        )
        restored_generated_path = (
            test_settings.resolved_data_dir
            / imported_project.storage_root
            / generated_relative_path
        )
        assert restored_generated_path.read_bytes() == generated_payload

        imported_image = session.get(ImageAsset, imported_image_id)
        assert imported_image is not None
        assert imported_image.project_id == imported_project_id
        assert imported_image.thumbnail_path is None
        assert (test_settings.resolved_data_dir / imported_image.managed_path).is_file()

        imported_graph = session.scalar(
            select(WorkflowGraphRecord).where(
                WorkflowGraphRecord.project_id == imported_project_id,
                WorkflowGraphRecord.graph_key == "round-trip-graph",
            )
        )
        assert imported_graph is not None
        assert imported_graph.id != source_graph_id
        assert imported_graph.graph_json["nodes"][0]["parameters"]["project_id"] == (
            imported_project_id
        )
        assert (
            imported_graph.graph_json["nodes"][0]["parameters"]["selected_image_id"]
            == imported_image_id
        )
        assert imported_graph.graph_sha256 != source_graph_sha
        assert imported_graph.graph_sha256 == canonical_json_sha256(imported_graph.graph_json)


def _fake_video_metadata(_path: object) -> dict[str, float | int]:
    return {
        "width_px": 200,
        "height_px": 100,
        "frame_count": 5,
        "fps": 10.0,
        "duration_seconds": 0.5,
    }


def test_project_exchange_round_trip_preserves_restart_safe_metric_3d_science(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Metric 3D exchange source")
    source_project_id = str(project["id"])
    label_class_id = str(project["label_classes"][0]["id"])
    monkeypatch.setattr(video_assets_module, "_inspect_video", _fake_video_metadata)

    imported_video = client.post(
        f"/api/v1/projects/{source_project_id}/imports/videos",
        files={"file": ("fish.mp4", io.BytesIO(b"synthetic-video"), "video/mp4")},
    )
    assert imported_video.status_code == 201, imported_video.text
    source_video_id = str(imported_video.json()["id"])
    created_track = client.post(
        f"/api/v1/videos/{source_video_id}/tracks",
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
    assert created_track.status_code == 201, created_track.text
    source_track = created_track.json()
    source_track_id = str(source_track["id"])

    calibration = client.put(
        f"/api/v1/videos/{source_video_id}/calibration",
        json={
            "unit": "cm",
            "reference_distance": 10,
            "reference_pixels": 100,
            "method": "scale_bar",
            "reference_label": "synthetic 10 cm bar",
        },
    )
    assert calibration.status_code == 200, calibration.text
    intrinsics = client.put(
        f"/api/v1/videos/{source_video_id}/camera-intrinsics",
        json={
            "fx_px": 100,
            "fy_px": 100,
            "cx_px": 5,
            "cy_px": 5,
            "method": "checkerboard",
            "notes": "Synthetic pinhole calibration",
        },
    )
    assert intrinsics.status_code == 200, intrinsics.text
    georeferencing_calibration = client.put(
        f"/api/v1/videos/{source_video_id}/georeferencing-calibration",
        json={
            "width_px": 200,
            "height_px": 100,
            "fx_px": 100,
            "fy_px": 100,
            "cx_px": 5,
            "cy_px": 5,
            "distortion_coefficients": [0.01, -0.02, 0.0, 0.0, 0.005],
            "digital_zoom_ratio": 1.0,
            "camera_mode": "synthetic-wide",
            "source": "round-trip fixture",
            "evidence": "Full georeferencing calibration preserved across exchange",
        },
    )
    assert georeferencing_calibration.status_code == 200, georeferencing_calibration.text
    source_georeferencing_checksum = georeferencing_calibration.json()["checksum_sha256"]
    source_video_revision = int(georeferencing_calibration.json()["video_revision"])

    depth_parameters: dict[str, Any] = {
        "unit": "m",
        "depth_samples": [
            {"track_id": source_track_id, "frame": 0, "depth": 2.0, "confidence": 0.99},
            {"track_id": source_track_id, "frame": 2, "depth": 2.0, "confidence": 0.98},
        ],
    }
    graph_json = {
        "schema_version": "workflow-graph-0001",
        "graph_id": "metric-3d-exchange",
        "name": "Metric 3D exchange",
        "nodes": [
            {"node_id": "project", "node_type": "project_source", "parameters": {}},
            {
                "node_id": "video",
                "node_type": "project_video_source",
                "parameters": {"video_id": source_video_id},
            },
            {
                "node_id": "tracks",
                "node_type": "video_tracking",
                "parameters": {"verified_track_ids": [source_track_id]},
            },
            {
                "node_id": "depth3d",
                "node_type": "video_depth_3d_analytics",
                "parameters": depth_parameters,
            },
        ],
        "edges": [],
    }
    app = cast(FastAPI, client.app)
    video_input = cast(
        WorkflowArtifact,
        SimpleNamespace(
            payload_json={"project_id": source_project_id, "video_id": source_video_id}
        ),
    )
    tracks_input = cast(
        WorkflowArtifact,
        SimpleNamespace(
            payload_json={
                "project_id": source_project_id,
                "video_id": source_video_id,
                "track_ids": [source_track_id],
                "tracks": [
                    {
                        "track_id": source_track_id,
                        "track_number": source_track["track_number"],
                    }
                ],
            }
        ),
    )
    with app.state.session_factory() as session:
        output = execute_video_depth_3d_adapter(
            session,
            test_settings,
            source_project_id,
            depth_parameters,
            {"video": [video_input], "tracks": [tracks_input]},
        )[0]
        trajectory_payload = cast(dict[str, Any], output["payload_json"])
        graph = WorkflowGraphRecord(
            project_id=source_project_id,
            graph_key="metric-3d-exchange",
            name="Metric 3D exchange",
            schema_version="workflow-graph-0001",
            revision=1,
            graph_json=graph_json,
            graph_sha256=canonical_json_sha256(graph_json),
        )
        session.add(graph)
        session.flush()
        run = WorkflowRun(
            project_id=source_project_id,
            workflow_graph_record_id=graph.id,
            status="succeeded",
            graph_sha256=graph.graph_sha256,
            input_json={"video_id": source_video_id, "track_ids": [source_track_id]},
            result_json={"stage": "complete", "completed_nodes": 1},
        )
        session.add(run)
        session.flush()
        node_run = WorkflowNodeRun(
            workflow_run_id=run.id,
            node_id="depth3d",
            node_type="video_depth_3d_analytics",
            execution_order=1,
            status="succeeded",
            parameters_json=depth_parameters,
            input_artifact_ids_json=[],
            output_artifact_ids_json=[],
            result_json={"video_id": source_video_id, "source_track_ids": [source_track_id]},
        )
        session.add(node_run)
        session.flush()
        artifact = WorkflowArtifact(
            workflow_run_id=run.id,
            producer_node_run_id=node_run.id,
            producer_port_id="trajectories",
            data_type="video_3d_trajectories",
            payload_json=trajectory_payload,
            payload_sha256=canonical_json_sha256(trajectory_payload),
        )
        session.add(artifact)
        session.flush()
        node_run.output_artifact_ids_json = [artifact.id]
        session.commit()
        source_graph_id = graph.id
        source_run_id = run.id
        source_artifact_id = artifact.id

    created = client.post(
        f"/api/v1/projects/{source_project_id}/exchange-packages",
        json={
            "include_media": True,
            "include_model_weights": False,
            "include_generated_artifacts": True,
            "notes": "Metric 3D restart round trip",
        },
    )
    assert created.status_code == 202, created.text
    export_payload = created.json()
    assert process_project_exchange_export_job(
        test_settings, app.state.session_factory, export_payload["job_id"]
    )
    package = client.get(f"/api/v1/exchange-packages/{export_payload['package']['id']}").json()
    archive_bytes = (test_settings.resolved_data_dir / Path(package["archive_path"])).read_bytes()
    inspected = client.post(
        "/api/v1/exchange-packages/inspect",
        files={"file": ("metric-3d.reefvision.zip", archive_bytes, "application/zip")},
    )
    assert inspected.status_code == 200, inspected.text
    assert inspected.json()["compatible"] is True
    assert inspected.json()["section_counts"]["workflow_artifacts"] == 1

    imported = client.post(
        "/api/v1/exchange-packages/import",
        files={"file": ("metric-3d.reefvision.zip", archive_bytes, "application/zip")},
        data={"project_name": "Metric 3D exchange imported"},
    )
    assert imported.status_code == 201, imported.text
    imported_project_id = str(imported.json()["project_id"])
    assert imported_project_id != source_project_id

    imported_videos = client.get(f"/api/v1/projects/{imported_project_id}/videos")
    assert imported_videos.status_code == 200, imported_videos.text
    imported_video_id = str(imported_videos.json()[0]["id"])
    imported_tracks = client.get(f"/api/v1/videos/{imported_video_id}/tracks")
    assert imported_tracks.status_code == 200, imported_tracks.text
    imported_track_id = str(imported_tracks.json()[0]["id"])
    assert imported_video_id != source_video_id
    assert imported_track_id != source_track_id
    assert imported_tracks.json()[0]["video_id"] == imported_video_id

    public_calibration = client.get(f"/api/v1/videos/{imported_video_id}/calibration")
    public_intrinsics = client.get(f"/api/v1/videos/{imported_video_id}/camera-intrinsics")
    public_georeferencing = client.get(
        f"/api/v1/videos/{imported_video_id}/georeferencing-calibration"
    )
    assert public_calibration.status_code == 200, public_calibration.text
    assert public_intrinsics.status_code == 200, public_intrinsics.text
    assert public_georeferencing.status_code == 200, public_georeferencing.text
    assert public_calibration.json()["pixels_per_unit"] == pytest.approx(10.0)
    assert public_intrinsics.json()["fx_px"] == pytest.approx(100.0)
    assert public_intrinsics.json()["video_revision"] == source_video_revision
    assert public_georeferencing.json()["checksum_sha256"] == source_georeferencing_checksum

    with app.state.session_factory() as session:
        imported_video_row = session.get(VideoAsset, imported_video_id)
        assert imported_video_row is not None
        assert "spatial_calibration" in imported_video_row.metadata_json
        assert "camera_intrinsics" in imported_video_row.metadata_json
        assert "georeferencing_camera_calibration" in imported_video_row.metadata_json
        imported_track_row = session.get(VideoTrack, imported_track_id)
        assert imported_track_row is not None
        assert imported_track_row.video_id == imported_video_id
        imported_graph = session.scalar(
            select(WorkflowGraphRecord).where(
                WorkflowGraphRecord.project_id == imported_project_id,
                WorkflowGraphRecord.graph_key == "metric-3d-exchange",
            )
        )
        imported_run = session.scalar(
            select(WorkflowRun).where(WorkflowRun.project_id == imported_project_id)
        )
        imported_artifact = session.scalar(
            select(WorkflowArtifact)
            .join(WorkflowRun)
            .where(
                WorkflowRun.project_id == imported_project_id,
                WorkflowArtifact.data_type == "video_3d_trajectories",
            )
        )
        assert imported_graph is not None and imported_graph.id != source_graph_id
        assert imported_run is not None and imported_run.id != source_run_id
        assert imported_artifact is not None and imported_artifact.id != source_artifact_id
        serialized_state = str(
            {
                "graph": imported_graph.graph_json,
                "run_input": imported_run.input_json,
                "artifact": imported_artifact.payload_json,
            }
        )
        assert source_project_id not in serialized_state
        assert source_video_id not in serialized_state
        assert source_track_id not in serialized_state
        payload = imported_artifact.payload_json
        assert payload["schema_version"] == "video-depth-track-analytics-0001"
        assert payload["unit"] == "m"
        analytics = payload["tracks"][0]
        assert analytics["track_id"] == imported_track_id
        assert analytics["path_length_3d"] == pytest.approx(0.4)
        assert analytics["displacement_3d"] == pytest.approx(0.4)
        assert analytics["mean_speed_3d_per_second"] == pytest.approx(2.0)
        assert analytics["minimum_depth"] == pytest.approx(2.0)
        assert analytics["maximum_depth"] == pytest.approx(2.0)
        assert analytics["points"][1]["x"] == pytest.approx(0.4)
        provenance = payload["workflow_provenance"]
        assert provenance["project_id"] == imported_project_id
        assert provenance["video_id"] == imported_video_id
        assert provenance["source_track_ids"] == [imported_track_id]
        assert provenance["depth_source_requirement"] == "calibrated_metric_depth"
        assert provenance["relative_monocular_depth_is_metric"] is False
        assert imported_artifact.payload_sha256 == canonical_json_sha256(payload)
        imported_run_id = imported_run.id

        rerun = execute_video_depth_3d_adapter(
            session,
            test_settings,
            imported_project_id,
            {
                "unit": "m",
                "depth_samples": [
                    {"track_id": imported_track_id, "frame": 0, "depth": 2.0},
                    {"track_id": imported_track_id, "frame": 2, "depth": 2.0},
                ],
            },
            {
                "video": [
                    cast(
                        WorkflowArtifact,
                        SimpleNamespace(payload_json={"video_id": imported_video_id}),
                    )
                ],
                "tracks": [
                    cast(
                        WorkflowArtifact,
                        SimpleNamespace(
                            payload_json={
                                "video_id": imported_video_id,
                                "track_ids": [imported_track_id],
                                "tracks": [
                                    {
                                        "track_id": imported_track_id,
                                        "track_number": source_track["track_number"],
                                    }
                                ],
                            }
                        ),
                    )
                ],
            },
        )[0]
        assert rerun["payload_json"]["tracks"][0]["path_length_3d"] == pytest.approx(0.4)

    restart_app = create_app(test_settings)
    Base.metadata.create_all(restart_app.state.engine)
    with TestClient(restart_app) as restarted:
        assert restarted.get(f"/api/v1/videos/{imported_video_id}/calibration").status_code == 200
        assert (
            restarted.get(f"/api/v1/videos/{imported_video_id}/camera-intrinsics").status_code
            == 200
        )
        reopened_georeferencing = restarted.get(
            f"/api/v1/videos/{imported_video_id}/georeferencing-calibration"
        )
        assert reopened_georeferencing.status_code == 200
        assert reopened_georeferencing.json()["checksum_sha256"] == (source_georeferencing_checksum)
        reopened_run = restarted.get(f"/api/v1/workflow-runs/{imported_run_id}")
        assert reopened_run.status_code == 200, reopened_run.text
        reopened_artifact = next(
            item
            for item in reopened_run.json()["artifacts"]
            if item["data_type"] == "video_3d_trajectories"
        )
        assert (
            reopened_artifact["payload_json"]["workflow_provenance"]["video_id"]
            == imported_video_id
        )
    restart_app.state.engine.dispose()
