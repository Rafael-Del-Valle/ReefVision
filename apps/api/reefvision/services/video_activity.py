"""Calibrated fish movement-activity and bout analytics."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot

from sqlalchemy.orm import Session

from reefvision.db.models import VideoTrack
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.video_activity import (
    VideoActivityBout,
    VideoActivityInterval,
    VideoTrackActivityRequest,
    VideoTrackActivityResponse,
)
from reefvision.services.video_science import VideoScienceService
from reefvision.services.video_tracks import VideoTrackService


@dataclass(frozen=True)
class _Interval:
    start_frame: int
    end_frame: int
    start_time_seconds: float
    end_time_seconds: float
    duration_seconds: float
    distance_pixels: float
    distance: float
    speed_pixels_per_second: float
    speed_per_second: float
    active: bool


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


class VideoActivityService:
    """Measure calibrated activity from one persisted/interpolated fish trajectory."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.track_service = VideoTrackService(session)
        self.science_service = VideoScienceService(session)

    def analyze(
        self,
        track_id: str,
        payload: VideoTrackActivityRequest,
    ) -> VideoTrackActivityResponse:
        track = self.session.get(VideoTrack, track_id)
        if track is None or track.deleted_at is not None:
            raise NotFoundError("Video track not found")

        interpolation = self.track_service.interpolate(track_id)
        calibration = self.science_service.get_calibration(track.video_id)
        frames = interpolation.frames
        if len(frames) < 2:
            raise ValidationError("Activity analytics require at least two trajectory frames")

        first_available = frames[0].frame
        last_available = frames[-1].frame
        start_frame = (
            payload.start_frame if payload.start_frame is not None else first_available
        )
        end_frame = payload.end_frame if payload.end_frame is not None else last_available
        if start_frame < first_available or end_frame > last_available:
            raise ValidationError(
                "Activity frame range must stay within the selected track trajectory"
            )
        if end_frame <= start_frame:
            raise ValidationError("Activity analytics require at least two frames")

        selected = [item for item in frames if start_frame <= item.frame <= end_frame]
        if len(selected) < 2:
            raise ValidationError("Activity frame range contains fewer than two trajectory frames")

        pixels_per_unit = calibration.pixels_per_unit
        threshold_px_per_second = payload.speed_threshold_per_second * pixels_per_unit
        intervals: list[_Interval] = []
        for first, second in zip(selected, selected[1:], strict=False):
            duration = second.timestamp_seconds - first.timestamp_seconds
            if duration <= 0:
                raise ValidationError("Interpolated trajectory timestamps must increase")
            distance_px = hypot(
                second.center_x - first.center_x,
                second.center_y - first.center_y,
            )
            speed_px = distance_px / duration
            speed = speed_px / pixels_per_unit
            intervals.append(
                _Interval(
                    start_frame=first.frame,
                    end_frame=second.frame,
                    start_time_seconds=first.timestamp_seconds,
                    end_time_seconds=second.timestamp_seconds,
                    duration_seconds=duration,
                    distance_pixels=distance_px,
                    distance=distance_px / pixels_per_unit,
                    speed_pixels_per_second=speed_px,
                    speed_per_second=speed,
                    active=speed >= payload.speed_threshold_per_second,
                )
            )

        raw_bouts: list[tuple[bool, list[_Interval]]] = []
        for interval in intervals:
            if raw_bouts and raw_bouts[-1][0] == interval.active:
                raw_bouts[-1][1].append(interval)
            else:
                raw_bouts.append((interval.active, [interval]))

        if payload.minimum_active_bout_seconds > 0:
            retained_states: list[bool] = []
            for active, group in raw_bouts:
                duration = sum(item.duration_seconds for item in group)
                retained_states.extend(
                    [
                        active
                        and duration >= payload.minimum_active_bout_seconds
                    ]
                    * len(group)
                )
            intervals = [
                _Interval(
                    start_frame=item.start_frame,
                    end_frame=item.end_frame,
                    start_time_seconds=item.start_time_seconds,
                    end_time_seconds=item.end_time_seconds,
                    duration_seconds=item.duration_seconds,
                    distance_pixels=item.distance_pixels,
                    distance=item.distance,
                    speed_pixels_per_second=item.speed_pixels_per_second,
                    speed_per_second=item.speed_per_second,
                    active=retained_states[index],
                )
                for index, item in enumerate(intervals)
            ]

        bouts: list[VideoActivityBout] = []
        current: list[_Interval] = []
        current_state: bool | None = None
        for interval in intervals:
            if current_state is None or interval.active == current_state:
                current.append(interval)
                current_state = interval.active
                continue
            bouts.append(self._bout(current_state, current))
            current = [interval]
            current_state = interval.active
        if current and current_state is not None:
            bouts.append(self._bout(current_state, current))

        evaluated_seconds = sum(item.duration_seconds for item in intervals)
        active_seconds = sum(
            item.duration_seconds for item in intervals if item.active
        )
        rest_seconds = evaluated_seconds - active_seconds
        active_bouts = [item for item in bouts if item.state == "active"]
        rest_bouts = [item for item in bouts if item.state == "rest"]
        active_speeds = [item.speed_per_second for item in intervals if item.active]
        all_speeds = [item.speed_per_second for item in intervals]

        return VideoTrackActivityResponse(
            schema_version="video-track-activity-0001",
            track_id=track.id,
            video_id=track.video_id,
            track_number=track.track_number,
            label_class_id=track.label_class_id,
            trajectory_policy="configured_track_interpolation",
            start_frame=start_frame,
            end_frame=end_frame,
            distance_unit=calibration.unit,
            speed_threshold_per_second=payload.speed_threshold_per_second,
            speed_threshold_pixels_per_second=threshold_px_per_second,
            minimum_active_bout_seconds=payload.minimum_active_bout_seconds,
            evaluated_seconds=evaluated_seconds,
            active_seconds=active_seconds,
            rest_seconds=rest_seconds,
            active_fraction=(active_seconds / evaluated_seconds),
            active_bout_count=len(active_bouts),
            rest_bout_count=len(rest_bouts),
            mean_active_bout_seconds=_mean(
                [item.duration_seconds for item in active_bouts]
            ),
            maximum_active_bout_seconds=(
                max(item.duration_seconds for item in active_bouts)
                if active_bouts
                else None
            ),
            mean_rest_bout_seconds=_mean(
                [item.duration_seconds for item in rest_bouts]
            ),
            mean_active_speed_per_second=_mean(active_speeds),
            maximum_speed_per_second=max(all_speeds) if all_speeds else None,
            calibration=calibration,
            intervals=[
                VideoActivityInterval(
                    start_frame=item.start_frame,
                    end_frame=item.end_frame,
                    start_time_seconds=item.start_time_seconds,
                    end_time_seconds=item.end_time_seconds,
                    duration_seconds=item.duration_seconds,
                    distance_pixels=item.distance_pixels,
                    distance=item.distance,
                    speed_pixels_per_second=item.speed_pixels_per_second,
                    speed_per_second=item.speed_per_second,
                    active=item.active,
                )
                for item in intervals
            ],
            bouts=bouts,
        )

    @staticmethod
    def _bout(active: bool, intervals: list[_Interval]) -> VideoActivityBout:
        first = intervals[0]
        last = intervals[-1]
        return VideoActivityBout(
            state="active" if active else "rest",
            start_frame=first.start_frame,
            end_frame=last.end_frame,
            start_time_seconds=first.start_time_seconds,
            end_time_seconds=last.end_time_seconds,
            duration_seconds=sum(item.duration_seconds for item in intervals),
            interval_count=len(intervals),
        )
