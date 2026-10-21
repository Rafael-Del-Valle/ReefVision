"""Geographic analytics across the real invalidation/recomputation lifecycle."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from reefvision.db.models import LabelClass, Project, VideoAsset, VideoTrack
from reefvision.geospatial.models import TelemetrySample
from reefvision.geospatial.synchronization import IndexedTelemetrySource
from reefvision.schemas.georeferenced_observation import BoundingBoxPixels
from reefvision.schemas.projects import ProjectUpdate
from reefvision.schemas.video_georeferencing_calibration import (
    VideoGeoreferencingCalibrationSetRequest,
)
from reefvision.services.georeferenced_observations import GeoReferencedObservationService
from reefvision.services.projects import ProjectService
from reefvision.services.video_assets import VideoAssetService
from reefvision.services.video_georeferencing import VideoGeoreferencingService
from reefvision.services.video_georeferencing_calibration import (
    VideoGeoreferencingCalibrationService,
)


def test_geographic_analytics_resumes_after_real_recomputation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Only replace telemetry acquisition; projection, hashes, persistence,
    # invalidation, recomputation and both HTTP endpoints are real.
    source = IndexedTelemetrySource(
        [
            TelemetrySample(
                sample_index=index,
                time_s=float(index),
                latitude=0.0,
                longitude=0.0,
                relative_altitude_m=100.0,
                gimbal_yaw_deg=0.0,
                gimbal_pitch_deg=-90.0,
                gimbal_roll_deg=0.0,
                digital_zoom_ratio=1.0,
            )
            for index in range(2)
        ]
    )
    monkeypatch.setattr(VideoAssetService, "telemetry_source", lambda _self, _id: source)
    app = client.app
    settings = app.state.settings

    with app.state.session_factory() as session:
        project = Project(
            name="Movement lifecycle",
            slug="movement-lifecycle",
            storage_root="projects/movement-lifecycle",
            georeference_height_offset_m=5.0,
            georeference_height_evidence="Synthetic datum: takeoff is 5 m above surface",
        )
        session.add(project)
        session.flush()
        video = VideoAsset(
            project_id=project.id,
            original_filename="synthetic.mp4",
            managed_path="projects/movement-lifecycle/videos/synthetic.mp4",
            sha256="0" * 64,
            media_type="video/mp4",
            width_px=1000,
            height_px=800,
            frame_count=60,
            fps=30.0,
            duration_seconds=2.0,
            metadata_json={},
            status="imported",
        )
        label_class = LabelClass(
            project_id=project.id,
            class_index=0,
            display_order=0,
            name="Organism",
            display_color="#336699",
        )
        session.add_all([video, label_class])
        session.flush()
        track = VideoTrack(
            video_id=video.id,
            label_class_id=label_class.id,
            track_number=1,
            geometry_kind="bbox",
            interpolation="linear",
            status="verified",
            keyframes_json=[
                {"frame": 0, "bbox": [490.0, 390.0, 20.0, 20.0]},
                {"frame": 30, "bbox": [590.0, 390.0, 20.0, 20.0]},
            ],
        )
        session.add(track)
        session.flush()
        project_id, video_id, track_id = project.id, video.id, track.id
        VideoGeoreferencingCalibrationService(session).set(
            video_id,
            VideoGeoreferencingCalibrationSetRequest(
                width_px=1000,
                height_px=800,
                fx_px=500.0,
                fy_px=500.0,
                cx_px=500.0,
                cy_px=400.0,
                distortion_coefficients=(),
                digital_zoom_ratio=1.0,
                camera_mode="synthetic-wide",
                source="Synthetic pinhole parameters",
                evidence="Fixed unit-test reference plane",
            ),
        )
        georeferencing = VideoGeoreferencingService(session, settings)
        persistence = GeoReferencedObservationService(session)
        configuration_hash = georeferencing.configuration_hash(video_id)
        original_ids = []
        for frame, center_x in [(0, 500.0), (30, 600.0)]:
            observation = georeferencing.georeference_detection(
                video_id,
                frame_index=frame,
                track_id=track_id,
                bbox=BoundingBoxPixels(
                    x_min=center_x - 10.0,
                    y_min=390.0,
                    x_max=center_x + 10.0,
                    y_max=410.0,
                ),
            )
            original_ids.append(str(observation.id))
            persistence.persist(observation, configuration_hash=configuration_hash)
        session.commit()

    endpoint = f"/api/v1/video-tracks/{track_id}/geographic-analytics"
    before = client.get(endpoint)
    assert before.status_code == 200
    assert before.json()["observation_count"] == 2
    assert before.json()["total_distance_m"] == pytest.approx(21.0, abs=1e-5)

    with app.state.session_factory() as session:
        ProjectService(session, settings).update_project(
            project_id,
            ProjectUpdate(
                georeference_height_offset_m=10.0,
                georeference_height_evidence="Synthetic revised datum: 10 m above surface",
            ),
        )

    stale = client.get(endpoint)
    assert stale.status_code == 200
    assert stale.json()["observation_count"] == 0
    assert stale.json()["segments"] == []
    assert stale.json()["mean_speed_m_s"] is None

    recomputed = client.post(f"/api/v1/videos/{video_id}/georeferenced-observations/recompute")
    assert recomputed.status_code == 200, recomputed.text
    assert recomputed.json()["recomputed_count"] == 2

    after = client.get(endpoint)
    assert after.status_code == 200
    payload = after.json()
    assert payload["observation_count"] == 2
    assert payload["total_distance_m"] == pytest.approx(22.0, abs=1e-5)
    segment = payload["segments"][0]
    assert segment["initial_bearing_deg"] == pytest.approx(90.0)
    assert segment["start_observation_id"] not in original_ids
    assert segment["end_observation_id"] not in original_ids
