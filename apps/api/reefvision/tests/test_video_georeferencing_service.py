from __future__ import annotations

from pathlib import Path

import pytest

from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.db.models import Project, VideoAsset
from reefvision.db.session import create_database_engine, create_session_factory
from reefvision.geospatial.calibration import CameraCalibration
from reefvision.geospatial.models import TelemetrySample
from reefvision.geospatial.projection import SurfaceReference
from reefvision.geospatial.synchronization import IndexedTelemetrySource, PreferredTelemetrySource
from reefvision.services.video_georeferencing import VideoGeoreferencingService


@pytest.fixture
def service_context(tmp_path: Path):
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
            georeference_height_offset_m=0.0,
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
        session.commit()
        video_id = video.id
    try:
        yield settings, factory, video_id
    finally:
        engine.dispose()


@pytest.fixture
def calibration() -> CameraCalibration:
    return CameraCalibration(
        width_px=1000,
        height_px=800,
        fx_px=500,
        fy_px=500,
        cx_px=500,
        cy_px=400,
        distortion_coefficients=(),
        source_id="synthetic",
    )


@pytest.fixture
def surface() -> SurfaceReference:
    return SurfaceReference(
        takeoff_height_above_surface_m=0.0,
        evidence="Synthetic takeoff plane equals projected surface",
    )


def _source(*, time_s: float = 0.0, roll: float | None = 0.0) -> IndexedTelemetrySource:
    return IndexedTelemetrySource(
        [
            TelemetrySample(
                sample_index=0,
                time_s=time_s,
                latitude=0.0,
                longitude=0.0,
                relative_altitude_m=100.0,
                gimbal_yaw_deg=0.0,
                gimbal_pitch_deg=-90.0,
                gimbal_roll_deg=roll,
                digital_zoom_ratio=1.0,
            )
        ]
    )


def test_georeference_point_success(
    service_context,
    calibration: CameraCalibration,
    surface: SurfaceReference,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, factory, video_id = service_context
    with factory() as session:
        service = VideoGeoreferencingService(session, settings)
        preferred = PreferredTelemetrySource(airdata=_source(), srt=None)
        monkeypatch.setattr(service.video_assets, "telemetry_source", lambda _: preferred)
        response = service.georeference_point(
            video_id,
            frame_index=0,
            pixel_x=500.0,
            pixel_y=400.0,
            calibration=calibration,
            surface=surface,
        )

    assert response.status == "success"
    assert response.failure_reason is None
    assert response.result is not None
    assert response.result.latitude == pytest.approx(0.0, abs=1e-12)
    assert response.result.longitude == pytest.approx(0.0, abs=1e-12)
    assert response.sync_error_s == pytest.approx(0.0)
    assert response.telemetry_provenance is not None
    assert response.telemetry_provenance.position_source == "airdata"
    assert response.telemetry_provenance.gimbal_yaw_source == "airdata"


def test_georeference_point_reports_missing_telemetry(
    service_context,
    calibration: CameraCalibration,
    surface: SurfaceReference,
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
            calibration=calibration,
            surface=surface,
        )

    assert response.status == "failed"
    assert response.failure_reason == "telemetry_unavailable"


def test_georeference_point_reports_out_of_sync_telemetry(
    service_context,
    calibration: CameraCalibration,
    surface: SurfaceReference,
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
            calibration=calibration,
            surface=surface,
        )

    assert response.status == "failed"
    assert response.failure_reason == "telemetry_out_of_sync"


def test_georeference_point_rejects_frame_outside_video(
    service_context,
    calibration: CameraCalibration,
    surface: SurfaceReference,
) -> None:
    settings, factory, video_id = service_context
    with factory() as session:
        response = VideoGeoreferencingService(session, settings).georeference_point(
            video_id,
            frame_index=300,
            pixel_x=500.0,
            pixel_y=400.0,
            calibration=calibration,
            surface=surface,
        )

    assert response.status == "failed"
    assert response.failure_reason == "frame_out_of_range"


def test_georeference_point_rejects_calibration_dimension_mismatch(
    service_context,
    calibration: CameraCalibration,
    surface: SurfaceReference,
) -> None:
    settings, factory, video_id = service_context
    wrong = calibration.model_copy(update={"width_px": 999})
    with factory() as session:
        response = VideoGeoreferencingService(session, settings).georeference_point(
            video_id,
            frame_index=0,
            pixel_x=500.0,
            pixel_y=400.0,
            calibration=wrong,
            surface=surface,
        )

    assert response.status == "failed"
    assert response.failure_reason == "calibration_mismatch"


def test_georeference_point_returns_projection_failure(
    service_context,
    calibration: CameraCalibration,
    surface: SurfaceReference,
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
            calibration=calibration,
            surface=surface,
        )

    assert response.status == "failed"
    assert response.failure_reason == "projection_failed"
    assert response.sync_error_s == pytest.approx(0.0)
    assert response.message is not None
    assert "gimbal" in response.message.casefold()
