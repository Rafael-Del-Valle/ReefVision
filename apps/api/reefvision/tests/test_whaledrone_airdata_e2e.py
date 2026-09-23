"""End-to-end WhaleDrone AirData persistence and georeferencing validation."""

from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median

import pytest

from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.db.session import create_database_engine, create_session_factory
from reefvision.geospatial.geodesy import geodesic_distance_m
from reefvision.geospatial.projection import SurfaceReference
from reefvision.geospatial.synchronization import IndexedTelemetrySource
from reefvision.geospatial.validation import (
    GeoreferenceValidationPoint,
    evaluate_georeferencing,
)
from reefvision.schemas.projects import ProjectCreate
from reefvision.services import video_assets as video_assets_module
from reefvision.services.projects import ProjectService
from reefvision.services.video_assets import VideoAssetService
from reefvision.storage.georeferencing import load_camera_calibration
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.storage.telemetry import read_airdata_stream, read_srt_stream
from reefvision.tests.whaledrone import get_whaledrone_root

FPS_FALLBACK = 29.97002997002997
AIRDATA_NAME = "Jan-16th-2026-02-49PM-Flight-Airdata.csv"
ANNOTATION_NAME = "annotations_Jan-16th-2026-02-49PM-Flight-Airdata.csv"
CLIPS: dict[str, dict[str, str | int]] = {
    "0001": {
        "video": "DJI_20260116154954_0001_V.MP4",
        "dvm_video": "yggdln0thMY.mp4",
        "expected_unique_frames": 44,
    },
    "0003": {
        "video": "DJI_20260116155837_0003_V.MP4",
        "dvm_video": "6MQWPNj0SkQ.mp4",
        "expected_unique_frames": 58,
    },
}
_VIDEO_CLOCK = re.compile(r"DJI_(\d{14})_")
_CET = timezone(timedelta(hours=1))


def _blank(value: object) -> bool:
    return value is None or str(value).strip().casefold() in {"", "na", "nan"}


def _basename(value: object) -> str:
    return str(value or "").replace("\\", "/").rsplit("/", 1)[-1]


def _parse_utc(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.removesuffix(" UTC").replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _video_start_utc(video_name: str) -> datetime:
    match = _VIDEO_CLOCK.search(video_name)
    if match is None:
        raise AssertionError(f"Cannot parse DJI clock from {video_name}")
    local = datetime.strptime(match.group(1), "%Y%m%d%H%M%S").replace(tzinfo=_CET)
    return local.astimezone(UTC)


def _derive_airdata_offset(
    airdata_path: Path,
    video_name: str,
) -> tuple[float, dict[str, float]]:
    """Anchor video time to AirData flight time from the flight-start UTC stamp."""

    video_start = _video_start_utc(video_name)
    first_timestamp: datetime | None = None
    first_flight_time_s: float | None = None
    timestamp_count = 0

    with airdata_path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            timestamp = _parse_utc(row.get("datetime(utc)"))
            if timestamp is None:
                continue
            try:
                flight_time_s = float(row["time(millisecond)"]) / 1000.0
            except (KeyError, TypeError, ValueError):
                continue
            timestamp_count += 1
            if first_timestamp is None:
                first_timestamp = timestamp
                first_flight_time_s = flight_time_s

    if first_timestamp is None or first_flight_time_s is None:
        raise AssertionError("AirData flight-start UTC timestamp is unavailable")

    offset = first_flight_time_s + (video_start - first_timestamp).total_seconds()
    return offset, {
        "timestamp_rows_observed": float(timestamp_count),
        "first_airdata_datetime_utc_epoch_s": first_timestamp.timestamp(),
        "first_airdata_flight_time_s": first_flight_time_s,
        "video_start_utc_epoch_s": video_start.timestamp(),
        "initial_timestamp_offset_s": offset,
    }


def _find_video(root: Path, video_name: str) -> Path | None:
    candidates = [
        path
        for path in (root / "videos").rglob(video_name)
        if path.is_file()
    ]
    if len(candidates) > 1:
        raise AssertionError(f"Ambiguous source video locations for {video_name}")
    return candidates[0] if candidates else None


def _load_points(
    annotation_path: Path,
    dvm_video: str,
    *,
    srt_frame_count: int,
) -> tuple[list[GeoreferenceValidationPoint], dict[str, dict[str, float | None]], int]:
    points: list[GeoreferenceValidationPoint] = []
    reference: dict[str, dict[str, float | None]] = {}
    excluded_frames: set[int] = set()
    with annotation_path.open(encoding="utf-8-sig", newline="") as stream:
        for line, row in enumerate(csv.DictReader(stream), start=2):
            if _basename(row.get("video")) != dvm_video or not _blank(row.get("length")):
                continue
            frame = int(row["frame"])
            if frame < 0 or frame >= srt_frame_count:
                excluded_frames.add(frame)
                continue
            point_id = f"{line}:{row.get('name', '')}"
            height = None if _blank(row.get("height")) else float(row["height"])
            pitch = None if _blank(row.get("pitch")) else float(row["pitch"])
            yaw = None if _blank(row.get("yaw")) else float(row["yaw"])
            points.append(
                GeoreferenceValidationPoint(
                    point_id=point_id,
                    source_video=dvm_video,
                    frame_index=frame,
                    pixel_x=float(row["image_x"]),
                    pixel_y=float(row["image_y"]),
                    latitude=float(row["lat"]),
                    longitude=float(row["lon"]),
                    reference_height_m=height,
                    reference_pitch_deg=pitch,
                    object_id=row.get("name"),
                    source_frame_number=row.get("frame"),
                    source_time_value=row.get("time"),
                )
            )
            reference[point_id] = {"height_m": height, "yaw_deg": yaw}
    if not points:
        raise AssertionError(f"No valid DVM point annotations for {dvm_video}")
    return points, reference, len(excluded_frames)


def _angle_error_deg(actual: float, expected: float) -> float:
    return abs((actual - expected + 180.0) % 360.0 - 180.0)


def _source_alignment_score(
    *,
    airdata: IndexedTelemetrySource,
    srt_samples: list,
    offset_s: float,
) -> tuple[float, float, float, int] | None:
    heading_errors: list[float] = []
    position_errors: list[float] = []
    for srt_sample in srt_samples:
        air_match = airdata.sample_for_time(srt_sample.time_s + offset_s)
        if air_match is None:
            continue
        air_sample = air_match.sample
        if (
            srt_sample.gimbal_yaw_deg is not None
            and air_sample.aircraft_yaw_deg is not None
        ):
            heading_errors.append(
                _angle_error_deg(
                    air_sample.aircraft_yaw_deg,
                    srt_sample.gimbal_yaw_deg,
                )
            )
        if (
            srt_sample.latitude is not None
            and srt_sample.longitude is not None
            and air_sample.latitude is not None
            and air_sample.longitude is not None
        ):
            position_errors.append(
                geodesic_distance_m(
                    srt_sample.latitude,
                    srt_sample.longitude,
                    air_sample.latitude,
                    air_sample.longitude,
                )
            )
    if len(heading_errors) < 20 or len(position_errors) < 20:
        return None
    return (
        median(heading_errors),
        median(position_errors),
        mean(heading_errors),
        min(len(heading_errors), len(position_errors)),
    )


def _refine_airdata_offset_from_source_telemetry(
    *,
    airdata: IndexedTelemetrySource,
    srt: IndexedTelemetrySource,
    initial_offset_s: float,
) -> tuple[float, dict[str, float]]:
    """Align AirData to video using source telemetry only, never DVM outputs."""

    comparisons = [
        sample
        for sample in srt.samples[::300]
        if sample.gimbal_yaw_deg is not None
        and sample.latitude is not None
        and sample.longitude is not None
    ]
    if len(comparisons) < 20:
        raise AssertionError("WhaleDrone SRT lacks enough source telemetry for alignment")

    # Require the complete SRT clip to fit within the AirData flight-time span.
    air_min = airdata.samples[0].time_s
    air_max = airdata.samples[-1].time_s
    srt_min = srt.samples[0].time_s
    srt_max = srt.samples[-1].time_s
    offset_min = air_min - srt_min
    offset_max = air_max - srt_max
    if offset_max < offset_min:
        raise AssertionError("AirData flight log is shorter than the SRT clip")

    def search(
        start_s: float,
        end_s: float,
        step_s: float,
        *,
        current: tuple[float, float, float, float, int] | None = None,
    ) -> tuple[float, float, float, float, int] | None:
        best = current
        steps = round((end_s - start_s) / step_s)
        for index in range(steps + 1):
            offset_s = start_s + index * step_s
            if not offset_min <= offset_s <= offset_max:
                continue
            score = _source_alignment_score(
                airdata=airdata,
                srt_samples=comparisons,
                offset_s=offset_s,
            )
            if score is None:
                continue
            median_heading, median_position, mean_heading, count = score
            candidate = (
                median_heading,
                median_position,
                mean_heading,
                offset_s,
                count,
            )
            if best is None or candidate[:3] < best[:3]:
                best = candidate
        return best

    # Hierarchical search keeps the alignment source-only while avoiding millions
    # of repeated telemetry lookups across the full flight.
    best = search(offset_min, offset_max, 1.0)
    if best is None:
        raise AssertionError("Could not coarsely align AirData and SRT source telemetry")

    coarse_offset = best[3]
    best = search(
        max(offset_min, coarse_offset - 2.0),
        min(offset_max, coarse_offset + 2.0),
        0.1,
        current=best,
    )
    assert best is not None
    tenth_offset = best[3]
    refined_best = search(
        max(offset_min, tenth_offset - 0.2),
        min(offset_max, tenth_offset + 0.2),
        0.01,
        current=best,
    )
    assert refined_best is not None

    median_heading, median_position, mean_heading, offset_s, count = refined_best
    return offset_s, {
        "initial_timestamp_offset_s": initial_offset_s,
        "feasible_offset_min_s": offset_min,
        "feasible_offset_max_s": offset_max,
        "coarse_offset_s": coarse_offset,
        "tenth_second_offset_s": tenth_offset,
        "refined_offset_s": offset_s,
        "source_comparisons": float(count),
        "median_srt_vs_airdata_heading_error_deg": median_heading,
        "mean_srt_vs_airdata_heading_error_deg": mean_heading,
        "median_srt_vs_airdata_position_error_m": median_position,
        "difference_from_timestamp_anchor_s": offset_s - initial_offset_s,
    }



@pytest.mark.integration
def test_whaledrone_airdata_end_to_end(
    tmp_path: Path,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not request.config.getoption("--whaledrone-integration"):
        pytest.skip("Explicit --whaledrone-integration opt-in required")
    root = get_whaledrone_root()
    if root is None:
        pytest.skip("REEFVISION_WHALEDRONE_ROOT is unset or unavailable")

    airdata_path = root / "telemetry" / AIRDATA_NAME
    annotation_path = root / "annotations" / ANNOTATION_NAME
    calibration_path = root / "camera_calibration_DJIM3T_RGBwide.json"
    required = [airdata_path, annotation_path, calibration_path]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        pytest.skip("Missing WhaleDrone resources: " + ", ".join(missing))

    calibration = load_camera_calibration(calibration_path)
    settings = Settings(
        env="test",
        data_dir=tmp_path / "reefvision-whaledrone-e2e",
        database_url=f"sqlite:///{(tmp_path / 'whaledrone-e2e.db').as_posix()}",
        background_worker_enabled=False,
    )
    settings.ensure_directories()
    engine = create_database_engine(settings)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)

    summaries: dict[str, object] = {}
    try:
        with session_factory() as session:
            project = ProjectService(session, settings).create_project(
                ProjectCreate(
                    name="WhaleDrone AirData E2E",
                    template="blank",
                    georeference_height_offset_m=5.0,
                )
            )
            project_id = project.id

        inspect_source_video = video_assets_module._inspect_video
        for clip_key, clip_config in CLIPS.items():
            video_name = str(clip_config["video"])
            dvm_video = str(clip_config["dvm_video"])
            srt_path = root / "telemetry" / video_name.replace(".MP4", ".SRT")
            if not srt_path.is_file():
                pytest.skip(f"Missing WhaleDrone SRT: {srt_path}")

            initial_offset_s, clock_diagnostics = _derive_airdata_offset(
                airdata_path, video_name
            )
            with (
                srt_path.open("rb") as stream,
                airdata_path.open("rb") as airdata_stream,
            ):
                _, srt_source = read_srt_stream(stream)
                _, airdata_source = read_airdata_stream(airdata_stream)
            offset_s, source_alignment = _refine_airdata_offset_from_source_telemetry(
                airdata=airdata_source,
                srt=srt_source,
                initial_offset_s=initial_offset_s,
            )
            evidence = (
                "WhaleDrone AirData/video offset established from source-only SRT versus "
                "AirData heading/GPS alignment across the feasible flight-time range; "
                "DVM annotations and geolocation residuals are excluded from alignment"
            )
            source_video = _find_video(root, video_name)
            video_metadata_source = "documented_fallback"
            metadata: dict[str, float | int] = {
                "width_px": calibration.width_px,
                "height_px": calibration.height_px,
                "frame_count": len(srt_source.samples),
                "fps": FPS_FALLBACK,
                "duration_seconds": len(srt_source.samples) / FPS_FALLBACK,
            }
            if source_video is not None:
                metadata = inspect_source_video(source_video)
                assert (int(metadata["width_px"]), int(metadata["height_px"])) == (
                    calibration.width_px,
                    calibration.height_px,
                )
                video_metadata_source = "source_mp4"
            fps = float(metadata["fps"])

            points, reference, excluded_frame_count = _load_points(
                annotation_path,
                dvm_video,
                srt_frame_count=len(srt_source.samples),
            )
            frozen_metadata = tuple(metadata.items())
            monkeypatch.setattr(
                video_assets_module,
                "_inspect_video",
                lambda _, current=frozen_metadata: dict(current),
            )
            with (
                session_factory() as session,
                srt_path.open("rb") as srt_stream,
                airdata_path.open("rb") as airdata_stream,
            ):
                imported = VideoAssetService(session, settings).import_video(
                    project_id,
                    filename=video_name,
                    stream=io.BytesIO(("WhaleDrone-E2E:" + video_name).encode()),
                    media_type="video/mp4",
                    telemetry_filename=srt_path.name,
                    telemetry_stream=srt_stream,
                    airdata_filename=airdata_path.name,
                    airdata_stream=airdata_stream,
                    airdata_time_offset_s=offset_s,
                    airdata_time_offset_evidence=evidence,
                )
            video_id = imported.id

            with session_factory() as session:
                service = VideoAssetService(session, settings)
                persisted = service.get(video_id)
                assert persisted.airdata_telemetry.available
                assert persisted.airdata_telemetry.sample_count > 0
                assert persisted.telemetry.available
                assert persisted.airdata_alignment.time_offset_s == pytest.approx(offset_s)
                assert persisted.airdata_alignment.evidence == evidence
                assert persisted.telemetry.source_path is not None
                assert persisted.airdata_telemetry.source_path is not None
                assert resolve_managed_project_path(
                    settings, persisted.telemetry.source_path
                ).is_file()
                assert resolve_managed_project_path(
                    settings, persisted.airdata_telemetry.source_path
                ).is_file()

                project = ProjectService(session, settings).get_project(project_id)
                assert project.georeference_height_offset_m == pytest.approx(5.0)
                source = service.telemetry_source(video_id)
                assert source is not None

                report = evaluate_georeferencing(
                    points=points,
                    telemetry_source=source,
                    calibration=calibration,
                    fps=fps,
                    surface=SurfaceReference(
                        takeoff_height_above_surface_m=project.georeference_height_offset_m,
                        evidence="WhaleDrone/DVM height = AirData takeoff height + 5.0 m",
                    ),
                    max_delta_s=0.100,
                )

            projected = [
                observation
                for observation in report.observations
                if observation.error is None and observation.result is not None
            ]
            assert projected
            assert report.failed_count == 0
            assert report.statistics is not None

            provenance: Counter[tuple[str | None, ...]] = Counter()
            yaw_errors: list[float] = []
            pitch_errors: list[float] = []
            height_errors: list[float] = []
            sync_errors: list[float] = []
            for observation in projected:
                prov = observation.telemetry_provenance
                assert prov is not None
                sources = (
                    prov.position_source,
                    prov.relative_altitude_source,
                    prov.gimbal_yaw_source,
                    prov.gimbal_pitch_source,
                    prov.gimbal_roll_source,
                )
                provenance[sources] += 1
                assert sources == ("airdata",) * 5
                assert observation.telemetry is not None
                assert observation.sync_error_s is not None
                sync_errors.append(observation.sync_error_s)

                expected = reference[observation.point.point_id]
                expected_yaw = expected["yaw_deg"]
                if expected_yaw is not None and observation.telemetry.gimbal_yaw_deg is not None:
                    yaw_errors.append(
                        _angle_error_deg(observation.telemetry.gimbal_yaw_deg, expected_yaw)
                    )
                expected_pitch = observation.point.reference_pitch_deg
                if (
                    expected_pitch is not None
                    and observation.telemetry.gimbal_pitch_deg is not None
                ):
                    pitch_errors.append(
                        abs(observation.telemetry.gimbal_pitch_deg - expected_pitch)
                    )
                expected_height = expected["height_m"]
                if expected_height is not None:
                    height_errors.append(
                        abs(observation.result.camera_height_m - expected_height)
                    )

            unique_frames = {observation.point.frame_index for observation in projected}
            diagnostics = {
                "clip": clip_key,
                "airdata_time_offset_s": offset_s,
                "source_telemetry_alignment": source_alignment,
                "unique_frames_projected": len(unique_frames),
                "mean_sync_error_ms": mean(sync_errors) * 1000.0,
                "max_sync_error_ms": max(sync_errors) * 1000.0,
                "mean_airdata_vs_dvm_yaw_error_deg": mean(yaw_errors),
                "max_airdata_vs_dvm_yaw_error_deg": max(yaw_errors),
                "mean_airdata_vs_dvm_pitch_error_deg": mean(pitch_errors),
                "max_airdata_vs_dvm_pitch_error_deg": max(pitch_errors),
                "mean_resolved_vs_dvm_height_error_m": mean(height_errors),
                "max_resolved_vs_dvm_height_error_m": max(height_errors),
                "geolocation": report.statistics.model_dump(mode="json"),
            }
            print(json.dumps(diagnostics, indent=2, sort_keys=True))

            # Operational contracts are hard gates. DVM coordinate agreement is a
            # measured scientific diagnostic because DVM uses its own projection
            # implementation; it is not an independently surveyed accuracy target.
            assert len(unique_frames) >= int(clip_config["expected_unique_frames"])
            assert max(sync_errors) <= 0.100 + 1e-12
            assert yaw_errors
            assert pitch_errors
            assert height_errors

            summaries[clip_key] = {
                "video": video_name,
                "dvm_video": dvm_video,
                "video_metadata_source": video_metadata_source,
                "fps": fps,
                "airdata_time_offset_s": offset_s,
                "airdata_clock_diagnostics": clock_diagnostics,
                "source_telemetry_alignment": source_alignment,
                "persisted_alignment_evidence": evidence,
                "srt_sample_count": len(srt_source.samples),
                "airdata_sample_count": persisted.airdata_telemetry.sample_count,
                "point_rows_projected": len(projected),
                "unique_frames_projected": len(unique_frames),
                "unique_frames_excluded_outside_srt": excluded_frame_count,
                "mean_sync_error_ms": mean(sync_errors) * 1000.0,
                "max_sync_error_ms": max(sync_errors) * 1000.0,
                "mean_airdata_vs_dvm_yaw_error_deg": mean(yaw_errors),
                "max_airdata_vs_dvm_yaw_error_deg": max(yaw_errors),
                "mean_airdata_vs_dvm_pitch_error_deg": mean(pitch_errors),
                "max_airdata_vs_dvm_pitch_error_deg": max(pitch_errors),
                "mean_resolved_vs_dvm_height_error_m": mean(height_errors),
                "max_resolved_vs_dvm_height_error_m": max(height_errors),
                "geolocation": report.statistics.model_dump(mode="json"),
                "reference_agreement_status": "MEASURED_NOT_ACCEPTANCE_GATED",
                "reference_kind": "DVM-derived coordinates, not independent surveyed ground truth",
                "critical_field_provenance": {
                    "|".join(str(item) for item in key): value
                    for key, value in provenance.items()
                },
            }

        destination = (
            Path(__file__).resolve().parents[4]
            / ".artifacts"
            / "whaledrone-airdata-e2e"
        )
        destination.mkdir(parents=True, exist_ok=True)
        output = destination / "summary.json"
        output.write_text(json.dumps(summaries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        assert json.loads(output.read_text(encoding="utf-8")) == summaries
        print(json.dumps(summaries, indent=2, sort_keys=True))
    finally:
        engine.dispose()
