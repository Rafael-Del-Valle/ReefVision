"""Configurable grid occupancy from persisted/interpolated fish trajectories."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import VideoAsset, VideoTrack
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.video_occupancy import (
    VideoOccupancyCell,
    VideoOccupancyRequest,
    VideoOccupancyResponse,
    VideoTrackOccupancySummary,
)
from reefvision.services.video_tracks import VideoTrackService


@dataclass(frozen=True)
class _Observation:
    track_id: str
    frame: int
    row: int
    column: int


class VideoOccupancyService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.track_service = VideoTrackService(session)

    def _video(self, video_id: str) -> VideoAsset:
        video = self.session.get(VideoAsset, video_id)
        if video is None:
            raise NotFoundError("Video not found")
        return video

    def _tracks(self, video_id: str, track_ids: list[str]) -> list[VideoTrack]:
        tracks = list(
            self.session.scalars(
                select(VideoTrack).where(
                    VideoTrack.id.in_(track_ids),
                    VideoTrack.video_id == video_id,
                    VideoTrack.deleted_at.is_(None),
                )
            )
        )
        by_id = {track.id: track for track in tracks}
        missing = [track_id for track_id in track_ids if track_id not in by_id]
        if missing:
            raise ValidationError(
                "Occupancy tracks must be active and belong to the selected video: "
                + ", ".join(missing)
            )
        return [by_id[track_id] for track_id in track_ids]

    @staticmethod
    def _cell_index(
        x: float,
        y: float,
        width: int,
        height: int,
        rows: int,
        columns: int,
    ) -> tuple[int, int]:
        column = min(columns - 1, max(0, int((x / width) * columns)))
        row = min(rows - 1, max(0, int((y / height) * rows)))
        return row, column

    def analyze(
        self,
        video_id: str,
        payload: VideoOccupancyRequest,
    ) -> VideoOccupancyResponse:
        video = self._video(video_id)
        tracks = self._tracks(video_id, payload.track_ids)
        start_frame = payload.start_frame if payload.start_frame is not None else 0
        end_frame = (
            payload.end_frame
            if payload.end_frame is not None
            else max(0, video.frame_count - 1)
        )
        if start_frame >= video.frame_count or end_frame >= video.frame_count:
            raise ValidationError("Occupancy frame range cannot exceed the source video")

        observations: list[_Observation] = []
        track_lookup = {track.id: track for track in tracks}
        for track in tracks:
            interpolation = self.track_service.interpolate(track.id)
            for item in interpolation.frames:
                if not start_frame <= item.frame <= end_frame:
                    continue
                row, column = self._cell_index(
                    item.center_x,
                    item.center_y,
                    video.width_px,
                    video.height_px,
                    payload.grid_rows,
                    payload.grid_columns,
                )
                observations.append(
                    _Observation(
                        track_id=track.id,
                        frame=item.frame,
                        row=row,
                        column=column,
                    )
                )

        if not observations:
            raise ValidationError("Selected trajectories have no observations in the frame range")

        frames_with_tracks = len({item.frame for item in observations})
        total_observations = len(observations)
        total_track_seconds = total_observations / video.fps
        by_cell: dict[tuple[int, int], list[_Observation]] = defaultdict(list)
        by_track: dict[str, list[_Observation]] = defaultdict(list)
        for observation in observations:
            by_cell[(observation.row, observation.column)].append(observation)
            by_track[observation.track_id].append(observation)

        cell_width = video.width_px / payload.grid_columns
        cell_height = video.height_px / payload.grid_rows
        cells: list[VideoOccupancyCell] = []
        for row in range(payload.grid_rows):
            for column in range(payload.grid_columns):
                cell_observations = by_cell.get((row, column), [])
                occupied_frames = {item.frame for item in cell_observations}
                unique_tracks = {item.track_id for item in cell_observations}
                count = len(cell_observations)
                cells.append(
                    VideoOccupancyCell(
                        row=row,
                        column=column,
                        x_min_pixels=column * cell_width,
                        y_min_pixels=row * cell_height,
                        x_max_pixels=(column + 1) * cell_width,
                        y_max_pixels=(row + 1) * cell_height,
                        observation_count=count,
                        observation_fraction=count / total_observations,
                        occupied_frame_count=len(occupied_frames),
                        occupied_frame_fraction=len(occupied_frames) / frames_with_tracks,
                        unique_track_count=len(unique_tracks),
                        dwell_seconds=count / video.fps,
                    )
                )

        per_track: list[VideoTrackOccupancySummary] = []
        for track_id in payload.track_ids:
            items = by_track.get(track_id, [])
            counts: dict[tuple[int, int], int] = defaultdict(int)
            for item in items:
                counts[(item.row, item.column)] += 1
            most_occupied = (
                min(
                    counts,
                    key=lambda key: (-counts[key], key[0], key[1]),
                )
                if counts
                else None
            )
            track = track_lookup[track_id]
            per_track.append(
                VideoTrackOccupancySummary(
                    track_id=track.id,
                    track_number=track.track_number,
                    label_class_id=track.label_class_id,
                    observation_count=len(items),
                    dwell_seconds=len(items) / video.fps,
                    occupied_cell_count=len(counts),
                    most_occupied_row=(most_occupied[0] if most_occupied else None),
                    most_occupied_column=(most_occupied[1] if most_occupied else None),
                    most_occupied_fraction=(
                        counts[most_occupied] / len(items)
                        if most_occupied is not None and items
                        else None
                    ),
                )
            )

        return VideoOccupancyResponse(
            schema_version="video-occupancy-0001",
            video_id=video_id,
            track_ids=payload.track_ids,
            start_frame=start_frame,
            end_frame=end_frame,
            grid_rows=payload.grid_rows,
            grid_columns=payload.grid_columns,
            video_width_pixels=video.width_px,
            video_height_pixels=video.height_px,
            trajectory_policy="configured_track_interpolation",
            frames_with_tracks=frames_with_tracks,
            track_frame_observations=total_observations,
            total_track_seconds=total_track_seconds,
            cells=cells,
            per_track=per_track,
        )
