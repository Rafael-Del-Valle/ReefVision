"""Side-by-side scientific comparison of multiple video tracking runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import Job, VideoTrack
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
class _ResolvedCandidate:
    name: str
    source_job_id: str | None
    prediction_track_ids: list[str]
    tracker: str | None
    model_id: str | None
    job_status: str | None
    tracking_settings: dict[str, Any]


@dataclass(frozen=True)
class _CandidateEvaluation:
    candidate: _ResolvedCandidate
    evaluation: VideoTrackingEvaluationResponse


class VideoTrackingBenchmarkService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.evaluator = VideoTrackingEvaluationService(session)

    @staticmethod
    def _tracking_settings(request: dict[str, Any]) -> dict[str, Any]:
        allowed = (
            "tracker",
            "model_id",
            "confidence",
            "iou",
            "device",
            "minimum_track_frames",
        )
        return {key: request[key] for key in allowed if key in request}

    def _resolve_candidate(
        self,
        video_id: str,
        candidate: VideoTrackingBenchmarkCandidate,
    ) -> _ResolvedCandidate:
        name = candidate.name.strip()
        if candidate.source_job_id is None:
            return _ResolvedCandidate(
                name=name,
                source_job_id=None,
                prediction_track_ids=candidate.prediction_track_ids,
                tracker=None,
                model_id=None,
                job_status=None,
                tracking_settings={},
            )

        job = self.session.get(Job, candidate.source_job_id)
        if job is None or job.job_type != "video_tracking":
            raise ValidationError(
                f"Tracking job {candidate.source_job_id} does not exist or is not a video-tracking job"
            )
        request = dict(job.request_json or {})
        if str(request.get("video_id", "")) != video_id:
            raise ValidationError(
                f"Tracking job {candidate.source_job_id} does not belong to the selected video"
            )
        if job.status != "succeeded":
            raise ValidationError(
                f"Tracking job {candidate.source_job_id} must succeed before benchmarking"
            )

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
        tracker = request.get("tracker")
        model_id = request.get("model_id")
        return _ResolvedCandidate(
            name=name,
            source_job_id=job.id,
            prediction_track_ids=track_ids,
            tracker=str(tracker) if tracker is not None else None,
            model_id=str(model_id) if model_id is not None else None,
            job_status=job.status,
            tracking_settings=self._tracking_settings(request),
        )

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
            item.candidate.name.casefold(),
        )

    def benchmark(
        self,
        video_id: str,
        payload: VideoTrackingBenchmarkRequest,
    ) -> VideoTrackingBenchmarkResponse:
        evaluations: list[_CandidateEvaluation] = []
        for requested_candidate in payload.candidates:
            candidate = self._resolve_candidate(video_id, requested_candidate)
            evaluation = self.evaluator.evaluate(
                video_id,
                VideoTrackingEvaluationRequest(
                    ground_truth_track_ids=payload.ground_truth_track_ids,
                    prediction_track_ids=candidate.prediction_track_ids,
                    iou_threshold=payload.iou_threshold,
                    class_aware=payload.class_aware,
                    start_frame=payload.start_frame,
                    end_frame=payload.end_frame,
                ),
            )
            evaluations.append(
                _CandidateEvaluation(
                    candidate=candidate,
                    evaluation=evaluation,
                )
            )

        ranked = sorted(evaluations, key=self._ranking_key)
        results = [
            VideoTrackingBenchmarkResult(
                rank=index,
                name=item.candidate.name,
                source_job_id=item.candidate.source_job_id,
                prediction_track_ids=item.candidate.prediction_track_ids,
                tracker=item.candidate.tracker,
                model_id=item.candidate.model_id,
                job_status=item.candidate.job_status,
                tracking_settings=item.candidate.tracking_settings,
                evaluation=item.evaluation,
            )
            for index, item in enumerate(ranked, start=1)
        ]
        first_evaluation = results[0].evaluation
        return VideoTrackingBenchmarkResponse(
            schema_version="video-tracking-benchmark-0001",
            video_id=video_id,
            winner=results[0].name,
            ground_truth_track_ids=first_evaluation.ground_truth_track_ids,
            start_frame=first_evaluation.start_frame,
            end_frame=first_evaluation.end_frame,
            iou_threshold=payload.iou_threshold,
            class_aware=payload.class_aware,
            results=results,
        )
