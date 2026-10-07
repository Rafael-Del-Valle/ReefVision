"""Task 19D production georeferencing configuration identity."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from reefvision.domain.errors import ValidationError
from reefvision.services.video_georeferencing import (
    VideoGeoreferencingService,
)


class FakeSession:
    def __init__(self, project: object) -> None:
        self.project = project

    def get(
        self,
        model: type[object],
        _identifier: str,
    ) -> object | None:
        if model.__name__ == "Project":
            return self.project

        return None


class VideoAssets:
    def __init__(self, video: object) -> None:
        self.video = video

    def get_record(self, _video_id: str) -> object:
        return self.video


class Calibrations:
    def __init__(self, calibration: object) -> None:
        self.calibration = calibration

    def get(self, _video_id: str) -> object:
        return self.calibration


def service(
    *,
    alignment_offset: float = 1.25,
    alignment_evidence: str | None = ("Independent synchronization"),
) -> VideoGeoreferencingService:
    video = SimpleNamespace(
        id="video-1",
        project_id="project-1",
        sha256="a" * 64,
        fps=29.97,
        metadata_json={
            "telemetry": {
                "source_path": ("project/videos/telemetry/video-1.srt"),
                "sample_count": 500,
            },
            "airdata_telemetry": {
                "source_path": ("project/videos/telemetry/video-1.airdata.csv"),
                "sample_count": 600,
            },
            "airdata_alignment": {
                "time_offset_s": alignment_offset,
                "evidence": alignment_evidence,
            },
        },
    )

    project = SimpleNamespace(
        georeference_height_offset_m=5.0,
        georeference_height_evidence=("Surveyed takeoff height"),
    )

    calibration = SimpleNamespace(
        checksum_sha256="b" * 64,
        calibration_revision=3,
    )

    instance = object.__new__(VideoGeoreferencingService)

    instance.session = FakeSession(project)  # type: ignore[assignment]
    instance.video_assets = VideoAssets(video)  # type: ignore[assignment]
    instance.calibrations = Calibrations(  # type: ignore[assignment]
        calibration
    )

    return instance


def test_current_configuration_hash_is_deterministic() -> None:
    first = service().configuration_hash("video-1")
    second = service().configuration_hash("video-1")

    assert first == second
    assert len(first) == 64


def test_alignment_change_changes_production_hash() -> None:
    first = service(
        alignment_offset=1.25,
    ).configuration_hash("video-1")

    second = service(
        alignment_offset=1.50,
    ).configuration_hash("video-1")

    assert first != second


def test_sync_tolerance_changes_production_hash() -> None:
    instance = service()

    first = instance.configuration_hash(
        "video-1",
        max_delta_s=0.1,
    )

    second = instance.configuration_hash(
        "video-1",
        max_delta_s=0.2,
    )

    assert first != second


def test_invalid_alignment_metadata_is_rejected() -> None:
    instance = service()

    video_assets = cast(VideoAssets, instance.video_assets)
    video = cast(SimpleNamespace, video_assets.video)
    video.metadata_json["airdata_alignment"] = "invalid"

    with pytest.raises(
        ValidationError,
        match="AirData alignment metadata",
    ):
        instance.configuration_hash("video-1")
