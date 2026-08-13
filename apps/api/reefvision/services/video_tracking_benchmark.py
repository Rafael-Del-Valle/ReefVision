"""Side-by-side scientific comparison of multiple video tracking runs."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import VideoTrack
from reefvision.domain.errors import ValidationError
from reefvision.schemas.videos import (
    VideoTrackingBenchmarkCandidate,
    VideoTrackingBenchmarkRequest,
    VideoTrackingBenchmarkResponse,
    VideoTrackingBenchmarkResult,
    VideoTrackingEvaluationRequest,
    VideoTrackingEvaluationResponse,
)
from reefvision.services.video_tracking_evaluation import VideoTrackingEvaluationService


@dataclass(frozen=True)
class _CandidateEvaluation:
    name: str
    source_job_id: str | None
    prediction_track_ids: list[str]
    evaluation: VideoTrackingEvaluationResponse


class VideoTrackingBenchmarkService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.evaluator = VideoTrackingEvaluationService(session)

    def _prediction_track_ids(
        self,
        video_id: str,
        candidate: VideoTrackingBenchmarkCandidate,
    ) -> list[str]:
        if candidate.source_job_id is None:
            return candidate.prediction_track_ids
        track_ids = list(
            self.session.scalars(
                select(VideoTrack.id)
                .where(
                    VideoTrack.video_id == video_id,
                    VideoTrack.source_job_id == candidate.source_job_id,
                    VideoTrack.deleted_at.is_(None),
                )
                .order_by(VideoTrack.track_number, VideoTrack.id)
            )
        )
        if not track_ids:
            raise ValidationError(
                f"Tracking job {candidate.source_job_id} has no active tracks for this video"
            )
        return track_ids

    @staticmethod
    def _ranking_key(
        item: _CandidateEvaluation,
    ) -> tuple[float, float, float, int, int, float, str]:
        evaluation = item.evaluation
        center_error = evaluation.mean_center_error_pixels
        return (
            -evaluation.mota,
            -evaluation.recall,
            -evaluation.precision,
            evaluation.id_switches,
            evaluation.fragmentations,
            center_error if center_error is not None else float("inf"),
            item.name.casefold(),
        )

    def benchmark(
        self,
        video_id: str,
        payload: VideoTrackingBenchmarkRequest,
    ) -> VideoTrackingBenchmarkResponse:
        evaluations: list[_CandidateEvaluation] = []
        for candidate in payload.candidates:
            prediction_track_ids = self._prediction_track_ids(video_id, candidate)
            evaluation = self.evaluator.evaluate(
                video_id,
                VideoTrackingEvaluationRequest(
                    ground_truth_track_ids=payload.ground_truth_track_ids,
                    prediction_track_ids=prediction_track_ids,
                    iou_threshold=payload.iou_threshold,
                    class_aware=payload.class_aware,
                    start_frame=payload.start_frame,
                    end_frame=payload.end_frame,
                ),
            )
            evaluations.append(
                _CandidateEvaluation(
                    name=candidate.name.strip(),
                    source_job_id=candidate.source_job_id,
                    prediction_track_ids=prediction_track_ids,
                    evaluation=evaluation,
                )
            )

        ranked = sorted(evaluations, key=self._ranking_key)
        results = [
            VideoTrackingBenchmarkResult(
                rank=index,
                name=item.name,
                source_job_id=item.source_job_id,
                prediction_track_ids=item.prediction_track_ids,
                evaluation=item.evaluation,
            )
            for index, item in enumerate(ranked, start=1)
        ]
        return VideoTrackingBenchmarkResponse(
            schema_version="video-tracking-benchmark-0001",
            video_id=video_id,
            winner=results[0].name,
            results=results,
        )
