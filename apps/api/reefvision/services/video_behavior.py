"""Advanced trajectory and schooling metrics for tracked video animals."""

from __future__ import annotations

from collections import Counter, defaultdict
from math import atan2, degrees, hypot, sqrt
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import VideoAsset, VideoTrack
from reefvision.domain.errors import NotFoundError
from reefvision.schemas.videos import (
    VideoAnalyticsRequest,
    VideoAnalyticsResponse,
    VideoFrameSchoolAnalytics,
    VideoHeatmapCell,
    VideoTrackAnalytics,
)
from reefvision.services.videos import _center, interpolate_track


class VideoBehaviorAnalysisService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _video(self, video_id: str) -> VideoAsset:
        video = self.session.get(VideoAsset, video_id)
        if video is None:
            raise NotFoundError("Video not found")
        return video

    def analytics(
        self,
        video_id: str,
        request: VideoAnalyticsRequest,
    ) -> VideoAnalyticsResponse:
        video = self._video(video_id)
        tracks = list(
            self.session.scalars(
                select(VideoTrack)
                .where(VideoTrack.video_id == video.id)
                .order_by(VideoTrack.track_number)
            )
        )
        calibration = dict(video.metadata_json).get("calibration", {})
        distance_per_pixel = (
            float(calibration["distance_per_pixel"])
            if isinstance(calibration, dict) and calibration.get("distance_per_pixel")
            else None
        )
        physical_unit = (
            str(calibration.get("unit"))
            if isinstance(calibration, dict) and calibration.get("unit")
            else None
        )
        warnings: list[str] = []
        if distance_per_pixel is None:
            warnings.append(
                "Video calibration is not set; physical distance, speed, acceleration, "
                "and wall-distance metrics are unavailable."
            )

        track_results: list[VideoTrackAnalytics] = []
        centers_by_frame: dict[int, list[tuple[float, float]]] = defaultdict(list)
        directions_by_frame: dict[int, list[tuple[float, float]]] = defaultdict(list)
        heatmap_counts: Counter[tuple[int, int]] = Counter()

        for track in tracks:
            points = interpolate_track(track)
            if not points:
                continue
            centers = [_center(item) for item in points]
            frame_distances: list[float] = []
            frame_speeds: list[float] = []
            interval_seconds: list[float] = []
            movement_vectors: list[tuple[float, float]] = []
            zone_counts: Counter[str] = Counter()
            wall_distances: list[float] = []

            for index, (point, center) in enumerate(zip(points, centers, strict=True)):
                centers_by_frame[point.frame_index].append(center)
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
                for zone in request.zones:
                    if (
                        zone.x_min <= center[0] <= zone.x_max
                        and zone.y_min <= center[1] <= zone.y_max
                    ):
                        zone_counts[zone.name] += 1
                if index == 0:
                    continue
                previous = points[index - 1]
                frame_delta = point.frame_index - previous.frame_index
                if frame_delta <= 0:
                    continue
                elapsed = frame_delta / video.fps
                dx = center[0] - centers[index - 1][0]
                dy = center[1] - centers[index - 1][1]
                distance = hypot(dx, dy)
                speed = distance / elapsed
                movement_vectors.append((dx, dy))
                frame_distances.append(distance)
                frame_speeds.append(speed)
                interval_seconds.append(elapsed)
                if distance > 0:
                    directions_by_frame[point.frame_index].append((dx / distance, dy / distance))

            duration = (points[-1].frame_index - points[0].frame_index) / video.fps
            distance_pixels = sum(frame_distances)
            net_displacement = hypot(
                centers[-1][0] - centers[0][0],
                centers[-1][1] - centers[0][1],
            )
            path_tortuosity = distance_pixels / net_displacement if net_displacement > 0 else None
            mean_speed = distance_pixels / duration if duration > 0 else 0.0
            maximum_speed = max(frame_speeds, default=0.0)
            accelerations = [
                abs(frame_speeds[index] - frame_speeds[index - 1]) / interval_seconds[index]
                for index in range(1, len(frame_speeds))
                if interval_seconds[index] > 0
            ]
            turning_angles: list[float] = []
            for index in range(1, len(movement_vectors)):
                previous_dx, previous_dy = movement_vectors[index - 1]
                current_dx, current_dy = movement_vectors[index]
                if hypot(previous_dx, previous_dy) == 0 or hypot(current_dx, current_dy) == 0:
                    continue
                dot = previous_dx * current_dx + previous_dy * current_dy
                cross = previous_dx * current_dy - previous_dy * current_dx
                turning_angles.append(degrees(atan2(abs(cross), dot)))
            active_time = sum(
                elapsed
                for elapsed, speed in zip(interval_seconds, frame_speeds, strict=True)
                if speed >= request.activity_speed_threshold_pixels_per_second
            )
            inactive_time = max(0.0, duration - active_time)
            mean_acceleration = mean(accelerations) if accelerations else 0.0
            maximum_acceleration = max(accelerations, default=0.0)
            mean_wall_distance = mean(wall_distances) if wall_distances else 0.0
            track_results.append(
                VideoTrackAnalytics(
                    track_id=track.id,
                    tracker_id=track.track_number,
                    label_class_id=track.label_class_id,
                    first_frame=points[0].frame_index,
                    last_frame=points[-1].frame_index,
                    observed_frame_count=len(points),
                    duration_seconds=duration,
                    distance_pixels=distance_pixels,
                    net_displacement_pixels=net_displacement,
                    path_tortuosity=path_tortuosity,
                    mean_speed_pixels_per_second=mean_speed,
                    maximum_speed_pixels_per_second=maximum_speed,
                    mean_acceleration_pixels_per_second_squared=mean_acceleration,
                    maximum_acceleration_pixels_per_second_squared=maximum_acceleration,
                    mean_turning_angle_degrees=(mean(turning_angles) if turning_angles else None),
                    cumulative_turning_angle_degrees=sum(turning_angles),
                    mean_distance_to_wall_pixels=mean_wall_distance,
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
                        maximum_speed * distance_per_pixel
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
                        mean_wall_distance * distance_per_pixel
                        if distance_per_pixel is not None
                        else None
                    ),
                    physical_unit=physical_unit,
                    zone_time_seconds={
                        name: count / video.fps for name, count in sorted(zone_counts.items())
                    },
                )
            )

        school_results: list[VideoFrameSchoolAnalytics] = []
        for frame_index, centers in sorted(centers_by_frame.items()):
            nearest: list[float] = []
            pairwise: list[float] = []
            if len(centers) >= 2:
                for first_index, first in enumerate(centers):
                    distances = [
                        hypot(first[0] - second[0], first[1] - second[1])
                        for second_index, second in enumerate(centers)
                        if second_index != first_index
                    ]
                    nearest.append(min(distances))
                    for second_index in range(first_index + 1, len(centers)):
                        second = centers[second_index]
                        pairwise.append(hypot(first[0] - second[0], first[1] - second[1]))
                center_x = mean(point[0] for point in centers)
                center_y = mean(point[1] for point in centers)
                spread = sqrt(
                    mean(
                        (point[0] - center_x) ** 2 + (point[1] - center_y) ** 2 for point in centers
                    )
                )
                mean_nearest = mean(nearest)
                mean_pairwise = mean(pairwise)
            else:
                spread = None
                mean_nearest = None
                mean_pairwise = None
            directions = directions_by_frame.get(frame_index, [])
            polarization = (
                hypot(
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
                    timestamp_seconds=frame_index / video.fps,
                    active_track_count=len(centers),
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
                )
            )

        heatmap = [
            VideoHeatmapCell(
                column=column,
                row=row,
                observation_count=count,
                occupancy_seconds=count / video.fps,
            )
            for (column, row), count in sorted(heatmap_counts.items())
        ]
        return VideoAnalyticsResponse(
            video_id=video.id,
            fps=video.fps,
            distance_per_pixel=distance_per_pixel,
            physical_unit=physical_unit,
            tracks=track_results,
            school_by_frame=school_results,
            heatmap_bins_x=request.heatmap_bins_x,
            heatmap_bins_y=request.heatmap_bins_y,
            heatmap=heatmap,
            warnings=warnings,
        )
