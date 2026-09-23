from __future__ import annotations

from pathlib import Path

from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.db.models import (
    GeoReferencedObservation,
    LabelClass,
    Project,
    VideoAsset,
    VideoTrack,
)
from reefvision.db.session import (
    create_database_engine,
    create_session_factory,
)


def test_geo_referenced_observation_relationships(
    tmp_path: Path,
) -> None:
    settings = Settings(
        env="test",
        data_dir=tmp_path / "data",
        database_url=(f"sqlite:///{(tmp_path / 'geo-observations.db').as_posix()}"),
        background_worker_enabled=False,
    )

    settings.ensure_directories()

    engine = create_database_engine(settings)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)

    try:
        with factory() as session:
            project = Project(
                name="Geo persistence",
                slug="geo-persistence",
                storage_root="projects/geo-persistence",
            )
            session.add(project)
            session.flush()

            label = LabelClass(
                project_id=project.id,
                class_index=0,
                display_order=0,
                name="fish",
                display_color="#336699",
            )
            session.add(label)

            video = VideoAsset(
                project_id=project.id,
                original_filename="test.mp4",
                managed_path=("projects/geo-persistence/videos/originals/test.mp4"),
                sha256="a" * 64,
                media_type="video/mp4",
                width_px=1920,
                height_px=1080,
                frame_count=300,
                fps=30.0,
                duration_seconds=10.0,
                metadata_json={},
            )
            session.add(video)
            session.flush()

            track = VideoTrack(
                video_id=video.id,
                label_class_id=label.id,
                track_number=1,
                geometry_kind="bbox",
                keyframes_json=[],
                interpolation="linear",
                status="machine_generated",
            )
            session.add(track)
            session.flush()

            observation = GeoReferencedObservation(
                project_id=project.id,
                video_id=video.id,
                track_id=track.id,
                detection_id=None,
                schema_version="1.0.0",
                frame_index=12,
                frame_width_px=1920,
                frame_height_px=1080,
                bbox_x_min=100.0,
                bbox_y_min=200.0,
                bbox_x_max=300.0,
                bbox_y_max=400.0,
                representative_pixel_x=200.0,
                representative_pixel_y=300.0,
                representative_pixel_method="bbox_center",
                frame_time_s=0.4,
                latitude_deg=32.75,
                longitude_deg=-79.93,
                crs="EPSG:4326",
                method_name="camera_ray_surface_intersection",
                method_version="opencv-dji-enu-flat-wgs84-v1",
                calibration_id="sha256:" + ("b" * 64),
                calibration_version="1",
                calibration_checksum_sha256="b" * 64,
                telemetry_source_id="test.srt",
                telemetry_source_type="dji_srt",
                telemetry_sample_index=12,
                signed_time_delta_ms=0.0,
                uncertainty_available=False,
                payload_json={
                    "schema_version": "1.0.0",
                    "frame_index": 12,
                },
            )

            session.add(observation)
            session.commit()

            observation_id = observation.id

        with factory() as session:
            persisted = session.get(
                GeoReferencedObservation,
                observation_id,
            )

            assert persisted is not None

            assert persisted.project.slug == "geo-persistence"
            assert persisted.video.original_filename == "test.mp4"
            assert persisted.track is not None
            assert persisted.track.track_number == 1

            assert persisted in (persisted.project.geo_referenced_observations)
            assert persisted in (persisted.video.geo_referenced_observations)
            assert persisted in (persisted.track.geo_referenced_observations)

            assert persisted.frame_index == 12
            assert persisted.latitude_deg == 32.75
            assert persisted.longitude_deg == -79.93
            assert persisted.representative_pixel_method == ("bbox_center")

            foreign_keys = {
                fk.target_fullname for fk in (GeoReferencedObservation.__table__.foreign_keys)
            }

            assert foreign_keys == {
                "projects.id",
                "videos.id",
                "video_tracks.id",
            }

    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
