from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.db.models import (
    LabelClass,
    Project,
    VideoAsset,
    VideoTrack,
)
from reefvision.db.session import (
    create_database_engine,
    create_session_factory,
)
from reefvision.schemas.georeferenced_observation import (
    GeoReferencedObservation,
)
from reefvision.services.georeferenced_observations import (
    GeoReferencedObservationService,
)


def test_task12b_persist_and_query_observation(
    tmp_path: Path,
) -> None:
    settings = Settings(
        env="test",
        data_dir=tmp_path / "data",
        database_url=(f"sqlite:///{(tmp_path / 'task12b.db').as_posix()}"),
        background_worker_enabled=False,
    )

    settings.ensure_directories()

    engine = create_database_engine(settings)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)

    try:
        with factory() as session:
            project = Project(
                name="Task 12B",
                slug="task-12b",
                storage_root="projects/task-12b",
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
                original_filename="fish.mp4",
                managed_path=("projects/task-12b/videos/originals/fish.mp4"),
                sha256="a" * 64,
                media_type="video/mp4",
                width_px=100,
                height_px=60,
                frame_count=30,
                fps=10.0,
                duration_seconds=3.0,
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

            observation = GeoReferencedObservation.model_validate(
                {
                    "id": uuid4(),
                    "project_id": UUID(project.id),
                    "video_asset_id": UUID(video.id),
                    "detection_id": None,
                    "track_id": UUID(track.id),
                    "frame_index": 12,
                    "frame_width_px": 100,
                    "frame_height_px": 60,
                    "bbox": {
                        "x_min": 10.0,
                        "y_min": 12.0,
                        "x_max": 30.0,
                        "y_max": 20.0,
                    },
                    "representative_pixel": {
                        "x": 20.0,
                        "y": 16.0,
                        "method": "bbox_center",
                    },
                    "timestamp": {
                        "frame_time_s": 1.2,
                        "utc": None,
                        "source": "frame_index_fps",
                        "fps": 10.0,
                    },
                    "pose": {
                        "platform": {
                            "latitude_deg": 32.75,
                            "longitude_deg": -79.93,
                            "altitude_m": 100.0,
                            "altitude_datum": "relative_takeoff",
                            "height_above_surface_m": 105.0,
                            "yaw_deg": None,
                            "pitch_deg": None,
                            "roll_deg": None,
                            "heading_reference": "unknown",
                        },
                        "camera": {
                            "yaw_deg": 0.0,
                            "pitch_deg": -90.0,
                            "roll_deg": 0.0,
                            "orientation_source": "gimbal_telemetry",
                        },
                    },
                    "calibration": {
                        "calibration_id": "sha256:" + ("b" * 64),
                        "calibration_version": "1",
                        "checksum_sha256": "b" * 64,
                        "camera_model": "synthetic-wide",
                        "image_width_px": 100,
                        "image_height_px": 60,
                        "focal_length_x_px": 50.0,
                        "focal_length_y_px": 50.0,
                        "principal_point_x_px": 50.0,
                        "principal_point_y_px": 30.0,
                        "distortion_model": "none",
                        "zoom_state": 1.0,
                    },
                    "telemetry": {
                        "source_id": "synthetic.srt",
                        "source_type": "dji_srt",
                        "sample_index": 12,
                        "synchronization_method": "nearest",
                        "telemetry_time_s": 1.2,
                        "telemetry_utc": None,
                        "signed_time_delta_ms": 0.0,
                        "absolute_time_error_ms": 0.0,
                        "within_sync_tolerance": True,
                        "sync_tolerance_ms": 100.0,
                        "field_provenance": {
                            "position_source": "dji_srt",
                        },
                    },
                    "location": {
                        "latitude_deg": 32.7501,
                        "longitude_deg": -79.9299,
                    },
                    "uncertainty": {
                        "available": False,
                        "method": "not_estimated",
                        "reason_unavailable": (
                            "Formal uncertainty propagation not yet implemented."
                        ),
                    },
                    "method": {
                        "version": "opencv-dji-enu-flat-wgs84-v1",
                        "surface_model": "local_horizontal_plane",
                        "representative_pixel_policy_version": "1.0.0",
                        "synchronization_version": ("nearest-frame-time-v1"),
                        "pose_convention_version": ("absolute-gimbal-ned-to-enu-v1"),
                    },
                    "created_at": datetime.now(UTC),
                }
            )

            persistence = GeoReferencedObservationService(session)

            stored = persistence.persist(observation)

            # The tracking job owns the transaction in production.
            session.commit()

            assert stored.id == str(observation.id)

            by_video = persistence.list_for_video(video.id)
            by_track = persistence.list_for_track(track.id)
            by_frame = persistence.list_for_frame(
                video.id,
                12,
            )

            assert [item.id for item in by_video] == [str(observation.id)]
            assert [item.id for item in by_track] == [str(observation.id)]
            assert [item.id for item in by_frame] == [str(observation.id)]

            persisted = by_video[0]

            assert persisted.project_id == project.id
            assert persisted.video_id == video.id
            assert persisted.track_id == track.id
            assert persisted.frame_index == 12

            assert persisted.bbox_x_min == 10.0
            assert persisted.bbox_y_min == 12.0
            assert persisted.bbox_x_max == 30.0
            assert persisted.bbox_y_max == 20.0

            assert persisted.representative_pixel_x == 20.0
            assert persisted.representative_pixel_y == 16.0
            assert persisted.representative_pixel_method == "bbox_center"

            assert persisted.latitude_deg == 32.7501
            assert persisted.longitude_deg == -79.9299
            assert persisted.crs == "EPSG:4326"

            assert persisted.method_name == "camera_ray_surface_intersection"
            assert persisted.method_version == ("opencv-dji-enu-flat-wgs84-v1")

            assert persisted.payload_json["track_id"] == track.id
            assert persisted.payload_json["representative_pixel"]["method"] == "bbox_center"

            # Tracking reruns use this to prevent duplicate map points.
            persistence.delete_for_tracks([track.id])
            session.commit()

            assert persistence.list_for_video(video.id) == []
            assert persistence.list_for_track(track.id) == []
            assert (
                persistence.list_for_frame(
                    video.id,
                    12,
                )
                == []
            )

    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
