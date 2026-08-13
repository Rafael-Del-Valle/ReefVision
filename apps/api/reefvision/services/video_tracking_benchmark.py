"""Side-by-side scientific comparison of multiple video tracking runs."""

from __future__ import annotations

from sqlalchemy.orm import Session

from reefvision.schemas.videos import (
    VideoTrackingBenchmarkRequest,
    VideoTrackingBenchmarkResponse,
    VideoTrackingBenchmarkResult,
    VideoTrackingEvaluationRequest,
    VideoTrackingEvaluationResponse,
)
from reefvision.services.video_tracking_evaluation import VideoTrackingEvaluationService


class VideoTrackingBenchmarkService:
    def __init__(self, session: Session) -> None:
        self.evaluator = VideoTrackingEvaluationService(session)

    @staticmethod
    def _ranking_key(
        item: tuple[str, VideoTrackingEvaluationResponse],
    ) -> tuple[float, float, float, int, int, float, str]:
        name, evaluation = item
        center_error = evaluation.mean_center_error_pixels
        return (
            -evaluation.mota,
            -evaluation.recall,
            -evaluation.precision,
            evaluation.id_switches,
            evaluation.fragmentations,
            center_error if center_error is not None else float("inf"),
            name.casefold(),
        )

    def benchmark(
        self,
        video_id: str,
        payload: VideoTrackingBenchmarkRequest,
    ) -> VideoTrackingBenchmarkResponse:
        evaluations: list[tuple[str, VideoTrackingEvaluationResponse]] = []
        for candidate in payload.candidates:
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
            evaluations.append((candidate.name.strip(), evaluation))

        ranked = sorted(evaluations, key=self._ranking_key)
        results = [
            VideoTrackingBenchmarkResult(rank=index, name=name, evaluation=evaluation)
            for index, (name, evaluation) in enumerate(ranked, start=1)
        ]
        return VideoTrackingBenchmarkResponse(
            schema_version="video-tracking-benchmark-0001",
            video_id=video_id,
            winner=results[0].name,
            results=results,
        )
