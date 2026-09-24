"""Task 19C persistence state for derived geographic observations."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from reefvision.domain.errors import ValidationError
from reefvision.services.georeferenced_observations import (
    GeoReferencedObservationService,
)


class FakeSession:
    def __init__(self, video: object) -> None:
        self.video = video
        self.added: object | None = None

    def get(
        self,
        model: type[object],
        _identifier: str,
    ) -> object | None:
        if model.__name__ == "VideoAsset":
            return self.video

        return None

    def add(self, record: object) -> None:
        self.added = record


class FakeObservation:
    def __init__(
        self,
        *,
        project_id: str,
        video_id: str,
    ) -> None:
        self.id = uuid4()
        self.project_id = project_id
        self.video_asset_id = video_id
        self.track_id = None
        self.detection_id = None

        self.schema_version = "1.0.0"

        self.frame_index = 2
        self.frame_width_px = 100
        self.frame_height_px = 60

        self.bbox = SimpleNamespace(
            x_min=10.0,
            y_min=12.0,
            x_max=30.0,
            y_max=20.0,
        )

        self.representative_pixel = SimpleNamespace(
            x=20.0,
            y=16.0,
            method="bbox_center",
        )

        self.timestamp = SimpleNamespace(
            frame_time_s=0.2,
        )

        self.location = SimpleNamespace(
            latitude_deg=32.75,
            longitude_deg=-79.93,
            crs="EPSG:4326",
        )

        self.method = SimpleNamespace(
            name="camera_ray_surface_intersection",
            version="opencv-dji-enu-flat-wgs84-v1",
        )

        self.calibration = SimpleNamespace(
            calibration_id="sha256:" + ("b" * 64),
            calibration_version="3",
            checksum_sha256="b" * 64,
        )

        self.telemetry = SimpleNamespace(
            source_id="test.srt",
            source_type="dji_srt",
            sample_index=2,
            signed_time_delta_ms=0.0,
        )

        self.uncertainty = SimpleNamespace(
            available=False,
        )

        self.created_at = datetime.now(UTC)

    def model_dump(self, *, mode: str) -> dict[str, object]:
        assert mode == "json"

        return {
            "id": str(self.id),
            "project_id": self.project_id,
            "video_asset_id": self.video_asset_id,
        }


def context() -> tuple[
    GeoReferencedObservationService,
    FakeObservation,
]:
    project_id = str(uuid4())
    video_id = str(uuid4())

    video = SimpleNamespace(
        id=video_id,
        project_id=project_id,
        frame_count=100,
        width_px=100,
        height_px=60,
    )

    session = FakeSession(video)

    service = GeoReferencedObservationService(session)

    return (
        service,
        FakeObservation(
            project_id=project_id,
            video_id=video_id,
        ),
    )


def test_missing_configuration_hash_is_conservatively_stale() -> None:
    service, observation = context()

    record = service.persist(observation)  # type: ignore[arg-type]

    assert record.configuration_hash is None
    assert record.is_stale is True
    assert record.stale_reason == "configuration_not_recorded"
    assert record.stale_at is not None


def test_valid_configuration_hash_records_fresh_result() -> None:
    service, observation = context()

    record = service.persist(  # type: ignore[arg-type]
        observation,
        configuration_hash="A" * 64,
    )

    assert record.configuration_hash == "a" * 64
    assert record.is_stale is False
    assert record.stale_reason is None
    assert record.stale_at is None


def test_invalid_configuration_hash_is_rejected() -> None:
    service, observation = context()

    with pytest.raises(
        ValidationError,
        match="64-character SHA-256",
    ):
        service.persist(  # type: ignore[arg-type]
            observation,
            configuration_hash="not-a-hash",
        )


def test_summary_exposes_persistence_state() -> None:
    service, observation = context()

    record = service.persist(  # type: ignore[arg-type]
        observation,
        configuration_hash="c" * 64,
    )

    summary = service.to_summary(record)

    assert str(summary.configuration_hash) == "c" * 64
    assert summary.is_stale is False
    assert summary.stale_reason is None
    assert summary.stale_at is None
