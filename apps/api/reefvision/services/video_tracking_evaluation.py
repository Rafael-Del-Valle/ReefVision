"""Scientific evaluation of persisted video tracks against manual ground truth."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import hypot

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import VideoAsset, VideoTrack
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.videos import (
    VideoTrackKeyframe,
    VideoTrackingEvaluationPerTrack,
    VideoTrackingEvaluationRequest,
    VideoTrackingEvaluationResponse,
)
from reefvision.services.video_tracks import VideoTrackService


@dataclass(frozen=True)
class _Observation:
    track_id: str
    track_number: int
    label_class_id: str
    frame: int
    bbox: tuple[float, float, float, float]


def _iou(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    if intersection <= 0:
        return 0.0
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0 else 0.0


def _center_error(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    return hypot((ax + aw / 2.0) - (bx + bw / 2.0), (ay + ah / 2.0) - (by + bh / 2.0))


class VideoTrackingEvaluationService:
    """Compare explicit prediction tracks with explicit human ground-truth tracks.

    Ground-truth tracks may be sparse manual annotations, so their configured
    interpolation is honored. Prediction tracks are evaluated only at persisted
    keyframes; interpolating model output would otherwise hide missed detections.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.track_service = VideoTrackService(session)

    def _video(self, video_id: str) -> VideoAsset:
        video = self.session.get(VideoAsset, video_id)
        if video is None:
            raise NotFoundError("Video not found")
        return video

    def _tracks(self, video_id: str, track_ids: list[str], role: str) -> list[VideoTrack]:
        unique_ids = list(dict.fromkeys(track_ids))
        rows = list(
            self.session.scalars(
                select(VideoTrack).where(
                    VideoTrack.id.in_(unique_ids),
                    VideoTrack.video_id == video_id,
                    VideoTrack.deleted_at.is_(None),
                )
            )
        )
        by_id = {track.id: track for track in rows}
        missing = [track_id for track_id in unique_ids if track_id not in by_id]
        if missing:
            raise ValidationError(
                f"{role} tracks must exist, be active, and belong to the selected video: "
                + ", ".join(missing)
            )
        return [by_id[track_id] for track_id in unique_ids]

    @staticmethod
    def _in_range(frame: int, start_frame: int, end_frame: int) -> bool:
        return start_frame <= frame <= end_frame

    def _ground_truth_observations(
        self,
        tracks: list[VideoTrack],
        start_frame: int,
        end_frame: int,
    ) -> dict[int, list[_Observation]]:
        by_frame: dict[int, list[_Observation]] = defaultdict(list)
        for track in tracks:
            interpolation = self.track_service.interpolate(track.id)
            for item in interpolation.frames:
                if not self._in_range(item.frame, start_frame, end_frame):
                    continue
                by_frame[item.frame].append(
                    _Observation(
                        track_id=track.id,
                        track_number=track.track_number,
                        label_class_id=track.label_class_id,
                        frame=item.frame,
                        bbox=item.bbox,
                    )
                )
        return by_frame

    def _prediction_observations(
        self,
        tracks: list[VideoTrack],
        start_frame: int,
        end_frame: int,
    ) -> dict[int, list[_Observation]]:
        by_frame: dict[int, list[_Observation]] = defaultdict(list)
        for track in tracks:
            try:
                keyframes = [
                    VideoTrackKeyframe.model_validate(item) for item in track.keyframes_json
                ]
            except ValueError as exc:
                raise ValidationError("Stored prediction track keyframes are invalid") from exc
            for item in keyframes:
                if not self._in_range(item.frame, start_frame, end_frame):
                    continue
                by_frame[item.frame].append(
                    _Observation(
                        track_id=track.id,
                        track_number=track.track_number,
                        label_class_id=track.label_class_id,
                        frame=item.frame,
                        bbox=item.bbox,
                    )
                )
        return by_frame

    @staticmethod
    def _compatible(
        truth: _Observation,
        prediction: _Observation,
        *,
        class_aware: bool,
    ) -> bool:
        return not class_aware or truth.label_class_id == prediction.label_class_id

    @classmethod
    def _match_frame(
        cls,
        ground_truth: list[_Observation],
        predictions: list[_Observation],
        *,
        iou_threshold: float,
        class_aware: bool,
        previous_assignments: dict[str, str],
    ) -> list[tuple[_Observation, _Observation, float, float]]:
        truth_by_id = {item.track_id: item for item in ground_truth}
        prediction_by_id = {item.track_id: item for item in predictions}
        used_truth: set[str] = set()
        used_predictions: set[str] = set()
        matches: list[tuple[_Observation, _Observation, float, float]] = []

        # CLEAR-MOT-style continuity preference: if yesterday's association still
        # passes the current frame gate, preserve it before solving new ambiguity.
        for truth_id, prediction_id in sorted(previous_assignments.items()):
            truth = truth_by_id.get(truth_id)
            prediction = prediction_by_id.get(prediction_id)
            if truth is None or prediction is None:
                continue
            if not cls._compatible(truth, prediction, class_aware=class_aware):
                continue
            overlap = _iou(truth.bbox, prediction.bbox)
            if overlap < iou_threshold:
                continue
            used_truth.add(truth.track_id)
            used_predictions.add(prediction.track_id)
            matches.append(
                (truth, prediction, overlap, _center_error(truth.bbox, prediction.bbox))
            )

        candidates: list[tuple[float, str, str, _Observation, _Observation]] = []
        for truth in ground_truth:
            if truth.track_id in used_truth:
                continue
            for prediction in predictions:
                if prediction.track_id in used_predictions:
                    continue
                if not cls._compatible(truth, prediction, class_aware=class_aware):
                    continue
                overlap = _iou(truth.bbox, prediction.bbox)
                if overlap < iou_threshold:
                    continue
                candidates.append((-overlap, truth.track_id, prediction.track_id, truth, prediction))
        candidates.sort(key=lambda item: (item[0], item[1], item[2]))

        for negative_iou, _truth_id, _prediction_id, truth, prediction in candidates:
            if truth.track_id in used_truth or prediction.track_id in used_predictions:
                continue
            used_truth.add(truth.track_id)
            used_predictions.add(prediction.track_id)
            matches.append(
                (truth, prediction, -negative_iou, _center_error(truth.bbox, prediction.bbox))
            )
        return matches

    def evaluate(
        self,
        video_id: str,
        payload: VideoTrackingEvaluationRequest,
    ) -> VideoTrackingEvaluationResponse:
        video = self._video(video_id)
        if set(payload.ground_truth_track_ids) & set(payload.prediction_track_ids):
            raise ValidationError("Ground-truth and prediction track sets must not overlap")

        start_frame = payload.start_frame if payload.start_frame is not None else 0
        end_frame = payload.end_frame if payload.end_frame is not None else video.frame_count - 1
        if start_frame >= video.frame_count or end_frame >= video.frame_count:
            raise ValidationError("Evaluation frame range cannot exceed the source video")
        if end_frame < start_frame:
            raise ValidationError("Evaluation end_frame must be greater than or equal to start_frame")

        truth_tracks = self._tracks(
            video_id, payload.ground_truth_track_ids, "Ground-truth"
        )
        prediction_tracks = self._tracks(
            video_id, payload.prediction_track_ids, "Prediction"
        )
        truth_by_frame = self._ground_truth_observations(truth_tracks, start_frame, end_frame)
        prediction_by_frame = self._prediction_observations(
            prediction_tracks, start_frame, end_frame
        )

        truth_count = sum(len(items) for items in truth_by_frame.values())
        prediction_count = sum(len(items) for items in prediction_by_frame.values())
        if truth_count == 0:
            raise ValidationError("Ground-truth tracks contain no observations in the frame range")

        match_by_truth_frame: dict[tuple[str, int], tuple[str, float, float]] = {}
        matched_prediction_observations: set[tuple[str, int]] = set()
        matched_prediction_tracks: set[str] = set()
        all_ious: list[float] = []
        all_center_errors: list[float] = []
        previous_assignments: dict[str, str] = {}

        for frame in range(start_frame, end_frame + 1):
            matches = self._match_frame(
                truth_by_frame.get(frame, []),
                prediction_by_frame.get(frame, []),
                iou_threshold=payload.iou_threshold,
                class_aware=payload.class_aware,
                previous_assignments=previous_assignments,
            )
            previous_assignments = {
                truth.track_id: prediction.track_id for truth, prediction, _iou_value, _error in matches
            }
            for truth, prediction, overlap, center_error in matches:
                match_by_truth_frame[(truth.track_id, frame)] = (
                    prediction.track_id,
                    overlap,
                    center_error,
                )
                matched_prediction_observations.add((prediction.track_id, frame))
                matched_prediction_tracks.add(prediction.track_id)
                all_ious.append(overlap)
                all_center_errors.append(center_error)

        per_track: list[VideoTrackingEvaluationPerTrack] = []
        id_switches_total = 0
        fragmentations_total = 0
        matched_truth_tracks = 0

        truth_observations_by_track: dict[str, list[_Observation]] = defaultdict(list)
        for frame_items in truth_by_frame.values():
            for observation in frame_items:
                truth_observations_by_track[observation.track_id].append(observation)

        for track in truth_tracks:
            observations = sorted(
                truth_observations_by_track.get(track.id, []), key=lambda item: item.frame
            )
            matched_rows: list[tuple[int, str, float, float]] = []
            matched_state: list[bool] = []
            for observation in observations:
                match = match_by_truth_frame.get((track.id, observation.frame))
                matched_state.append(match is not None)
                if match is not None:
                    prediction_id, overlap, center_error = match
                    matched_rows.append(
                        (observation.frame, prediction_id, overlap, center_error)
                    )

            switches = 0
            previous_prediction_id: str | None = None
            for _frame, prediction_id, _overlap, _center_error_px in matched_rows:
                if (
                    previous_prediction_id is not None
                    and prediction_id != previous_prediction_id
                ):
                    switches += 1
                previous_prediction_id = prediction_id

            matched_segments = 0
            previous_matched = False
            for is_matched in matched_state:
                if is_matched and not previous_matched:
                    matched_segments += 1
                previous_matched = is_matched
            fragmentations = max(0, matched_segments - 1)

            matched_count = len(matched_rows)
            if matched_count > 0:
                matched_truth_tracks += 1
            id_switches_total += switches
            fragmentations_total += fragmentations
            track_ious = [row[2] for row in matched_rows]
            track_errors = [row[3] for row in matched_rows]
            per_track.append(
                VideoTrackingEvaluationPerTrack(
                    ground_truth_track_id=track.id,
                    ground_truth_track_number=track.track_number,
                    label_class_id=track.label_class_id,
                    ground_truth_observations=len(observations),
                    matched_observations=matched_count,
                    missed_observations=len(observations) - matched_count,
                    recall=(matched_count / len(observations)) if observations else 0.0,
                    id_switches=switches,
                    fragmentations=fragmentations,
                    matched_prediction_track_ids=sorted(
                        {row[1] for row in matched_rows}
                    ),
                    mean_iou=(sum(track_ious) / len(track_ious)) if track_ious else None,
                    mean_center_error_pixels=(
                        sum(track_errors) / len(track_errors) if track_errors else None
                    ),
                )
            )

        matched_count = len(match_by_truth_frame)
        missed_observations = truth_count - matched_count
        false_positive_observations = prediction_count - len(matched_prediction_observations)
        missed_tracks = len(truth_tracks) - matched_truth_tracks
        false_positive_tracks = len(prediction_tracks) - len(matched_prediction_tracks)
        mota = 1.0 - (
            missed_observations + false_positive_observations + id_switches_total
        ) / truth_count

        return VideoTrackingEvaluationResponse(
            schema_version="video-tracking-evaluation-0001",
            video_id=video_id,
            start_frame=start_frame,
            end_frame=end_frame,
            iou_threshold=payload.iou_threshold,
            class_aware=payload.class_aware,
            ground_truth_track_count=len(truth_tracks),
            prediction_track_count=len(prediction_tracks),
            ground_truth_observations=truth_count,
            prediction_observations=prediction_count,
            matched_observations=matched_count,
            missed_observations=missed_observations,
            false_positive_observations=false_positive_observations,
            recall=matched_count / truth_count,
            precision=(matched_count / prediction_count) if prediction_count else 0.0,
            missed_tracks=missed_tracks,
            false_positive_tracks=false_positive_tracks,
            id_switches=id_switches_total,
            fragmentations=fragmentations_total,
            mean_iou=(sum(all_ious) / len(all_ious)) if all_ious else None,
            mean_center_error_pixels=(
                sum(all_center_errors) / len(all_center_errors)
                if all_center_errors
                else None
            ),
            mota=mota,
            per_track=per_track,
        )
