"""Video behavior analytics, schooling summaries, heatmaps, and research exports."""

from __future__ import annotations

import csv
import io
import json
from collections import Counter, defaultdict
from itertools import pairwise
from math import hypot, sqrt

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import VideoAsset, VideoTrack
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.videos import (
    VideoAssetResponse,
    VideoBehaviorAnalyticsRequest,
    VideoBehaviorAnalyticsResponse,
    VideoBehaviorTrackAnalytics,
    VideoFrameSchoolAnalytics,
    VideoHeatmapCell,
    VideoTrackResponse,
)
from reefvision.services.video_tracks import VideoTrackService


class VideoBehaviorService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.track_service = VideoTrackService(session)

    def _video(self, video_id: str) -> VideoAsset:
        video = self.session.get(VideoAsset, video_id)
        if video is None:
            raise NotFoundError("Video not found")
        return video

    def _tracks(self, video_id: str) -> list[VideoTrack]:
        return list(
            self.session.scalars(
                select(VideoTrack)
                .where(VideoTrack.video_id == video_id, VideoTrack.deleted_at.is_(None))
                .order_by(VideoTrack.track_number, VideoTrack.created_at, VideoTrack.id)
            )
        )

    @staticmethod
    def _calibration(video: VideoAsset) -> tuple[float | None, str | None]:
        calibration = dict(video.metadata_json or {}).get("calibration")
        if not isinstance(calibration, dict):
            return None, None
        raw_distance = calibration.get("distance_per_pixel")
        if raw_distance is None:
            return None, None
        try:
            distance_per_pixel = float(raw_distance)
        except (TypeError, ValueError):
            return None, None
        if distance_per_pixel <= 0:
            return None, None
        raw_unit = calibration.get("unit")
        return distance_per_pixel, str(raw_unit) if raw_unit else None

    def analytics(
        self,
        video_id: str,
        payload: VideoBehaviorAnalyticsRequest,
    ) -> VideoBehaviorAnalyticsResponse:
        video = self._video(video_id)
        tracks = self._tracks(video_id)
        for zone in payload.zones:
            if zone.x_max > video.width_px or zone.y_max > video.height_px:
                raise ValidationError("Video zones cannot extend outside the source video bounds")

        distance_per_pixel, physical_unit = self._calibration(video)
        warnings: list[str] = []
        if distance_per_pixel is None:
            warnings.append(
                "Video calibration is not set; physical distance and speed are unavailable."
            )

        track_results: list[VideoBehaviorTrackAnalytics] = []
        centers_by_frame: dict[int, list[tuple[float, float]]] = defaultdict(list)
        heatmap_counts: Counter[tuple[int, int]] = Counter()

        for track in tracks:
            interpolation = self.track_service.interpolate(track.id)
            frames = interpolation.frames
            if not frames:
                continue

            for frame in frames:
                center = (frame.center_x, frame.center_y)
                centers_by_frame[frame.frame].append(center)
                column = min(
                    payload.heatmap_bins_x - 1,
                    max(0, int(frame.center_x / video.width_px * payload.heatmap_bins_x)),
                )
                row = min(
                    payload.heatmap_bins_y - 1,
                    max(0, int(frame.center_y / video.height_px * payload.heatmap_bins_y)),
                )
                heatmap_counts[(column, row)] += 1

            distances: list[float] = []
            speeds: list[float] = []
            intervals: list[float] = []
            for first, second in pairwise(frames):
                elapsed = (second.frame - first.frame) / video.fps
                if elapsed <= 0:
                    continue
                distance = hypot(
                    second.center_x - first.center_x,
                    second.center_y - first.center_y,
                )
                distances.append(distance)
                speeds.append(distance / elapsed)
                intervals.append(elapsed)

            duration = max(0.0, (frames[-1].frame - frames[0].frame) / video.fps)
            distance_pixels = sum(distances)
            mean_speed = distance_pixels / duration if duration > 0 else 0.0
            maximum_speed = max(speeds, default=0.0)
            active_time = sum(
                elapsed
                for elapsed, speed in zip(intervals, speeds, strict=True)
                if speed >= payload.activity_speed_threshold_pixels_per_second
            )
            inactive_time = max(0.0, duration - active_time)
            zone_counts: Counter[str] = Counter()
            for frame in frames:
                for zone in payload.zones:
                    if (
                        zone.x_min <= frame.center_x <= zone.x_max
                        and zone.y_min <= frame.center_y <= zone.y_max
                    ):
                        zone_counts[zone.name] += 1

            track_results.append(
                VideoBehaviorTrackAnalytics(
                    track_id=track.id,
                    track_number=track.track_number,
                    label_class_id=track.label_class_id,
                    first_frame=frames[0].frame,
                    last_frame=frames[-1].frame,
                    observed_frame_count=len(frames),
                    duration_seconds=duration,
                    distance_pixels=distance_pixels,
                    mean_speed_pixels_per_second=mean_speed,
                    maximum_speed_pixels_per_second=maximum_speed,
                    active_time_seconds=active_time,
                    inactive_time_seconds=inactive_time,
                    distance_physical=(
                        distance_pixels * distance_per_pixel
                        if distance_per_pixel is not None
                        else None
                    ),
                    mean_speed_physical_per_second=(
                        mean_speed * distance_per_pixel
                        if distance_per_pixel is not None
                        else None
                    ),
                    maximum_speed_physical_per_second=(
                        maximum_speed * distance_per_pixel
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
            if len(centers) >= 2:
                nearest = [
                    min(
                        hypot(center[0] - other[0], center[1] - other[1])
                        for other_index, other in enumerate(centers)
                        if other_index != index
                    )
                    for index, center in enumerate(centers)
                ]
                center_x = sum(point[0] for point in centers) / len(centers)
                center_y = sum(point[1] for point in centers) / len(centers)
                spread = sqrt(
                    sum(
                        (point[0] - center_x) ** 2 + (point[1] - center_y) ** 2
                        for point in centers
                    )
                    / len(centers)
                )
                mean_nearest = sum(nearest) / len(nearest)
            else:
                mean_nearest = None
                spread = None

            school_results.append(
                VideoFrameSchoolAnalytics(
                    frame=frame_index,
                    timestamp_seconds=frame_index / video.fps,
                    active_track_count=len(centers),
                    mean_nearest_neighbor_pixels=mean_nearest,
                    school_spread_pixels=spread,
                    mean_nearest_neighbor_physical=(
                        mean_nearest * distance_per_pixel
                        if mean_nearest is not None and distance_per_pixel is not None
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
        return VideoBehaviorAnalyticsResponse(
            video_id=video.id,
            fps=video.fps,
            distance_per_pixel=distance_per_pixel,
            physical_unit=physical_unit,
            tracks=track_results,
            school_by_frame=school_results,
            heatmap_bins_x=payload.heatmap_bins_x,
            heatmap_bins_y=payload.heatmap_bins_y,
            heatmap=heatmap,
            warnings=warnings,
        )

    def export_tracks(self, video_id: str, export_format: str) -> tuple[bytes, str, str]:
        video = self._video(video_id)
        tracks = self._tracks(video_id)
        normalized = export_format.strip().casefold()

        if normalized == "json":
            payload = {
                "format": "reefvision_video_tracks_v1",
                "video": VideoAssetResponse.model_validate(video).model_dump(mode="json"),
                "tracks": [
                    {
                        **VideoTrackResponse.model_validate(track).model_dump(mode="json"),
                        "interpolated_frames": [
                            frame.model_dump(mode="json")
                            for frame in self.track_service.interpolate(track.id).frames
                        ],
                    }
                    for track in tracks
                ],
            }
            return (
                json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8"),
                "application/json",
                f"reefvision-{video.id}-tracks.json",
            )

        output = io.StringIO(newline="")
        if normalized == "csv":
            writer = csv.writer(output)
            writer.writerow(
                [
                    "frame",
                    "time_seconds",
                    "track_number",
                    "label_class_id",
                    "center_x",
                    "center_y",
                    "x",
                    "y",
                    "width",
                    "height",
                    "confidence",
                ]
            )
            for track in tracks:
                for frame in self.track_service.interpolate(track.id).frames:
                    confidence = next(
                        (
                            item.get("confidence")
                            for item in track.keyframes_json
                            if int(item.get("frame", -1)) == frame.frame
                        ),
                        None,
                    )
                    writer.writerow(
                        [
                            frame.frame,
                            frame.timestamp_seconds,
                            track.track_number,
                            track.label_class_id,
                            frame.center_x,
                            frame.center_y,
                            *frame.bbox,
                            confidence if confidence is not None else "",
                        ]
                    )
            return (
                output.getvalue().encode("utf-8"),
                "text/csv; charset=utf-8",
                f"reefvision-{video.id}-tracks.csv",
            )

        if normalized == "mot":
            writer = csv.writer(output, lineterminator="\n")
            for track in tracks:
                for frame in self.track_service.interpolate(track.id).frames:
                    confidence = next(
                        (
                            item.get("confidence")
                            for item in track.keyframes_json
                            if int(item.get("frame", -1)) == frame.frame
                        ),
                        None,
                    )
                    x, y, width, height = frame.bbox
                    writer.writerow(
                        [
                            frame.frame + 1,
                            track.track_number,
                            x,
                            y,
                            width,
                            height,
                            confidence if confidence is not None else 1.0,
                            -1,
                            -1,
                            -1,
                        ]
                    )
            return (
                output.getvalue().encode("utf-8"),
                "text/plain; charset=utf-8",
                f"reefvision-{video.id}-mot.txt",
            )

        raise ValidationError("Supported tracking exports are csv, mot, and json")
