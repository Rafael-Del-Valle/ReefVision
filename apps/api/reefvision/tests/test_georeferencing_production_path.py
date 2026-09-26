"""Task 20: backend georeferencing production-path tests."""

from __future__ import annotations

import io
import json
from math import isfinite
from pathlib import Path

import pytest

from reefvision.api.routes import georeferenced_observations as georeferenced_observation_routes
from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.db.models import LabelClass, Project, VideoAsset, VideoTrack
from reefvision.db.session import create_database_engine, create_session_factory
from reefvision.geospatial.models import TelemetrySample
from reefvision.geospatial.synchronization import IndexedTelemetrySource, PreferredTelemetrySource
from reefvision.schemas.georeferenced_observation import BoundingBoxPixels
from reefvision.schemas.projects import ProjectUpdate
from reefvision.schemas.video_georeferencing_calibration import (
    VideoGeoreferencingCalibrationSetRequest,
)
from reefvision.services import video_assets as video_assets_module
from reefvision.services.georeferenced_observation_recomputation import (
    GeoreferencedObservationRecomputationService,
)
from reefvision.services.georeferenced_observations import (
    GeoReferencedObservationService,
)
from reefvision.services.projects import ProjectService
from reefvision.services.video_assets import VideoAssetService
from reefvision.services.video_georeferencing import VideoGeoreferencingService
from reefvision.services.video_georeferencing_calibration import (
    VideoGeoreferencingCalibrationService,
)
from reefvision.storage.projects import resolve_managed_project_path

TASK20_AIRDATA_CSV = (
    b"time(millisecond),latitude,longitude,height_above_takeoff(meters),"
    b"gimbal_heading(degrees),gimbal_pitch(degrees),gimbal_roll(degrees),"
    b"compass_heading(degrees)\n"
    b"10000,22.892814,-109.840571,83.4,265.1,-23.4,0,248.9\n"
    b"10100,22.892808,-109.840590,83.5,265.6,-23.4,0,249.3\n"
)

TASK20_MODERN_SRT = Path(__file__).parent / "fixtures" / "telemetry" / "modern.SRT"


def _task20_fake_video_metadata(
    _path: object,
) -> dict[str, float | int]:
    return {
        "width_px": 1000,
        "height_px": 800,
        "frame_count": 20,
        "fps": 10.0,
        "duration_seconds": 2.0,
    }


@pytest.fixture
def production_georeferencing_context(tmp_path: Path):
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
                gimbal_pitch_deg=-90.0,
                gimbal_roll_deg=roll,
                digital_zoom_ratio=digital_zoom_ratio,
            )
        ]
    )


def test_production_service_happy_path_creates_fresh_persisted_observation(
    production_georeferencing_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the real projection/hash/persistence path on a real DB."""
    (
        settings,
        factory,
        video_id,
    ) = production_georeferencing_context

    # Task 20A isolates the production projection/persistence stack.
    # Task 20B separately exercises the real persisted AirData/SRT
    # selection and fallback path.
    preferred = PreferredTelemetrySource(
        airdata=None,
        srt=_source(),
    )

    with factory() as session:
        georeferencing = VideoGeoreferencingService(
            session,
            settings,
        )

        monkeypatch.setattr(
            georeferencing.video_assets,
            "telemetry_source",
            lambda _: preferred,
        )

        bbox = BoundingBoxPixels(
            x_min=400.0,
            y_min=300.0,
            x_max=600.0,
            y_max=500.0,
        )

        observation = georeferencing.georeference_detection(
            video_id,
            frame_index=0,
            bbox=bbox,
        )

        configuration_hash = georeferencing.configuration_hash(video_id)

        persistence = GeoReferencedObservationService(session)

        record = persistence.persist(
            observation,
            configuration_hash=configuration_hash,
        )

        observation_id = record.id

        session.commit()

    # Reopen the database so assertions cover actual persisted
    # state rather than only the SQLAlchemy identity map.
    with factory() as session:
        persistence = GeoReferencedObservationService(session)

        stored = persistence.get(observation_id)

        restored = persistence.to_response(stored)

        summary = persistence.to_summary(stored)

        assert stored.video_id == video_id
        assert stored.frame_index == 0

        assert stored.configuration_hash == (configuration_hash)

        assert len(configuration_hash) == 64

        assert stored.is_stale is False
        assert stored.stale_reason is None
        assert stored.stale_at is None

        assert restored.id == observation.id

        assert str(restored.video_asset_id) == video_id

        assert restored.frame_index == 0

        assert restored.representative_pixel.method == "bbox_center"

        assert restored.representative_pixel.x == (pytest.approx(500.0))

        assert restored.representative_pixel.y == (pytest.approx(400.0))

        assert restored.bbox == bbox

        assert isfinite(restored.location.latitude_deg)

        assert isfinite(restored.location.longitude_deg)

        assert -90.0 <= restored.location.latitude_deg <= 90.0

        assert -180.0 <= restored.location.longitude_deg <= 180.0

        assert restored.location.crs == "EPSG:4326"

        assert restored.pose.platform.height_above_surface_m > 0.0

        assert restored.calibration.checksum_sha256 is not None

        assert len(restored.calibration.checksum_sha256) == 64

        assert restored.calibration.image_width_px == restored.frame_width_px

        assert restored.calibration.image_height_px == restored.frame_height_px

        assert restored.telemetry.source_type == "dji_srt"

        assert restored.telemetry.field_provenance is not None

        assert restored.telemetry.field_provenance["position_source"] == "dji_srt"

        assert restored.method.version == ("opencv-dji-enu-flat-wgs84-v1")

        assert restored.method.surface_model == ("local_horizontal_plane")

        assert restored.uncertainty.available is False
        assert restored.uncertainty.method == "not_estimated"

        assert summary.configuration_hash == (configuration_hash)

        assert summary.is_stale is False
        assert summary.stale_reason is None

        assert summary.location.latitude_deg == pytest.approx(restored.location.latitude_deg)

        assert summary.location.longitude_deg == pytest.approx(restored.location.longitude_deg)


def test_project_datum_change_invalidates_and_recomputes_observation(
    production_georeferencing_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise project-datum invalidation and real atomic recomputation."""
    (
        settings,
        factory,
        video_id,
    ) = production_georeferencing_context

    # Keep telemetry deterministic while testing the real DB,
    # project, projection, invalidation, persistence, hashing,
    # and recomputation services.
    preferred = PreferredTelemetrySource(
        airdata=None,
        srt=_source(),
    )

    monkeypatch.setattr(
        VideoAssetService,
        "telemetry_source",
        lambda self, _video_id: preferred,
    )

    # --------------------------------------------------------------
    # 1. Create and persist an initial fresh geographic observation.
    #
    # Deliberately use an off-center bbox so changing the effective
    # height can affect the projected location as well as provenance.
    # --------------------------------------------------------------

    with factory() as session:
        georeferencing = VideoGeoreferencingService(
            session,
            settings,
        )

        video = georeferencing.video_assets.get_record(video_id)

        project_id = video.project_id

        bbox = BoundingBoxPixels(
            x_min=600.0,
            y_min=300.0,
            x_max=700.0,
            y_max=400.0,
        )

        original = georeferencing.georeference_detection(
            video_id,
            frame_index=0,
            bbox=bbox,
        )

        original_hash = georeferencing.configuration_hash(video_id)

        persistence = GeoReferencedObservationService(session)

        original_record = persistence.persist(
            original,
            configuration_hash=original_hash,
        )

        original_id = original_record.id

        original_location = (
            original.location.latitude_deg,
            original.location.longitude_deg,
        )

        original_height = original.pose.platform.height_above_surface_m

        assert original_height > 0.0

        session.commit()

    # --------------------------------------------------------------
    # 2. Change the authoritative project datum/height.
    #
    # Keep the change safely smaller than the current effective
    # height so the synthetic projection remains physically valid
    # regardless of the sign convention used internally.
    # --------------------------------------------------------------

    height_delta = min(
        0.5,
        original_height / 4.0,
    )

    assert height_delta > 0.0

    with factory() as session:
        projects = ProjectService(
            session,
            settings,
        )

        project = projects.get_project(project_id)

        original_offset = project.georeference_height_offset_m

        updated_offset = original_offset + height_delta

        updated_project = projects.update_project(
            project_id,
            ProjectUpdate(
                georeference_height_offset_m=(updated_offset),
                georeference_height_evidence=("Task 20 production-path controlled datum update"),
            ),
        )

        assert updated_project.georeference_height_offset_m == pytest.approx(updated_offset)

        assert updated_project.georeference_height_evidence == (
            "Task 20 production-path controlled datum update"
        )

    # --------------------------------------------------------------
    # 3. The already-derived coordinate must now be stale.
    # --------------------------------------------------------------

    with factory() as session:
        persistence = GeoReferencedObservationService(session)

        stale = persistence.get(original_id)

        assert stale.is_stale is True

        assert stale.stale_reason == ("project_surface_reference_changed")

        assert stale.stale_at is not None

        assert stale.configuration_hash == (original_hash)

    # --------------------------------------------------------------
    # 4. Recompute through the real Task 19 production service.
    # --------------------------------------------------------------

    with factory() as session:
        result = GeoreferencedObservationRecomputationService(
            session,
            settings,
        ).recompute_video(video_id)

        assert result.invalidated_count == 0
        assert result.stale_count == 1
        assert result.recomputed_count == 1
        assert result.unchanged_count == 0

        assert result.configuration_hash is not None

        assert result.configuration_hash != (original_hash)

        assert len(result.configuration_hash) == 64

        assert len(result.replacements) == 1

        replacement = result.replacements[0]

        assert str(replacement.old_observation_id) == str(original_id)

        replacement_id = str(replacement.new_observation_id)

        assert replacement_id != str(original_id)

    # --------------------------------------------------------------
    # 5. Re-open the DB and prove immutable replacement semantics.
    # --------------------------------------------------------------

    with factory() as session:
        persistence = GeoReferencedObservationService(session)

        records = persistence.list_for_video(video_id)

        assert len(records) == 1

        replacement_record = records[0]

        assert str(replacement_record.id) == replacement_id

        assert replacement_record.is_stale is False
        assert replacement_record.stale_reason is None
        assert replacement_record.stale_at is None

        assert replacement_record.configuration_hash == result.configuration_hash

        assert replacement_record.configuration_hash != original_hash

        recomputed = persistence.to_response(replacement_record)

        assert recomputed.frame_index == 0
        assert recomputed.bbox == bbox

        assert recomputed.representative_pixel.method == "bbox_center"

        # The current bbox-center policy is reapplied rather
        # than freezing an old derived representative pixel.
        assert recomputed.representative_pixel.x == (pytest.approx(650.0))

        assert recomputed.representative_pixel.y == (pytest.approx(350.0))

        assert recomputed.pose.platform.height_above_surface_m != pytest.approx(original_height)

        coordinate_delta = max(
            abs(recomputed.location.latitude_deg - original_location[0]),
            abs(recomputed.location.longitude_deg - original_location[1]),
        )

        assert coordinate_delta > 0.0

        assert recomputed.location.crs == "EPSG:4326"


def test_persisted_airdata_is_preferred_over_srt_in_production_path(
    production_georeferencing_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Load real managed SRT/AirData files and prefer aligned AirData."""
    (
        settings,
        factory,
        seed_video_id,
    ) = production_georeferencing_context

    monkeypatch.setattr(
        video_assets_module,
        "_inspect_video",
        _task20_fake_video_metadata,
    )

    alignment_evidence = "Task 20 controlled flight-log/video start alignment"

    with factory() as session:
        assets = VideoAssetService(
            session,
            settings,
        )

        seed_video = assets.get_record(seed_video_id)

        with TASK20_MODERN_SRT.open("rb") as srt_stream:
            imported = assets.import_video(
                seed_video.project_id,
                filename="task20-airdata-preferred.mp4",
                stream=io.BytesIO(b"task20-airdata-preferred-video"),
                media_type="video/mp4",
                telemetry_filename="task20-airdata-preferred.SRT",
                telemetry_stream=srt_stream,
                airdata_filename="task20-Airdata.csv",
                airdata_stream=io.BytesIO(TASK20_AIRDATA_CSV),
                airdata_time_offset_s=10.0,
                airdata_time_offset_evidence=(alignment_evidence),
            )

        video_id = imported.id

        assert imported.telemetry.available is True
        assert imported.telemetry.source_type == "dji_srt"

        assert imported.airdata_telemetry.available is True

        assert imported.airdata_telemetry.source_type == "airdata"

        assert imported.airdata_telemetry.sample_count == 2

        assert imported.airdata_alignment.time_offset_s == pytest.approx(10.0)

        assert imported.airdata_alignment.evidence == alignment_evidence

        assert imported.telemetry.source_path is not None
        assert imported.airdata_telemetry.source_path is not None

        srt_path = resolve_managed_project_path(
            settings,
            imported.telemetry.source_path,
        )

        airdata_path = resolve_managed_project_path(
            settings,
            imported.airdata_telemetry.source_path,
        )

        assert srt_path.is_file()
        assert airdata_path.is_file()

    # Re-open the database and storage-backed telemetry source.
    with factory() as session:
        assets = VideoAssetService(
            session,
            settings,
        )

        persisted = assets.get(video_id)

        assert persisted.telemetry.available is True
        assert persisted.airdata_telemetry.available is True

        assert persisted.airdata_alignment.time_offset_s == pytest.approx(10.0)

        source = assets.telemetry_source(video_id)

        assert source is not None

        match = source.sample_for_frame(
            1,
            10.0,
        )

        assert match is not None

        # 10 Hz frame 1 is video time 0.1 s. The persisted
        # +10 s AirData alignment selects the 10.1 s row.
        assert match.sample.latitude == pytest.approx(22.892808)

        assert match.sample.longitude == pytest.approx(-109.840590)

        assert match.sample.relative_altitude_m == pytest.approx(83.5)

        assert match.sample.gimbal_yaw_deg == pytest.approx(265.6)

        assert match.sample.gimbal_pitch_deg == pytest.approx(-23.4)

        assert match.provenance is not None

        assert match.provenance.position_source == "airdata"

        assert match.provenance.relative_altitude_source == "airdata"

        assert match.provenance.gimbal_yaw_source == "airdata"

        assert match.provenance.gimbal_pitch_source == "airdata"

        assert match.provenance.gimbal_roll_source == "airdata"


def test_persisted_airdata_failure_falls_back_to_srt_in_production_path(
    production_georeferencing_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persist both sources, remove AirData, and prove real SRT fallback."""
    (
        settings,
        factory,
        seed_video_id,
    ) = production_georeferencing_context

    monkeypatch.setattr(
        video_assets_module,
        "_inspect_video",
        _task20_fake_video_metadata,
    )

    with factory() as session:
        assets = VideoAssetService(
            session,
            settings,
        )

        seed_video = assets.get_record(seed_video_id)

        with TASK20_MODERN_SRT.open("rb") as srt_stream:
            imported = assets.import_video(
                seed_video.project_id,
                filename="task20-srt-fallback.mp4",
                stream=io.BytesIO(b"task20-srt-fallback-video"),
                media_type="video/mp4",
                telemetry_filename="task20-srt-fallback.SRT",
                telemetry_stream=srt_stream,
                airdata_filename="task20-Airdata.csv",
                airdata_stream=io.BytesIO(TASK20_AIRDATA_CSV),
                airdata_time_offset_s=10.0,
                airdata_time_offset_evidence=("Task 20 controlled fallback test"),
            )

        video_id = imported.id

        assert imported.telemetry.available is True
        assert imported.airdata_telemetry.available is True

        assert imported.airdata_telemetry.source_path is not None

        airdata_path = resolve_managed_project_path(
            settings,
            imported.airdata_telemetry.source_path,
        )

        assert airdata_path.is_file()

        # Simulate a persisted AirData source becoming
        # unavailable after import. The SRT remains intact.
        airdata_path.unlink()

        assert not airdata_path.exists()

    # Use a fresh service instance so no source is cached.
    with factory() as session:
        assets = VideoAssetService(
            session,
            settings,
        )

        persisted = assets.get(video_id)

        # Database provenance still records that AirData was
        # imported; runtime loading must nevertheless degrade
        # safely to the persisted DJI SRT.
        assert persisted.airdata_telemetry.available is True

        assert persisted.telemetry.available is True

        source = assets.telemetry_source(video_id)

        assert source is not None

        fallback = source.sample_for_frame(
            1,
            10.0,
        )

        assert fallback is not None

        # This value comes from modern.SRT and proves the
        # fallback path did not silently reuse AirData.
        assert fallback.sample.latitude == pytest.approx(25.126)

        # Raw SRT does not carry PreferredTelemetrySource
        # field-selection provenance.
        assert fallback.provenance is None


def test_recomputation_rolls_back_partial_replacement_in_real_database(
    production_georeferencing_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mid-batch failure must leave every original stale row intact."""
    (
        settings,
        factory,
        video_id,
    ) = production_georeferencing_context

    preferred = PreferredTelemetrySource(
        airdata=None,
        srt=_source(),
    )

    monkeypatch.setattr(
        VideoAssetService,
        "telemetry_source",
        lambda self, _video_id: preferred,
    )

    # --------------------------------------------------------------
    # 1. Persist two genuine geographic derivations under the
    #    original configuration.
    # --------------------------------------------------------------

    with factory() as session:
        georeferencing = VideoGeoreferencingService(
            session,
            settings,
        )

        video = georeferencing.video_assets.get_record(video_id)

        project_id = video.project_id

        original_hash = georeferencing.configuration_hash(video_id)

        persistence = GeoReferencedObservationService(session)

        first = georeferencing.georeference_detection(
            video_id,
            frame_index=0,
            bbox=BoundingBoxPixels(
                x_min=350.0,
                y_min=300.0,
                x_max=450.0,
                y_max=400.0,
            ),
        )

        second = georeferencing.georeference_detection(
            video_id,
            frame_index=0,
            bbox=BoundingBoxPixels(
                x_min=550.0,
                y_min=300.0,
                x_max=650.0,
                y_max=400.0,
            ),
        )

        first_record = persistence.persist(
            first,
            configuration_hash=original_hash,
        )

        second_record = persistence.persist(
            second,
            configuration_hash=original_hash,
        )

        original_ids = {
            str(first_record.id),
            str(second_record.id),
        }

        original_height = first.pose.platform.height_above_surface_m

        assert original_height > 0.0

        session.commit()

    # --------------------------------------------------------------
    # 2. Change the authoritative project surface reference.
    #    This uses the production invalidation hook and makes both
    #    stored derivations stale.
    # --------------------------------------------------------------

    height_delta = min(
        0.25,
        original_height / 4.0,
    )

    assert height_delta > 0.0

    with factory() as session:
        projects = ProjectService(
            session,
            settings,
        )

        project = projects.get_project(project_id)

        projects.update_project(
            project_id,
            ProjectUpdate(
                georeference_height_offset_m=(project.georeference_height_offset_m + height_delta),
                georeference_height_evidence=("Task 20 rollback production test"),
            ),
        )

    with factory() as session:
        persistence = GeoReferencedObservationService(session)

        stale_before = persistence.list_for_video(video_id)

        assert len(stale_before) == 2

        assert {str(item.id) for item in stale_before} == original_ids

        assert all(item.is_stale for item in stale_before)

        assert all(item.configuration_hash == original_hash for item in stale_before)

    # --------------------------------------------------------------
    # 3. Let the first replacement project/persist normally, then
    #    fail the second projection. The production recomputation
    #    service must roll the whole transaction back.
    # --------------------------------------------------------------

    with factory() as session:
        recomputation = GeoreferencedObservationRecomputationService(
            session,
            settings,
        )

        real_georeference = recomputation.georeferencing.georeference_detection

        calls = 0

        def fail_second_projection(
            *args,
            **kwargs,
        ):
            nonlocal calls

            calls += 1

            if calls == 2:
                raise RuntimeError("Task 20 injected second-projection failure")

            return real_georeference(
                *args,
                **kwargs,
            )

        monkeypatch.setattr(
            recomputation.georeferencing,
            "georeference_detection",
            fail_second_projection,
        )

        with pytest.raises(
            RuntimeError,
            match=("Task 20 injected second-projection failure"),
        ):
            recomputation.recompute_video(video_id)

        assert calls == 2

    # --------------------------------------------------------------
    # 4. Re-open the database. The first staged replacement must
    #    have disappeared with the rollback, while both originals
    #    remain stale and unchanged.
    # --------------------------------------------------------------

    with factory() as session:
        persistence = GeoReferencedObservationService(session)

        after = persistence.list_for_video(video_id)

        assert len(after) == 2

        assert {str(item.id) for item in after} == original_ids

        assert all(item.is_stale for item in after)

        assert all(item.configuration_hash == original_hash for item in after)

        assert all(item.stale_reason == "project_surface_reference_changed" for item in after)


def test_production_geojson_export_uses_persisted_coordinates_without_recalculation(
    production_georeferencing_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Export real persisted observations as Point and LineString features."""
    (
        settings,
        factory,
        video_id,
    ) = production_georeferencing_context

    preferred = PreferredTelemetrySource(
        airdata=None,
        srt=_source(),
    )

    monkeypatch.setattr(
        VideoAssetService,
        "telemetry_source",
        lambda self, _video_id: preferred,
    )

    # --------------------------------------------------------------
    # 1. Build a real persisted track and two real geographic
    #    observations linked to it.
    # --------------------------------------------------------------

    with factory() as session:
        georeferencing = VideoGeoreferencingService(
            session,
            settings,
        )

        video = georeferencing.video_assets.get_record(video_id)

        project_id = video.project_id

        projects = ProjectService(
            session,
            settings,
        )

        classes = projects.list_classes(project_id)

        if classes:
            label_class = classes[0]
        else:
            # The synthetic georeferencing fixture may use a blank
            # project, so add the minimum authoritative class needed
            # for a real VideoTrack foreign-key relationship.
            label_class = LabelClass(
                project_id=project_id,
                class_index=0,
                display_order=0,
                name="Task 20 export class",
                scientific_name=None,
                state_name=None,
                description=None,
                display_color="#336699",
            )

            session.add(label_class)
            session.flush()

        track = VideoTrack(
            video_id=video_id,
            label_class_id=label_class.id,
            track_number=1,
            geometry_kind="bbox",
            keyframes_json=[
                {
                    "frame": 0,
                    "bbox": [
                        420.0,
                        340.0,
                        80.0,
                        80.0,
                    ],
                    "confidence": 0.91,
                },
                {
                    "frame": 1,
                    "bbox": [
                        540.0,
                        340.0,
                        80.0,
                        80.0,
                    ],
                    "confidence": 0.82,
                },
            ],
            interpolation="linear",
            status="verified",
            metadata_json={
                "source": "task20-production-export",
            },
        )

        session.add(track)
        session.flush()

        track_id = str(track.id)

        configuration_hash = georeferencing.configuration_hash(video_id)

        persistence = GeoReferencedObservationService(session)

        first = georeferencing.georeference_detection(
            video_id,
            frame_index=0,
            bbox=BoundingBoxPixels(
                x_min=420.0,
                y_min=340.0,
                x_max=500.0,
                y_max=420.0,
            ),
            track_id=track_id,
        )

        second = georeferencing.georeference_detection(
            video_id,
            frame_index=1,
            bbox=BoundingBoxPixels(
                x_min=540.0,
                y_min=340.0,
                x_max=620.0,
                y_max=420.0,
            ),
            track_id=track_id,
        )

        first_record = persistence.persist(
            first,
            configuration_hash=configuration_hash,
        )

        second_record = persistence.persist(
            second,
            configuration_hash=configuration_hash,
        )

        assert first_record.is_stale is False
        assert second_record.is_stale is False

        assert first_record.configuration_hash == configuration_hash

        assert second_record.configuration_hash == configuration_hash

        expected = [
            [
                first.location.longitude_deg,
                first.location.latitude_deg,
            ],
            [
                second.location.longitude_deg,
                second.location.latitude_deg,
            ],
        ]

        observation_ids = {
            str(first_record.id),
            str(second_record.id),
        }

        class_name = str(label_class.name)

        session.commit()

    # --------------------------------------------------------------
    # 2. Export must never invoke projection again. Any hidden
    #    recalculation will make this test fail immediately.
    # --------------------------------------------------------------

    recalculation_calls = 0

    def forbidden_recalculation(
        *args,
        **kwargs,
    ):
        nonlocal recalculation_calls

        recalculation_calls += 1

        raise AssertionError("GIS export must not recalculate geographic coordinates")

    monkeypatch.setattr(
        VideoGeoreferencingService,
        "georeference_detection",
        forbidden_recalculation,
    )

    with factory() as session:
        response = georeferenced_observation_routes.export_video_geographic_observations(
            video_id,
            session,
            export_format="geojson",
        )

    assert recalculation_calls == 0

    assert response.status_code == 200
    assert response.media_type == "application/geo+json"

    assert response.headers["cache-control"] == "no-store"

    assert "reefvision-geographic-observations.geojson" in response.headers["content-disposition"]

    document = json.loads(response.body.decode("utf-8"))

    assert document["type"] == "FeatureCollection"

    features = document["features"]

    points = [feature for feature in features if feature["geometry"]["type"] == "Point"]

    lines = [feature for feature in features if feature["geometry"]["type"] == "LineString"]

    assert len(points) == 2
    assert len(lines) == 1

    points.sort(key=lambda feature: feature["properties"]["frame_index"])

    assert {str(feature["id"]) for feature in points} == observation_ids

    for point, expected_coordinates in zip(
        points,
        expected,
        strict=True,
    ):
        assert point["properties"]["feature_kind"] == "observation"

        assert point["properties"]["track_id"] == track_id

        assert point["properties"]["crs"] == "EPSG:4326"

        assert point["properties"]["class_name"] == class_name

        assert point["geometry"]["coordinates"] == pytest.approx(expected_coordinates)

    assert points[0]["properties"]["confidence"] == pytest.approx(0.91)

    assert points[1]["properties"]["confidence"] == pytest.approx(0.82)

    assert points[0]["properties"]["confidence_status"] == "exact_keyframe"

    assert points[1]["properties"]["confidence_status"] == "exact_keyframe"

    line = lines[0]

    assert line["id"] == f"track:{track_id}"

    assert line["properties"]["feature_kind"] == "track"

    assert line["properties"]["track_id"] == track_id

    assert line["properties"]["observation_count"] == 2

    assert line["properties"]["frame_indices"] == [0, 1]

    assert len(line["geometry"]["coordinates"]) == 2

    for actual, expected_coordinates in zip(
        line["geometry"]["coordinates"],
        expected,
        strict=True,
    ):
        assert actual == pytest.approx(expected_coordinates)


def test_calibration_change_invalidates_and_recomputes_observation(
    production_georeferencing_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real calibration change must stale and replace old coordinates."""
    (
        settings,
        factory,
        video_id,
    ) = production_georeferencing_context

    preferred = PreferredTelemetrySource(
        airdata=None,
        srt=_source(),
    )

    monkeypatch.setattr(
        VideoAssetService,
        "telemetry_source",
        lambda self, _video_id: preferred,
    )

    # --------------------------------------------------------------
    # 1. Persist a real geographic observation under the current
    #    camera calibration.
    # --------------------------------------------------------------

    with factory() as session:
        georeferencing = VideoGeoreferencingService(
            session,
            settings,
        )

        original_calibration = georeferencing.calibrations.get(video_id)

        original_hash = georeferencing.configuration_hash(video_id)

        observation = georeferencing.georeference_detection(
            video_id,
            frame_index=0,
            bbox=BoundingBoxPixels(
                x_min=650.0,
                y_min=350.0,
                x_max=750.0,
                y_max=450.0,
            ),
        )

        persistence = GeoReferencedObservationService(session)

        record = persistence.persist(
            observation,
            configuration_hash=original_hash,
        )

        original_id = str(record.id)

        original_location = (
            observation.location.latitude_deg,
            observation.location.longitude_deg,
        )

        original_checksum = original_calibration.checksum_sha256

        original_revision = original_calibration.calibration_revision

        session.commit()

    # --------------------------------------------------------------
    # 2. Change a real intrinsic parameter. Keep resolution and all
    #    other persisted provenance unchanged.
    # --------------------------------------------------------------

    with factory() as session:
        calibration_service = VideoGeoreferencingCalibrationService(session)

        updated_calibration = calibration_service.set(
            video_id,
            VideoGeoreferencingCalibrationSetRequest(
                width_px=original_calibration.width_px,
                height_px=original_calibration.height_px,
                fx_px=(original_calibration.fx_px * 1.05),
                fy_px=original_calibration.fy_px,
                cx_px=original_calibration.cx_px,
                cy_px=original_calibration.cy_px,
                distortion_coefficients=(original_calibration.distortion_coefficients),
                digital_zoom_ratio=(original_calibration.digital_zoom_ratio),
                camera_mode=(original_calibration.camera_mode),
                source=("Task 20 controlled calibration update"),
                evidence=("Production-path calibration invalidation/recomputation test"),
            ),
        )

        assert updated_calibration.calibration_revision == original_revision + 1

        assert updated_calibration.checksum_sha256 != original_checksum

    # --------------------------------------------------------------
    # 3. The calibration write hook must have marked the previous
    #    scientific derivation stale immediately.
    # --------------------------------------------------------------

    with factory() as session:
        persistence = GeoReferencedObservationService(session)

        records = persistence.list_for_video(video_id)

        assert len(records) == 1

        stale = records[0]

        assert str(stale.id) == original_id
        assert stale.is_stale is True

        assert stale.stale_reason == "georeferencing_calibration_changed"

        assert stale.stale_at is not None

        assert stale.configuration_hash == original_hash

    # --------------------------------------------------------------
    # 4. Recompute through the production service.
    # --------------------------------------------------------------

    with factory() as session:
        result = GeoreferencedObservationRecomputationService(
            session,
            settings,
        ).recompute_video(video_id)

        assert result.invalidated_count == 0
        assert result.stale_count == 1
        assert result.recomputed_count == 1
        assert result.unchanged_count == 0

        assert result.configuration_hash is not None
        assert len(result.configuration_hash) == 64

        assert result.configuration_hash != original_hash

        assert len(result.replacements) == 1

        replacement = result.replacements[0]

        assert str(replacement.old_observation_id) == original_id

        assert str(replacement.new_observation_id) != original_id

    # --------------------------------------------------------------
    # 5. The old row must be gone and the replacement must be fresh,
    #    fingerprinted, and tied to the updated calibration.
    # --------------------------------------------------------------

    with factory() as session:
        persistence = GeoReferencedObservationService(session)

        records = persistence.list_for_video(video_id)

        assert len(records) == 1

        fresh = records[0]

        assert str(fresh.id) != original_id
        assert fresh.is_stale is False
        assert fresh.stale_reason is None
        assert fresh.stale_at is None

        assert fresh.configuration_hash == result.configuration_hash

        reconstructed = persistence.to_response(fresh)

        assert reconstructed.calibration.checksum_sha256 == updated_calibration.checksum_sha256

        assert reconstructed.calibration.calibration_version == str(
            updated_calibration.calibration_revision
        )

        assert reconstructed.representative_pixel.method == "bbox_center"

        assert reconstructed.representative_pixel.x == pytest.approx(700.0)

        assert reconstructed.representative_pixel.y == pytest.approx(400.0)

        new_location = (
            reconstructed.location.latitude_deg,
            reconstructed.location.longitude_deg,
        )

        coordinate_change = max(
            abs(new_location[0] - original_location[0]),
            abs(new_location[1] - original_location[1]),
        )

        assert coordinate_change > 0.0

        assert reconstructed.location.crs == "EPSG:4326"
