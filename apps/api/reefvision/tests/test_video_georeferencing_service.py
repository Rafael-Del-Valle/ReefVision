from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.requests import Request

from reefvision.api.routes.videos import georeference_existing_video_tracks
from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.db.models import LabelClass, Project, VideoAsset, VideoTrack
from reefvision.db.session import create_database_engine, create_session_factory
from reefvision.domain.errors import ValidationError
from reefvision.geospatial.models import TelemetrySample
from reefvision.geospatial.synchronization import IndexedTelemetrySource, PreferredTelemetrySource
from reefvision.schemas.georeferenced_observation import BoundingBoxPixels
from reefvision.schemas.video_georeferencing_calibration import (
    VideoGeoreferencingCalibrationSetRequest,
)
from reefvision.services.georeferenced_observations import GeoReferencedObservationService
from reefvision.services.video_assets import VideoAssetService
from reefvision.services.video_georeferencing import VideoGeoreferencingService
from reefvision.services.video_georeferencing_calibration import (
    GEOREFERENCING_CALIBRATION_METADATA_KEY,
    VideoGeoreferencingCalibrationService,
)
from reefvision.services.video_georeferencing_readiness import (
    VideoGeoreferencingReadinessService,
)

ServiceContext = tuple[Settings, Any, str]


@pytest.fixture
def service_context(
    tmp_path: Path,
) -> Iterator[ServiceContext]:
    settings = Settings(
        env="test",
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{(tmp_path / 'service.db').as_posix()}",
        background_worker_enabled=False,
    )
    settings.ensure_directories()
    engine = create_database_engine(settings)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        project = Project(
            name="Geo",
            slug="geo",
            storage_root="projects/geo",
            georeference_height_offset_m=5.0,
            georeference_height_evidence="Synthetic takeoff point is 5 m above the surface",
        )
        session.add(project)
        session.flush()
        video = VideoAsset(
            project_id=project.id,
            original_filename="geo.mp4",
            managed_path=f"{project.storage_root}/videos/originals/geo.mp4",
            sha256="0" * 64,
            media_type="video/mp4",
            width_px=1000,
            height_px=800,
            frame_count=300,
            fps=30.0,
            duration_seconds=10.0,
            metadata_json={},
            status="imported",
        )
        session.add(video)
        session.flush()
        VideoGeoreferencingCalibrationService(session).set(
            video.id,
            VideoGeoreferencingCalibrationSetRequest(
                width_px=1000,
                height_px=800,
                fx_px=500,
                fy_px=500,
                cx_px=500,
                cy_px=400,
                distortion_coefficients=(),
                digital_zoom_ratio=1.0,
                camera_mode="synthetic-wide",
                source="Synthetic unit-test calibration",
                evidence="Known pinhole parameters for service contract tests",
            ),
        )
        video_id = video.id
    try:
        yield settings, factory, video_id
    finally:
        engine.dispose()


def _source(
    *,
    time_s: float = 0.0,
    roll: float | None = 0.0,
    pitch: float = -90.0,
    digital_zoom_ratio: float = 1.0,
) -> IndexedTelemetrySource:
    return IndexedTelemetrySource(
        [
            TelemetrySample(
                sample_index=0,
                time_s=time_s,
                latitude=0.0,
                longitude=0.0,
                relative_altitude_m=100.0,
                gimbal_yaw_deg=0.0,
                gimbal_pitch_deg=pitch,
                gimbal_roll_deg=roll,
                digital_zoom_ratio=digital_zoom_ratio,
            )
        ]
    )


def _source_for_video(
    *,
    fps: float = 30.0,
    frame_count: int = 300,
    digital_zoom_ratio: float = 1.0,
) -> IndexedTelemetrySource:
    frames = [
        0,
        round((frame_count - 1) * 0.25),
        round((frame_count - 1) * 0.50),
        round((frame_count - 1) * 0.75),
        frame_count - 1,
    ]
    return IndexedTelemetrySource(
        [
            TelemetrySample(
                sample_index=index,
                time_s=frame / fps,
                latitude=0.0,
                longitude=0.0,
                relative_altitude_m=100.0,
                gimbal_yaw_deg=0.0,
                gimbal_pitch_deg=-90.0,
                gimbal_roll_deg=0.0,
                digital_zoom_ratio=digital_zoom_ratio,
            )
            for index, frame in enumerate(frames)
        ]
    )


def test_georeference_point_success(
    service_context: ServiceContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, factory, video_id = service_context
    with factory() as session:
        service = VideoGeoreferencingService(session, settings)
        preferred = PreferredTelemetrySource(airdata=None, srt=_source())
        monkeypatch.setattr(service.video_assets, "telemetry_source", lambda _: preferred)
        response = service.georeference_point(
            video_id,
            frame_index=0,
            pixel_x=500.0,
            pixel_y=400.0,
        )

    assert response.status == "success"
    assert response.failure_reason is None
    assert response.result is not None
    assert response.result.latitude == pytest.approx(0.0, abs=1e-12)
    assert response.result.longitude == pytest.approx(0.0, abs=1e-12)
    assert response.result.camera_height_m == pytest.approx(105.0)
    assert response.result.surface_reference.takeoff_height_above_surface_m == pytest.approx(5.0)
    assert response.result.surface_reference.evidence == (
        "Synthetic takeoff point is 5 m above the surface"
    )
    assert response.result.calibration_source_id is not None
    assert response.result.calibration_source_id.startswith("sha256:")
    assert response.sync_error_s == pytest.approx(0.0)
    assert response.telemetry_provenance is not None
    assert response.telemetry_provenance.position_source == "dji_srt"
    assert response.telemetry_provenance.gimbal_yaw_source == "dji_srt"


def test_georeference_point_requires_project_surface_evidence(
    service_context: ServiceContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, factory, video_id = service_context
    with factory() as session:
        video = session.get(VideoAsset, video_id)
        assert video is not None
        project = session.get(Project, video.project_id)
        assert project is not None
        project.georeference_height_evidence = None
        session.commit()

        service = VideoGeoreferencingService(session, settings)
        monkeypatch.setattr(service.video_assets, "telemetry_source", lambda _: _source())
        response = service.georeference_point(
            video_id,
            frame_index=0,
            pixel_x=500.0,
            pixel_y=400.0,
        )

    assert response.status == "failed"
    assert response.failure_reason == "surface_reference_unavailable"
    assert response.message is not None
    assert "datum evidence" in response.message.casefold()


def test_georeference_point_reports_missing_telemetry(
    service_context: ServiceContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, factory, video_id = service_context
    with factory() as session:
        service = VideoGeoreferencingService(session, settings)
        monkeypatch.setattr(service.video_assets, "telemetry_source", lambda _: None)
        response = service.georeference_point(
            video_id,
            frame_index=0,
            pixel_x=500.0,
            pixel_y=400.0,
        )

    assert response.status == "failed"
    assert response.failure_reason == "telemetry_unavailable"


def test_georeference_point_reports_out_of_sync_telemetry(
    service_context: ServiceContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, factory, video_id = service_context
    with factory() as session:
        service = VideoGeoreferencingService(session, settings)
        monkeypatch.setattr(service.video_assets, "telemetry_source", lambda _: _source(time_s=1.0))
        response = service.georeference_point(
            video_id,
            frame_index=0,
            pixel_x=500.0,
            pixel_y=400.0,
        )

    assert response.status == "failed"
    assert response.failure_reason == "telemetry_out_of_sync"


def test_georeference_point_rejects_frame_outside_video(
    service_context: ServiceContext,
) -> None:
    settings, factory, video_id = service_context
    with factory() as session:
        response = VideoGeoreferencingService(session, settings).georeference_point(
            video_id,
            frame_index=300,
            pixel_x=500.0,
            pixel_y=400.0,
        )

    assert response.status == "failed"
    assert response.failure_reason == "frame_out_of_range"


def test_georeference_point_reports_missing_calibration(
    service_context: ServiceContext,
) -> None:
    settings, factory, video_id = service_context
    with factory() as session:
        service = VideoGeoreferencingService(session, settings)
        service.calibrations.clear(video_id)
        response = service.georeference_point(
            video_id,
            frame_index=0,
            pixel_x=500.0,
            pixel_y=400.0,
        )

    assert response.status == "failed"
    assert response.failure_reason == "calibration_unavailable"


def test_georeference_point_reports_corrupt_calibration_resolution(
    service_context: ServiceContext,
) -> None:
    settings, factory, video_id = service_context
    with factory() as session:
        video = session.get(VideoAsset, video_id)
        assert video is not None
        metadata = dict(video.metadata_json)
        raw = dict(metadata[GEOREFERENCING_CALIBRATION_METADATA_KEY])
        raw["width_px"] = 999
        metadata[GEOREFERENCING_CALIBRATION_METADATA_KEY] = raw
        video.metadata_json = metadata
        session.commit()

        response = VideoGeoreferencingService(session, settings).georeference_point(
            video_id,
            frame_index=0,
            pixel_x=500.0,
            pixel_y=400.0,
        )

    assert response.status == "failed"
    assert response.failure_reason == "calibration_mismatch"


def test_georeference_point_reports_calibration_checksum_mismatch(
    service_context: ServiceContext,
) -> None:
    settings, factory, video_id = service_context
    with factory() as session:
        video = session.get(VideoAsset, video_id)
        assert video is not None
        metadata = dict(video.metadata_json)
        raw = dict(metadata[GEOREFERENCING_CALIBRATION_METADATA_KEY])
        raw["checksum_sha256"] = "0" * 64
        metadata[GEOREFERENCING_CALIBRATION_METADATA_KEY] = raw
        video.metadata_json = metadata
        session.commit()

        response = VideoGeoreferencingService(session, settings).georeference_point(
            video_id,
            frame_index=0,
            pixel_x=500.0,
            pixel_y=400.0,
        )

    assert response.status == "failed"
    assert response.failure_reason == "calibration_mismatch"
    assert response.message is not None
    assert "checksum" in response.message.casefold()


def test_georeference_point_reports_zoom_mismatch(
    service_context: ServiceContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, factory, video_id = service_context
    with factory() as session:
        service = VideoGeoreferencingService(session, settings)
        monkeypatch.setattr(
            service.video_assets,
            "telemetry_source",
            lambda _: _source(digital_zoom_ratio=2.0),
        )
        response = service.georeference_point(
            video_id,
            frame_index=0,
            pixel_x=500.0,
            pixel_y=400.0,
        )

    assert response.status == "failed"
    assert response.failure_reason == "calibration_zoom_mismatch"


def test_georeference_point_rejects_unstable_near_horizon_projection(
    service_context: ServiceContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, factory, video_id = service_context

    with factory() as session:
        service = VideoGeoreferencingService(
            session,
            settings,
        )

        preferred = PreferredTelemetrySource(
            airdata=None,
            srt=_source(pitch=-7.5),
        )

        monkeypatch.setattr(
            service.video_assets,
            "telemetry_source",
            lambda _: preferred,
        )

        response = service.georeference_point(
            video_id,
            frame_index=0,
            pixel_x=500.0,
            pixel_y=400.0,
        )

    assert response.status == "failed"
    assert response.failure_reason == "projection_failed"
    assert response.message is not None
    assert "minimum required for stable flat-surface projection" in response.message
    assert "8.000" in response.message


def test_georeference_point_returns_projection_failure(
    service_context: ServiceContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, factory, video_id = service_context
    with factory() as session:
        service = VideoGeoreferencingService(session, settings)
        monkeypatch.setattr(
            service.video_assets,
            "telemetry_source",
            lambda _: _source(roll=None),
        )
        response = service.georeference_point(
            video_id,
            frame_index=0,
            pixel_x=500.0,
            pixel_y=400.0,
        )

    assert response.status == "failed"
    assert response.failure_reason == "projection_failed"
    assert response.sync_error_s == pytest.approx(0.0)
    assert response.message is not None
    assert "gimbal" in response.message.casefold()


def test_georeferencing_readiness_reports_all_missing_inputs(
    service_context: ServiceContext,
) -> None:
    settings, factory, video_id = service_context
    with factory() as session:
        video = session.get(VideoAsset, video_id)
        assert video is not None
        project = session.get(Project, video.project_id)
        assert project is not None
        project.georeference_height_evidence = None
        VideoGeoreferencingCalibrationService(session).clear(video_id)

        readiness = VideoGeoreferencingReadinessService(session, settings).evaluate(video_id)

    assert readiness.ready is False
    assert readiness.state == "missing_calibration"
    codes = {issue.code for issue in readiness.issues}
    assert codes == {
        "missing_calibration",
        "missing_surface_reference",
        "missing_telemetry",
    }


def test_georeferencing_readiness_reports_ready_for_synced_video(
    service_context: ServiceContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, factory, video_id = service_context
    with factory() as session:
        video = session.get(VideoAsset, video_id)
        assert video is not None
        metadata = dict(video.metadata_json)
        metadata["telemetry"] = {
            "found": True,
            "available": True,
            "source_type": "dji_srt",
            "source_path": "synthetic.srt",
            "path_kind": "managed",
            "sample_count": 5,
            "error": None,
        }
        video.metadata_json = metadata
        session.commit()

        service = VideoGeoreferencingReadinessService(session, settings)
        monkeypatch.setattr(
            service.video_assets,
            "telemetry_source",
            lambda _: _source_for_video(),
        )
        readiness = service.evaluate(video_id)

    assert readiness.ready is True
    assert readiness.state == "ready"
    assert readiness.issues == []
    assert readiness.synchronized_frame_count == 5
    assert readiness.sampled_frame_count == 5
    assert readiness.maximum_sync_error_s == pytest.approx(0.0)
    assert readiness.zoom_compatible is True


def test_georeferencing_readiness_reports_airdata_alignment_problem(
    service_context: ServiceContext,
) -> None:
    settings, factory, video_id = service_context
    with factory() as session:
        video = session.get(VideoAsset, video_id)
        assert video is not None
        metadata = dict(video.metadata_json)
        metadata["airdata_telemetry"] = {
            "found": True,
            "available": True,
            "source_type": "airdata",
            "source_path": "synthetic.csv",
            "path_kind": "managed",
            "sample_count": 100,
            "error": None,
        }
        metadata["airdata_alignment"] = {
            "time_offset_s": 6.19,
            "evidence": None,
        }
        video.metadata_json = metadata
        session.commit()

        readiness = VideoGeoreferencingReadinessService(session, settings).evaluate(video_id)

    assert readiness.ready is False
    assert readiness.state == "alignment_problem"
    assert readiness.airdata_alignment_valid is False
    assert {issue.code for issue in readiness.issues} == {"invalid_airdata_alignment"}


def test_georeferencing_readiness_reports_synchronization_problem(
    service_context: ServiceContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, factory, video_id = service_context
    with factory() as session:
        video = session.get(VideoAsset, video_id)
        assert video is not None
        metadata = dict(video.metadata_json)
        metadata["telemetry"] = {
            "found": True,
            "available": True,
            "source_type": "dji_srt",
            "source_path": "synthetic.srt",
            "path_kind": "managed",
            "sample_count": 1,
            "error": None,
        }
        video.metadata_json = metadata
        session.commit()

        service = VideoGeoreferencingReadinessService(session, settings)
        monkeypatch.setattr(
            service.video_assets,
            "telemetry_source",
            lambda _: _source(time_s=0.0),
        )
        readiness = service.evaluate(video_id)

    assert readiness.ready is False
    assert readiness.state == "synchronization_problem"
    assert readiness.synchronized_frame_count == 1
    assert readiness.sampled_frame_count == 5
    assert {issue.code for issue in readiness.issues} == {"telemetry_out_of_sync"}


def test_georeferencing_readiness_allows_zoom_mismatch(
    service_context: ServiceContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, factory, video_id = service_context
    with factory() as session:
        video = session.get(VideoAsset, video_id)
        assert video is not None
        metadata = dict(video.metadata_json)
        metadata["telemetry"] = {
            "found": True,
            "available": True,
            "source_type": "dji_srt",
            "source_path": "synthetic.srt",
            "path_kind": "managed",
            "sample_count": 5,
            "error": None,
        }
        video.metadata_json = metadata
        session.commit()

        service = VideoGeoreferencingReadinessService(session, settings)
        monkeypatch.setattr(
            service.video_assets,
            "telemetry_source",
            lambda _: _source_for_video(digital_zoom_ratio=2.0),
        )
        readiness = service.evaluate(video_id)

    assert readiness.ready is True
    assert readiness.state == "ready"
    assert readiness.synchronized_frame_count == 5
    assert readiness.zoom_compatible is False
    assert readiness.issues == []


@pytest.mark.parametrize(
    ("zooms", "missing_roll_frame", "expected_frames", "skipped", "failed"),
    [
        ((1.0, 2.0, 1.0, 2.0, 1.0), None, [0, 150, 299], 2, 0),
        ((2.0, 2.0, 2.0, 2.0, 2.0), None, [], 5, 0),
        ((1.0, 1.0, 1.0, 1.0, 1.0), None, [0, 75, 150, 224, 299], 0, 0),
        ((1.0000005, 1.000002, 1.0, 2.0, 1.0), None, [0, 150, 299], 2, 0),
        ((1.0, 2.0, 1.0, 2.0, 1.0), 150, [0, 299], 2, 1),
    ],
    ids=["mixed", "all-wrong", "all-matching", "zoom-tolerance", "other-failure"],
)
def test_georeference_tracks_skips_only_zoom_mismatches(
    service_context: ServiceContext,
    monkeypatch: pytest.MonkeyPatch,
    zooms: tuple[float, ...],
    missing_roll_frame: int | None,
    expected_frames: list[int],
    skipped: int,
    failed: int,
) -> None:
    settings, factory, video_id = service_context
    frames = [0, 75, 150, 224, 299]
    source = PreferredTelemetrySource(
        airdata=None,
        srt=IndexedTelemetrySource(
            [
                TelemetrySample(
                    sample_index=index,
                    time_s=frame / 30.0,
                    latitude=0.0,
                    longitude=0.0,
                    relative_altitude_m=100.0,
                    gimbal_yaw_deg=0.0,
                    gimbal_pitch_deg=-90.0,
                    gimbal_roll_deg=None if frame == missing_roll_frame else 0.0,
                    digital_zoom_ratio=zoom,
                )
                for index, (frame, zoom) in enumerate(zip(frames, zooms, strict=True))
            ]
        ),
    )
    monkeypatch.setattr(VideoAssetService, "telemetry_source", lambda self, _: source)
    with factory() as session:
        video = session.get(VideoAsset, video_id)
        video.metadata_json = {
            **video.metadata_json,
            "telemetry": {
                "found": True,
                "available": True,
                "source_type": "dji_srt",
                "source_path": "synthetic.srt",
                "path_kind": "managed",
                "sample_count": 5,
            },
        }
        label = LabelClass(
            project_id=video.project_id,
            name="Fish",
            class_index=0,
            display_order=0,
            display_color="#ffffff",
        )
        session.add(label)
        session.flush()
        session.add(
            VideoTrack(
                video_id=video_id,
                label_class_id=label.id,
                track_number=1,
                keyframes_json=[{"frame": frame, "bbox": [490, 390, 20, 20]} for frame in frames],
            )
        )
        session.commit()

        readiness = VideoGeoreferencingReadinessService(session, settings).evaluate(video_id)
        assert readiness.ready is True
        request = Request(
            {
                "type": "http",
                "app": SimpleNamespace(
                    state=SimpleNamespace(settings=settings),
                ),
            }
        )
        response = georeference_existing_video_tracks(video_id, request, session)
        assert response["attempted_count"] == 5
        assert response["georeferenced_observation_count"] == len(expected_frames)
        assert response["skipped_zoom_mismatch_count"] == skipped
        assert response["failure_count"] == failed

    with factory() as session:
        persistence = GeoReferencedObservationService(session)
        stored = persistence.list_for_video(video_id)
        assert [row.frame_index for row in stored] == expected_frames
        for row in stored:
            assert row.latitude_deg == pytest.approx(0.0, abs=1e-12)
            assert row.longitude_deg == pytest.approx(0.0, abs=1e-12)
            assert row.configuration_hash == response["configuration_hash"]
            observation = persistence.to_response(row)
            assert observation.calibration.zoom_state == 1.0
            field_provenance = observation.telemetry.field_provenance
            assert field_provenance is not None
            assert field_provenance["position_source"] == "dji_srt"


def test_georeference_detection_prefers_explicit_representative_pixel(
    service_context: ServiceContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, factory, video_id = service_context

    with factory() as session:
        service = VideoGeoreferencingService(session, settings)

        preferred = PreferredTelemetrySource(
            airdata=None,
            srt=_source(),
        )

        monkeypatch.setattr(
            service.video_assets,
            "telemetry_source",
            lambda _: preferred,
        )

        observation = service.georeference_detection(
            video_id,
            frame_index=0,
            bbox=BoundingBoxPixels(
                x_min=400.0,
                y_min=300.0,
                x_max=600.0,
                y_max=500.0,
            ),
            representative_pixel=(520.0, 410.0),
        )

    assert observation.representative_pixel.method == "explicit"
    assert observation.representative_pixel.x == pytest.approx(520.0)
    assert observation.representative_pixel.y == pytest.approx(410.0)

    assert observation.bbox.x_min == pytest.approx(400.0)
    assert observation.bbox.x_max == pytest.approx(600.0)

    assert observation.frame_width_px == 1000
    assert observation.frame_height_px == 800

    assert observation.telemetry.source_type == "dji_srt"
    assert observation.telemetry.field_provenance is not None
    assert observation.telemetry.field_provenance["position_source"] == "dji_srt"

    assert observation.calibration.checksum_sha256 is not None
    assert str(observation.calibration.calibration_id).startswith("sha256:")

    assert observation.method.version == ("opencv-dji-enu-flat-wgs84-v2")


def test_georeference_detection_falls_back_to_bbox_center(
    service_context: ServiceContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, factory, video_id = service_context

    with factory() as session:
        service = VideoGeoreferencingService(session, settings)

        preferred = PreferredTelemetrySource(
            airdata=None,
            srt=_source(),
        )

        monkeypatch.setattr(
            service.video_assets,
            "telemetry_source",
            lambda _: preferred,
        )

        observation = service.georeference_detection(
            video_id,
            frame_index=0,
            bbox=BoundingBoxPixels(
                x_min=400.0,
                y_min=300.0,
                x_max=600.0,
                y_max=500.0,
            ),
        )

    assert observation.representative_pixel.method == "bbox_center"
    assert observation.representative_pixel.x == pytest.approx(500.0)
    assert observation.representative_pixel.y == pytest.approx(400.0)

    # Center of the synthetic nadir camera projects directly below it.
    assert observation.location.latitude_deg == pytest.approx(
        0.0,
        abs=1e-12,
    )
    assert observation.location.longitude_deg == pytest.approx(
        0.0,
        abs=1e-12,
    )


def test_georeference_detection_rejects_explicit_pixel_outside_bbox(
    service_context: ServiceContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, factory, video_id = service_context

    with factory() as session:
        service = VideoGeoreferencingService(session, settings)

        preferred = PreferredTelemetrySource(
            airdata=None,
            srt=_source(),
        )

        monkeypatch.setattr(
            service.video_assets,
            "telemetry_source",
            lambda _: preferred,
        )

        with pytest.raises(
            ValidationError,
            match="must lie within the detection bounding box",
        ):
            service.georeference_detection(
                video_id,
                frame_index=0,
                bbox=BoundingBoxPixels(
                    x_min=400.0,
                    y_min=300.0,
                    x_max=600.0,
                    y_max=500.0,
                ),
                representative_pixel=(700.0, 410.0),
            )
