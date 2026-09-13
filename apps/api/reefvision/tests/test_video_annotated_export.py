from __future__ import annotations

from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import Job, VideoAsset, VideoTrack
from reefvision.jobs import video_annotated_export as export_job_module
from reefvision.services.video_annotated_export import resolve_overlay_options
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project


def test_annotated_export_preset_defaults() -> None:
    clean = resolve_overlay_options("clean_tracking", {})
    assert clean.boxes
    assert clean.track_ids
    assert clean.class_labels
    assert clean.confidence
    assert not clean.trails
    assert not clean.frame_time
    assert not clean.counters

    full = resolve_overlay_options("full_review", {"confidence": False})
    assert full.boxes
    assert full.track_ids
    assert full.class_labels
    assert not full.confidence
    assert full.trails
    assert full.frame_time
    assert full.counters


def test_annotated_export_job_and_download(
    client: TestClient,
    monkeypatch,
) -> None:
    project = create_project(client, "Annotated export")
    classes = cast(list[dict[str, object]], project["label_classes"])
    label_class_id = str(classes[0]["id"])
    app = cast(FastAPI, client.app)

    video_id = "11111111-1111-4111-8111-111111111111"
    tracking_job_id = "22222222-2222-4222-8222-222222222222"
    source_relative = f"{project['storage_root']}/videos/originals/{video_id}.mp4"
    source_path = resolve_managed_project_path(app.state.settings, source_relative)
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"fake-video")

    with app.state.session_factory() as session:
        session.add(
            VideoAsset(
                id=video_id,
                project_id=str(project["id"]),
                original_filename="reef survey.mp4",
                managed_path=source_relative,
                sha256="a" * 64,
                media_type="video/mp4",
                width_px=100,
                height_px=60,
                frame_count=3,
                fps=10.0,
                duration_seconds=0.3,
                metadata_json={},
                status="tracked",
            )
        )
        session.add(
            Job(
                id=tracking_job_id,
                project_id=str(project["id"]),
                job_type="video_tracking",
                status="succeeded",
                progress_current=3,
                progress_total=3,
                request_json={"video_id": video_id, "tracker": "bytetrack.yaml"},
                result_json={"track_count": 1, "observation_count": 2},
            )
        )
        session.add(
            VideoTrack(
                video_id=video_id,
                label_class_id=label_class_id,
                track_number=1,
                geometry_kind="bbox",
                keyframes_json=[
                    {"frame": 0, "bbox": [5, 5, 20, 10], "confidence": 0.9},
                    {"frame": 1, "bbox": [10, 5, 20, 10], "confidence": 0.8},
                ],
                interpolation="linear",
                status="machine_generated",
                source_job_id=tracking_job_id,
                metadata_json={},
            )
        )
        session.commit()

    captured: dict[str, object] = {}

    def fake_render(
        source_path: Path,
        destination_path: Path,
        **kwargs,
    ) -> int:
        captured["source"] = source_path
        captured["observations"] = kwargs["observations"]
        captured["options"] = kwargs["options"].as_dict()
        captured["trail_length"] = kwargs["trail_length"]
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_bytes(b"annotated-mp4")
        kwargs["on_progress"](3)
        return 3

    monkeypatch.setattr(export_job_module, "render_annotated_video", fake_render)

    queued = client.post(
        f"/api/v1/videos/{video_id}/annotated-video-exports",
        json={
            "source_tracking_job_id": tracking_job_id,
            "preset": "full_review",
            "overlays": {"confidence": False},
            "trail_length": 42,
        },
    )
    assert queued.status_code == 200, queued.text
    export_job_id = queued.json()["id"]

    processed = export_job_module.process_video_annotated_export_job(
        app.state.settings,
        app.state.session_factory,
        export_job_id,
    )
    if not processed:
        with app.state.session_factory() as session:
            failed_job = session.get(Job, export_job_id)
            message = failed_job.error_message if failed_job else "job missing"
            raise AssertionError(f"Annotated export failed: {message}")

    status = client.get(f"/api/v1/jobs/{export_job_id}")
    assert status.status_code == 200, status.text
    payload = status.json()
    assert payload["status"] == "succeeded"
    assert payload["progress_current"] == 3
    assert payload["result_json"]["preset"] == "full_review"
    assert payload["result_json"]["overlays"]["confidence"] is False
    assert payload["result_json"]["overlays"]["trails"] is True
    assert payload["result_json"]["track_count"] == 1
    assert payload["result_json"]["observation_count"] == 2
    assert payload["result_json"]["audio_preserved"] is False
    assert captured["trail_length"] == 42

    exports = client.get(f"/api/v1/videos/{video_id}/annotated-video-exports")
    assert exports.status_code == 200, exports.text
    assert exports.json()[0]["id"] == export_job_id

    download = client.get(f"/api/v1/video-annotated-exports/{export_job_id}/content")
    assert download.status_code == 200, download.text
    assert download.content == b"annotated-mp4"
