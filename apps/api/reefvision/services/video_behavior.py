"""Deterministic calibrated trajectory, zone, and schooling analysis."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from itertools import pairwise
from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    VideoAnalysisRun,
    VideoAsset,
    VideoTrack,
    VideoZoneRecord,
)
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.videos import (
    VideoAnalyticsRequest,
    VideoAnalyticsResponse,
    VideoFrameSchoolAnalytics,
    VideoHeatmapCell,
    VideoTrackAnalytics,
    VideoTrajectorySample,
    VideoZone,
    VideoZoneEvent,
)
from reefvision.services.video_tracks import (
    active_track_observations,
    interpolate_track,
    observation_center,
)
from reefvision.storage.datasets import canonical_json_sha256


def _point_time(frame_index: int, timestamp_seconds: float | None, fps: float) -> float:
    return float(timestamp_seconds) if timestamp_seconds is not None else frame_index / fps


def _inside_zone(center: tuple[float, float], zone: VideoZone) -> bool:
    return zone.x_min <= center[0] <= zone.x_max and zone.y_min <= center[1] <= zone.y_max


def _scaled(value: float | None, scale: float | None) -> float | None:
    return value * scale if value is not None and scale is not None else None


class VideoBehaviorAnalysisService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _video(self, video_id: str) -> VideoAsset:
        video = self.session.get(VideoAsset, video_id)
        if video is None:
            raise NotFoundError("Video not found")
        return video

    def _resolved_zones(
        self,
        video: VideoAsset,
        request: VideoAnalyticsRequest,
    ) -> list[VideoZone]:
        by_name: dict[str, VideoZone] = {}
        if request.include_saved_zones:
            saved = list(
                self.session.scalars(
                    select(VideoZoneRecord).where(
                        VideoZoneRecord.video_id == video.id,
                        VideoZoneRecord.deleted_at.is_(None),
                    )
                )
            )
            for saved_zone in saved:
                by_name[saved_zone.name.casefold()] = VideoZone(
                    name=saved_zone.name,
                    x_min=saved_zone.x_min,
                    y_min=saved_zone.y_min,
                    x_max=saved_zone.x_max,
                    y_max=saved_zone.y_max,
                )
        for requested_zone in request.zones:
            by_name[requested_zone.name.casefold()] = requested_zone
        zones = sorted(by_name.values(), key=lambda item: item.name.casefold())
        for resolved_zone in zones:
            if resolved_zone.x_max > video.width_px or resolved_zone.y_max > video.height_px:
                raise ValidationError("Analysis zones must remain inside source-frame bounds")
        return zones

    @staticmethod
    def _calibration(video: VideoAsset) -> tuple[float | None, str | None, int | None]:
        calibration = dict(video.metadata_json or {}).get("calibration", {})
        if not isinstance(calibration, dict):
            return None, None, None
        raw_scale = calibration.get("distance_per_pixel")
        try:
            scale = float(raw_scale) if raw_scale is not None else math.nan
        except (TypeError, ValueError):
            return None, None, None
        unit = str(calibration.get("unit") or "").strip()
        if not math.isfinite(scale) or scale <= 0 or not unit:
            return None, None, None
        revision = int(calibration.get("revision", 1))
        return scale, unit, revision

    def analytics(
        self,
        video_id: str,
        request: VideoAnalyticsRequest,
    ) -> VideoAnalyticsResponse:
        video = self._video(video_id)
        tracks = list(
            self.session.scalars(
                select(VideoTrack)
                .where(
                    VideoTrack.video_id == video.id,
                    VideoTrack.deleted_at.is_(None),
                )
                .order_by(VideoTrack.track_number, VideoTrack.id)
            )
        )
        zones = self._resolved_zones(video, request)
        distance_per_pixel, physical_unit, calibration_revision = self._calibration(video)
        warnings: list[str] = []
        warning_keys: set[str] = set()

        def warn(key: str, message: str) -> None:
            if key not in warning_keys:
                warning_keys.add(key)
                warnings.append(message)

        if distance_per_pixel is None:
            warn(
                "uncalibrated",
                "Video calibration is not set or invalid; results are explicitly pixel-based "
                "and physical distance, speed, acceleration, and wall-distance metrics are "
                "unavailable.",
            )
        if not tracks:
            warn("no_tracks", "No active tracks are available for behavior analysis.")

        track_results: list[VideoTrackAnalytics] = []
        centers_by_frame: dict[int, list[tuple[float, float]]] = defaultdict(list)
        timestamps_by_frame: dict[int, list[float]] = defaultdict(list)
        directions_by_frame: dict[int, list[tuple[float, float]]] = defaultdict(list)
        heatmap_counts: Counter[tuple[int, int]] = Counter()
        heatmap_seconds: defaultdict[tuple[int, int], float] = defaultdict(float)
        zone_events: list[VideoZoneEvent] = []
        source_revisions: list[dict[str, Any]] = []
        uses_observation_timestamps = False

        for track in tracks:
            persisted = active_track_observations(track, video)
            source_revisions.append(
                {
                    "track_id": track.id,
                    "revision": track.revision,
                    "observation_count": len(persisted),
                    "origin_job_id": track.origin_job_id,
                    "source_type": track.source_type,
                }
            )
            if not persisted:
                continue
            if any(right.frame_index - left.frame_index > 1 for left, right in pairwise(persisted)):
                warn(
                    "missing_frames",
                    "One or more tracks contain missing frames. Elapsed time uses actual frame "
                    "or observation timestamp intervals; gaps are not treated as zero-speed "
                    "samples.",
                )
            points = (
                interpolate_track(track, video) if request.sampling == "interpolated" else persisted
            )
            if not points:
                continue
            centers = [observation_center(item) for item in points]
            times = [
                _point_time(item.frame_index, item.timestamp_seconds, video.fps) for item in points
            ]
            if any(
                item.timestamp_seconds is not None
                and abs(float(item.timestamp_seconds) - item.frame_index / video.fps) > 1e-9
                for item in persisted
            ):
                uses_observation_timestamps = True

            distances: list[float | None] = [None] * len(points)
            speeds: list[float | None] = [None] * len(points)
            elapsed_intervals: list[float | None] = [None] * len(points)
            vectors: list[tuple[float, float] | None] = [None] * len(points)
            for index in range(1, len(points)):
                elapsed = times[index] - times[index - 1]
                if elapsed <= 0:
                    warn(
                        "nonpositive_time",
                        "Duplicate or non-increasing observation timestamps were skipped; they "
                        "do not create zero-speed measurements.",
                    )
                    continue
                dx = centers[index][0] - centers[index - 1][0]
                dy = centers[index][1] - centers[index - 1][1]
                distance = math.hypot(dx, dy)
                distances[index] = distance
                speeds[index] = distance / elapsed
                elapsed_intervals[index] = elapsed
                vectors[index] = (dx, dy)
                if distance > 0:
                    directions_by_frame[points[index].frame_index].append(
                        (dx / distance, dy / distance)
                    )

            accelerations: list[float | None] = [None] * len(points)
            turning_angles: list[float | None] = [None] * len(points)
            angular_velocities: list[float | None] = [None] * len(points)
            for index in range(2, len(points)):
                current_speed = speeds[index]
                previous_speed = speeds[index - 1]
                acceleration_elapsed = elapsed_intervals[index]
                if (
                    current_speed is not None
                    and previous_speed is not None
                    and acceleration_elapsed
                ):
                    accelerations[index] = (
                        abs(current_speed - previous_speed) / acceleration_elapsed
                    )
                previous_vector = vectors[index - 1]
                current_vector = vectors[index]
                if previous_vector is None or current_vector is None:
                    continue
                previous_length = math.hypot(*previous_vector)
                current_length = math.hypot(*current_vector)
                if previous_length == 0 or current_length == 0:
                    continue
                dot = (
                    previous_vector[0] * current_vector[0] + previous_vector[1] * current_vector[1]
                )
                cross = (
                    previous_vector[0] * current_vector[1] - previous_vector[1] * current_vector[0]
                )
                angle = math.degrees(math.atan2(abs(cross), dot))
                turning_angles[index] = angle
                if acceleration_elapsed:
                    angular_velocities[index] = angle / acceleration_elapsed

            zone_seconds = {zone.name: 0.0 for zone in zones}
            zone_states = {zone.name: False for zone in zones}
            wall_distances: list[float] = []
            for index, (point, center) in enumerate(zip(points, centers, strict=True)):
                centers_by_frame[point.frame_index].append(center)
                timestamps_by_frame[point.frame_index].append(times[index])
                wall_distances.append(
                    min(
                        center[0],
                        max(0.0, video.width_px - center[0]),
                        center[1],
                        max(0.0, video.height_px - center[1]),
                    )
                )
                column = min(
                    request.heatmap_bins_x - 1,
                    max(0, int(center[0] / video.width_px * request.heatmap_bins_x)),
                )
                row = min(
                    request.heatmap_bins_y - 1,
                    max(0, int(center[1] / video.height_px * request.heatmap_bins_y)),
                )
                heatmap_counts[(column, row)] += 1
                occupancy_elapsed = elapsed_intervals[index]
                if occupancy_elapsed is not None:
                    heatmap_seconds[(column, row)] += occupancy_elapsed
                for zone in zones:
                    inside = _inside_zone(center, zone)
                    was_inside = zone_states[zone.name]
                    if inside and (index == 0 or not was_inside):
                        zone_events.append(
                            VideoZoneEvent(
                                track_id=track.id,
                                zone_name=zone.name,
                                event_type="entry",
                                frame_index=point.frame_index,
                                timestamp_seconds=times[index],
                            )
                        )
                    elif was_inside and not inside:
                        zone_events.append(
                            VideoZoneEvent(
                                track_id=track.id,
                                zone_name=zone.name,
                                event_type="exit",
                                frame_index=point.frame_index,
                                timestamp_seconds=times[index],
                            )
                        )
                    if occupancy_elapsed is not None and was_inside:
                        zone_seconds[zone.name] += occupancy_elapsed
                    zone_states[zone.name] = inside

            valid_distances = [item for item in distances if item is not None]
            valid_speeds = [item for item in speeds if item is not None]
            valid_accelerations = [item for item in accelerations if item is not None]
            valid_turning = [item for item in turning_angles if item is not None]
            valid_angular = [item for item in angular_velocities if item is not None]
            valid_elapsed = [item for item in elapsed_intervals if item is not None]
            duration = max(0.0, times[-1] - times[0])
            distance_pixels = sum(valid_distances)
            net_displacement = math.hypot(
                centers[-1][0] - centers[0][0],
                centers[-1][1] - centers[0][1],
            )
            path_tortuosity = distance_pixels / net_displacement if net_displacement > 0 else None
            mean_speed = distance_pixels / sum(valid_elapsed) if sum(valid_elapsed) > 0 else 0.0
            active_time = sum(
                float(elapsed_intervals[index] or 0.0)
                for index, speed in enumerate(speeds)
                if speed is not None and speed >= request.activity_speed_threshold_pixels_per_second
            )
            measured_time = sum(valid_elapsed)
            inactive_time = max(0.0, measured_time - active_time)
            mean_acceleration = mean(valid_accelerations) if valid_accelerations else 0.0
            maximum_acceleration = max(valid_accelerations, default=0.0)
            trajectory = [
                VideoTrajectorySample(
                    observation_id=point.id,
                    frame_index=point.frame_index,
                    timestamp_seconds=times[index],
                    center_x_pixels=centers[index][0],
                    center_y_pixels=centers[index][1],
                    center_x_physical=(
                        centers[index][0] * distance_per_pixel
                        if distance_per_pixel is not None
                        else None
                    ),
                    center_y_physical=(
                        centers[index][1] * distance_per_pixel
                        if distance_per_pixel is not None
                        else None
                    ),
                    distance_from_previous_pixels=distances[index],
                    distance_from_previous_physical=_scaled(distances[index], distance_per_pixel),
                    speed_pixels_per_second=speeds[index],
                    speed_physical_per_second=_scaled(speeds[index], distance_per_pixel),
                    acceleration_pixels_per_second_squared=accelerations[index],
                    turning_angle_degrees=turning_angles[index],
                    angular_velocity_degrees_per_second=angular_velocities[index],
                    interpolated=point.source == "interpolated",
                    manual_edit=point.manual_edit,
                )
                for index, point in enumerate(points)
            ]
            track_results.append(
                VideoTrackAnalytics(
                    track_id=track.id,
                    tracker_id=track.track_number,
                    label_class_id=track.label_class_id,
                    first_frame=points[0].frame_index,
                    last_frame=points[-1].frame_index,
                    observed_frame_count=len(points),
                    persisted_observation_count=len(persisted),
                    duration_seconds=duration,
                    distance_pixels=distance_pixels,
                    total_path_length_pixels=distance_pixels,
                    net_displacement_pixels=net_displacement,
                    path_tortuosity=path_tortuosity,
                    mean_speed_pixels_per_second=mean_speed,
                    maximum_speed_pixels_per_second=max(valid_speeds, default=0.0),
                    mean_acceleration_pixels_per_second_squared=mean_acceleration,
                    maximum_acceleration_pixels_per_second_squared=maximum_acceleration,
                    mean_turning_angle_degrees=(mean(valid_turning) if valid_turning else None),
                    cumulative_turning_angle_degrees=sum(valid_turning),
                    mean_angular_velocity_degrees_per_second=(
                        mean(valid_angular) if valid_angular else None
                    ),
                    mean_distance_to_wall_pixels=mean(wall_distances),
                    active_time_seconds=active_time,
                    inactive_time_seconds=inactive_time,
                    distance_physical=(
                        distance_pixels * distance_per_pixel
                        if distance_per_pixel is not None
                        else None
                    ),
                    net_displacement_physical=(
                        net_displacement * distance_per_pixel
                        if distance_per_pixel is not None
                        else None
                    ),
                    mean_speed_physical_per_second=(
                        mean_speed * distance_per_pixel if distance_per_pixel is not None else None
                    ),
                    maximum_speed_physical_per_second=(
                        max(valid_speeds, default=0.0) * distance_per_pixel
                        if distance_per_pixel is not None
                        else None
                    ),
                    mean_acceleration_physical_per_second_squared=(
                        mean_acceleration * distance_per_pixel
                        if distance_per_pixel is not None
                        else None
                    ),
                    maximum_acceleration_physical_per_second_squared=(
                        maximum_acceleration * distance_per_pixel
                        if distance_per_pixel is not None
                        else None
                    ),
                    mean_distance_to_wall_physical=(
                        mean(wall_distances) * distance_per_pixel
                        if distance_per_pixel is not None
                        else None
                    ),
                    physical_unit=physical_unit,
                    zone_time_seconds=zone_seconds,
                    trajectory=trajectory,
                )
            )

        school_results: list[VideoFrameSchoolAnalytics] = []
        for frame_index, centers in sorted(centers_by_frame.items()):
            frame_timestamps = timestamps_by_frame[frame_index]
            if frame_timestamps and max(frame_timestamps) - min(frame_timestamps) > 1e-9:
                warn(
                    "inconsistent_frame_time",
                    "Observations on the same frame used different timestamps; school-level time "
                    "uses their deterministic mean.",
                )
            nearest: list[float] = []
            pairwise_distances: list[float] = []
            centroid_x = mean(point[0] for point in centers)
            centroid_y = mean(point[1] for point in centers)
            if len(centers) >= 2:
                for first_index, first in enumerate(centers):
                    distances_to_others = [
                        math.hypot(first[0] - second[0], first[1] - second[1])
                        for second_index, second in enumerate(centers)
                        if second_index != first_index
                    ]
                    nearest.append(min(distances_to_others))
                    for second in centers[first_index + 1 :]:
                        pairwise_distances.append(
                            math.hypot(first[0] - second[0], first[1] - second[1])
                        )
                spread = math.sqrt(
                    mean(
                        (point[0] - centroid_x) ** 2 + (point[1] - centroid_y) ** 2
                        for point in centers
                    )
                )
                mean_nearest = mean(nearest)
                mean_pairwise = mean(pairwise_distances)
            else:
                spread = None
                mean_nearest = None
                mean_pairwise = None
            directions = directions_by_frame.get(frame_index, [])
            polarization = (
                math.hypot(
                    sum(direction[0] for direction in directions),
                    sum(direction[1] for direction in directions),
                )
                / len(directions)
                if len(directions) >= 2
                else None
            )
            school_results.append(
                VideoFrameSchoolAnalytics(
                    frame_index=frame_index,
                    timestamp_seconds=(
                        mean(frame_timestamps) if frame_timestamps else frame_index / video.fps
                    ),
                    active_track_count=len(centers),
                    school_centroid_x_pixels=centroid_x,
                    school_centroid_y_pixels=centroid_y,
                    mean_nearest_neighbor_pixels=mean_nearest,
                    mean_pairwise_distance_pixels=mean_pairwise,
                    school_spread_pixels=spread,
                    polarization=polarization,
                    mean_nearest_neighbor_physical=(
                        mean_nearest * distance_per_pixel
                        if mean_nearest is not None and distance_per_pixel is not None
                        else None
                    ),
                    mean_pairwise_distance_physical=(
                        mean_pairwise * distance_per_pixel
                        if mean_pairwise is not None and distance_per_pixel is not None
                        else None
                    ),
                    school_spread_physical=(
                        spread * distance_per_pixel
                        if spread is not None and distance_per_pixel is not None
                        else None
                    ),
                    school_centroid_x_physical=_scaled(centroid_x, distance_per_pixel),
                    school_centroid_y_physical=_scaled(centroid_y, distance_per_pixel),
                )
            )

        heatmap = [
            VideoHeatmapCell(
                column=column,
                row=row,
                observation_count=count,
                occupancy_seconds=heatmap_seconds[(column, row)],
            )
            for (column, row), count in sorted(heatmap_counts.items())
        ]
        configuration = {
            **request.model_dump(mode="json", exclude={"persist_result"}),
            "resolved_zones": [zone.model_dump(mode="json") for zone in zones],
            "calibration_revision": calibration_revision,
        }
        response = VideoAnalyticsResponse(
            video_id=video.id,
            fps=video.fps,
            timing_source=(
                "observation_timestamps" if uses_observation_timestamps else "video_fps"
            ),
            distance_per_pixel=distance_per_pixel,
            physical_unit=physical_unit,
            tracks=track_results,
            school_by_frame=school_results,
            heatmap_bins_x=request.heatmap_bins_x,
            heatmap_bins_y=request.heatmap_bins_y,
            heatmap=heatmap,
            zone_events=sorted(
                zone_events,
                key=lambda item: (
                    item.timestamp_seconds,
                    item.track_id,
                    item.zone_name.casefold(),
                    item.event_type,
                ),
            ),
            configuration=configuration,
            source_track_revisions=source_revisions,
            warnings=warnings,
        )
        checksum_payload = response.model_dump(
            mode="json",
            exclude={"analysis_id", "analysis_sha256"},
        )
        result_sha256 = canonical_json_sha256(checksum_payload)
        response.analysis_sha256 = result_sha256
        if not request.persist_result:
            return response
        existing = self.session.scalar(
            select(VideoAnalysisRun).where(
                VideoAnalysisRun.video_id == video.id,
                VideoAnalysisRun.result_sha256 == result_sha256,
            )
        )
        if existing is not None:
            replay = VideoAnalyticsResponse.model_validate(existing.result_json)
            replay.analysis_id = existing.id
            replay.analysis_sha256 = existing.result_sha256
            return replay
        run = VideoAnalysisRun(
            video_id=video.id,
            configuration_json=configuration,
            source_revisions_json=source_revisions,
            result_json={},
            result_sha256=result_sha256,
        )
        self.session.add(run)
        self.session.flush()
        response.analysis_id = run.id
        run.result_json = response.model_dump(mode="json")
        self.session.commit()
        return response

    def get(self, analysis_id: str) -> VideoAnalyticsResponse:
        run = self.session.get(VideoAnalysisRun, analysis_id)
        if run is None:
            raise NotFoundError("Video analysis run not found")
        return VideoAnalyticsResponse.model_validate(run.result_json)

    def list(self, video_id: str, *, limit: int = 100) -> list[VideoAnalyticsResponse]:
        self._video(video_id)
        runs = list(
            self.session.scalars(
                select(VideoAnalysisRun)
                .where(VideoAnalysisRun.video_id == video_id)
                .order_by(VideoAnalysisRun.created_at.desc(), VideoAnalysisRun.id.desc())
                .limit(limit)
            )
        )
        return [VideoAnalyticsResponse.model_validate(item.result_json) for item in runs]
