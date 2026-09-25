from __future__ import annotations

from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import Job, VideoAsset, VideoTrack
from reefvision.jobs import video_annotated_export as export_job_module
from reefvision.services import video_annotated_export as renderer
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


def test_annotation_label_uses_readable_text_and_class_border(
    monkeypatch,
) -> None:
    rectangle_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    text_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    class FakeFrame:
        shape = (100, 200, 3)

    monkeypatch.setattr(
        renderer.cv2,
        "getTextSize",
        lambda *args, **kwargs: ((60, 12), 3),
    )
    monkeypatch.setattr(
        renderer.cv2,
        "rectangle",
        lambda *args, **kwargs: rectangle_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        renderer.cv2,
        "putText",
        lambda *args, **kwargs: text_calls.append((args, kwargs)),
    )

    class_color = (20, 120, 230)

    renderer._draw_label(
        FakeFrame(),
        "#7 Cruise Searching 0.91",
        10,
        30,
        class_color,
        font_scale=0.6,
        thickness=2,
    )

    assert len(rectangle_calls) == 2
    assert rectangle_calls[0][0][3] == (245, 245, 245)
    assert rectangle_calls[0][0][4] == renderer.cv2.FILLED
    assert rectangle_calls[1][0][3] == class_color
    assert text_calls[0][0][5] == (0, 0, 0)


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

    def fake_verify(
        path: Path,
        **kwargs,
    ) -> dict[str, object]:
        assert path.is_file()
        return {
            "codec": "h264",
            "container": "mp4",
            "fourcc": "h264",
            "encoder_backend": "imageio-ffmpeg/libx264",
            "crf": 20,
            "encoder_preset": "fast",
            "pixel_format": "yuv420p",
            "verified_frame_count": 3,
            "verified_fps": 10.0,
            "verified_width_px": 100,
            "verified_height_px": 60,
        }

    monkeypatch.setattr(
        export_job_module,
        "verify_annotated_video",
        fake_verify,
    )

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
    assert payload["result_json"]["codec"] == "h264"
    assert payload["result_json"]["container"] == "mp4"
    assert payload["result_json"]["encoder_backend"] == "imageio-ffmpeg/libx264"
    assert payload["result_json"]["verified_frame_count"] == 3
    assert payload["result_json"]["audio_preserved"] is False
    assert captured["trail_length"] == 42

    exports = client.get(f"/api/v1/videos/{video_id}/annotated-video-exports")
    assert exports.status_code == 200, exports.text
    assert exports.json()[0]["id"] == export_job_id

    download = client.get(f"/api/v1/video-annotated-exports/{export_job_id}/content")
    assert download.status_code == 200, download.text
    assert download.content == b"annotated-mp4"
