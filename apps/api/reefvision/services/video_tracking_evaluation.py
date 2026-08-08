"""Compare manual fish tracks with model-generated tracks using transparent MOT-style metrics."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import hypot

from sqlalchemy.orm import Session

from reefvision.db.models import VideoAsset, VideoTrack
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.videos import (
    VideoTrackingEvaluationRequest,
    VideoTrackingEvaluationResponse,
    VideoTrackingTrackEvaluation,
    VideoTrackKeyframe,
)
from reefvision.services.video_tracks import VideoTrackService


@dataclass(frozen=True)
class _Observation:
    track_id: str
    label_class_id: str
    frame: int
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class _Match:
    frame: int
    ground_truth_track_id: str
    prediction_track_id: str
    iou: float
    center_error_pixels: float


def _intersection_over_union(
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
    first_x = first[0] + first[2] / 2.0
    first_y = first[1] + first[3] / 2.0
    second_x = second[0] + second[2] / 2.0
    second_y = second[1] + second[3] / 2.0
    return hypot(second_x - first_x, second_y - first_y)


class VideoTrackingEvaluationService:
    """Evaluate selected prediction tracks against selected manual/reference tracks."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.track_service = VideoTrackService(session)

    def _video(self, video_id: str) -> VideoAsset:
        video = self.session.get(VideoAsset, video_id)
        if video is None:
            raise NotFoundError("Video not found")
        return video

    def _tracks(self, video_id: str, track_ids: list[str], label: str) -> list[VideoTrack]:
        unique_ids = list(dict.fromkeys(track_ids))
        tracks: list[VideoTrack] = []
        for track_id in unique_ids:
            track = self.session.get(VideoTrack, track_id)
            if track is None or track.deleted_at is not None or track.video_id != video_id:
                raise ValidationError(f"{label} track does not belong to the selected video: {track_id}")
            tracks.append(track)
        return tracks

    @staticmethod
    def _in_range(frame: int, start_frame: int, end_frame: int) -> bool:
        return start_frame <= frame <= end_frame

    def _ground_truth_observations(
        self,
        tracks: list[VideoTrack],
        start_frame: int,
        end_frame: int,
    ) -> list[_Observation]:
        observations: list[_Observation] = []
        for track in tracks:
            interpolation = self.track_service.interpolate(track.id)
            observations.extend(
                _Observation(
                    track_id=track.id,
                    label_class_id=track.label_class_id,
                    frame=item.frame,
                    bbox=item.bbox,
                )
                for item in interpolation.frames
                if self._in_range(item.frame, start_frame, end_frame)
            )
        return observations

    def _prediction_observations(
        self,
        tracks: list[VideoTrack],
        start_frame: int,
        end_frame: int,
    ) -> list[_Observation]:
        observations: list[_Observation] = []
        for track in tracks:
            try:
                keyframes = [VideoTrackKeyframe.model_validate(item) for item in track.keyframes_json]
            except ValueError as exc:
                raise ValidationError("Stored prediction track keyframes are invalid") from exc
            observations.extend(
                _Observation(
                    track_id=track.id,
                    label_class_id=track.label_class_id,
                    frame=item.frame,
                    bbox=item.bbox,
                )
                for item in keyframes
                if self._in_range(item.frame, start_frame, end_frame)
            )
        return observations

    @staticmethod
    def _matches_for_frame(
        ground_truth: list[_Observation],
        predictions: list[_Observation],
        *,
        iou_threshold: float,
        class_aware: bool,
    ) -> list[_Match]:
        candidates: list[tuple[float, str, str, _Observation, _Observation]] = []
        for truth in ground_truth:
            for prediction in predictions:
                if class_aware and truth.label_class_id != prediction.label_class_id:
                    continue
                iou = _intersection_over_union(truth.bbox, prediction.bbox)
                if iou >= iou_threshold:
                    candidates.append((-iou, truth.track_id, prediction.track_id, truth, prediction))
        candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        used_truth: set[str] = set()
        used_predictions: set[str] = set()
        matches: list[_Match] = []
        for negative_iou, _, _, truth, prediction in candidates:
            if truth.track_id in used_truth or prediction.track_id in used_predictions:
                continue
            used_truth.add(truth.track_id)
            used_predictions.add(prediction.track_id)
            matches.append(
                _Match(
                    frame=truth.frame,
                    ground_truth_track_id=truth.track_id,
                    prediction_track_id=prediction.track_id,
                    iou=-negative_iou,
                    center_error_pixels=_center_error(truth.bbox, prediction.bbox),
                )
            )
        return matches

    def evaluate(
        self,
        video_id: str,
        request: VideoTrackingEvaluationRequest,
    ) -> VideoTrackingEvaluationResponse:
        video = self._video(video_id)
        ground_truth_tracks = self._tracks(
            video_id, request.ground_truth_track_ids, "Ground-truth"
        )
        prediction_tracks = self._tracks(
            video_id, request.prediction_track_ids, "Prediction"
        )
        if set(request.ground_truth_track_ids) & set(request.prediction_track_ids):
            raise ValidationError("Ground-truth and prediction track sets must not overlap")

        start_frame = request.start_frame if request.start_frame is not None else 0
        end_frame = (
            request.end_frame if request.end_frame is not None else video.frame_count - 1
        )
        if start_frame >= video.frame_count or end_frame >= video.frame_count:
            raise ValidationError("Evaluation frame range exceeds the source video")

        ground_truth = self._ground_truth_observations(
            ground_truth_tracks, start_frame, end_frame
        )
        predictions = self._prediction_observations(
            prediction_tracks, start_frame, end_frame
        )
        if not ground_truth:
            raise ValidationError("No ground-truth observations exist in the evaluation range")

        truth_by_frame: dict[int, list[_Observation]] = defaultdict(list)
        predictions_by_frame: dict[int, list[_Observation]] = defaultdict(list)
        for item in ground_truth:
            truth_by_frame[item.frame].append(item)
        for item in predictions:
            predictions_by_frame[item.frame].append(item)

        matches: list[_Match] = []
        for frame in range(start_frame, end_frame + 1):
            matches.extend(
                self._matches_for_frame(
                    truth_by_frame.get(frame, []),
                    predictions_by_frame.get(frame, []),
                    iou_threshold=request.iou_threshold,
                    class_aware=request.class_aware,
                )
            )

        matched_truth_keys = {
            (item.frame, item.ground_truth_track_id) for item in matches
        }
        matched_prediction_keys = {
            (item.frame, item.prediction_track_id) for item in matches
        }
        missed_observations = sum(
            (item.frame, item.track_id) not in matched_truth_keys for item in ground_truth
        )
        false_positive_observations = sum(
            (item.frame, item.track_id) not in matched_prediction_keys for item in predictions
        )

        matches_by_truth: dict[str, list[_Match]] = defaultdict(list)
        truth_frames_by_track: dict[str, list[int]] = defaultdict(list)
        for item in matches:
            matches_by_truth[item.ground_truth_track_id].append(item)
        for item in ground_truth:
            truth_frames_by_track[item.track_id].append(item.frame)

        track_summaries: list[VideoTrackingTrackEvaluation] = []
        total_id_switches = 0
        total_fragmentations = 0
        matched_prediction_track_ids: set[str] = set()
        matched_ground_truth_track_ids: set[str] = set()
        for track in ground_truth_tracks:
            track_matches = sorted(
                matches_by_truth.get(track.id, []), key=lambda item: item.frame
            )
            matched_frames = {item.frame for item in track_matches}
            prediction_ids = [item.prediction_track_id for item in track_matches]
            unique_prediction_ids = list(dict.fromkeys(prediction_ids))
            matched_prediction_track_ids.update(unique_prediction_ids)
            if track_matches:
                matched_ground_truth_track_ids.add(track.id)

            id_switches = sum(
                current != previous
                for previous, current in zip(prediction_ids, prediction_ids[1:], strict=False)
            )
            ordered_truth_frames = sorted(truth_frames_by_track.get(track.id, []))
            matched_segments = 0
            previous_frame: int | None = None
            previous_was_matched = False
            for frame in ordered_truth_frames:
                is_matched = frame in matched_frames
                contiguous = previous_frame is not None and frame == previous_frame + 1
                if is_matched and (not previous_was_matched or not contiguous):
                    matched_segments += 1
                previous_frame = frame
                previous_was_matched = is_matched
            fragmentations = max(0, matched_segments - 1)
            total_id_switches += id_switches
            total_fragmentations += fragmentations
            total_observations = len(ordered_truth_frames)
            track_summaries.append(
                VideoTrackingTrackEvaluation(
                    ground_truth_track_id=track.id,
                    ground_truth_track_number=track.track_number,
                    total_observations=total_observations,
                    matched_observations=len(track_matches),
                    recall=(len(track_matches) / total_observations if total_observations else 0.0),
                    id_switches=id_switches,
                    fragmentations=fragmentations,
                    matched_prediction_track_ids=unique_prediction_ids,
                )
            )

        matched_count = len(matches)
        ground_truth_count = len(ground_truth)
        prediction_count = len(predictions)
        tracking_recall = matched_count / ground_truth_count
        tracking_precision = matched_count / prediction_count if prediction_count else 0.0
        mota = 1.0 - (
            missed_observations + false_positive_observations + total_id_switches
        ) / ground_truth_count

        return VideoTrackingEvaluationResponse(
            video_id=video_id,
            start_frame=start_frame,
            end_frame=end_frame,
            iou_threshold=request.iou_threshold,
            class_aware=request.class_aware,
            ground_truth_track_count=len(ground_truth_tracks),
            prediction_track_count=len(prediction_tracks),
            ground_truth_observations=ground_truth_count,
            prediction_observations=prediction_count,
            matched_observations=matched_count,
            missed_observations=missed_observations,
            false_positive_observations=false_positive_observations,
            missed_tracks=len(ground_truth_tracks) - len(matched_ground_truth_track_ids),
            false_positive_tracks=len(prediction_tracks) - len(matched_prediction_track_ids),
            tracking_recall=tracking_recall,
            tracking_precision=tracking_precision,
            id_switches=total_id_switches,
            fragmentations=total_fragmentations,
            mean_iou=(sum(item.iou for item in matches) / matched_count if matches else 0.0),
            mean_center_error_pixels=(
                sum(item.center_error_pixels for item in matches) / matched_count
                if matches
                else None
            ),
            mota=mota,
            per_ground_truth_track=track_summaries,
        )
