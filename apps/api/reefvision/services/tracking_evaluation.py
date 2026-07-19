"""Compare tracker outputs against manual reference trajectories."""

from __future__ import annotations

from reefvision.ml.tracking_metrics import TrackBox, evaluate_tracking
from reefvision.schemas.tracking_evaluation import (
    TrackingEvaluationRequest,
    TrackingEvaluationResponse,
    TrackingFrameMatch,
    TrackingMetricSummary,
)


def _box(item: object) -> TrackBox:
    payload = item.model_dump(mode="python")  # type: ignore[attr-defined]
    return TrackBox(**payload)


class TrackingEvaluationService:
    def evaluate(self, request: TrackingEvaluationRequest) -> TrackingEvaluationResponse:
        references = [_box(item) for item in request.references]
        warnings: list[str] = []
        if not references:
            warnings.append(
                "No reference boxes were supplied; detection and identity scores cannot be interpreted."
            )
        summaries: list[TrackingMetricSummary] = []
        for candidate in request.candidates:
            metrics = evaluate_tracking(
                references,
                [_box(item) for item in candidate.boxes],
                minimum_iou=float(request.minimum_iou),
                maximum_depth_gap=(
                    float(request.maximum_depth_gap)
                    if request.maximum_depth_gap is not None
                    else None
                ),
                mostly_tracked_threshold=float(request.mostly_tracked_threshold),
                mostly_lost_threshold=float(request.mostly_lost_threshold),
            )
            summaries.append(
                TrackingMetricSummary(
                    candidate_name=candidate.name,
                    parameters=candidate.parameters,
                    reference_detection_count=metrics.reference_detection_count,
                    predicted_detection_count=metrics.predicted_detection_count,
                    matched_detection_count=metrics.matched_detection_count,
                    false_positive_count=metrics.false_positive_count,
                    false_negative_count=metrics.false_negative_count,
                    identity_switch_count=metrics.identity_switch_count,
                    fragmentation_count=metrics.fragmentation_count,
                    mostly_tracked_count=metrics.mostly_tracked_count,
                    mostly_lost_count=metrics.mostly_lost_count,
                    mota=metrics.mota,
                    motp=metrics.motp,
                    id_precision=metrics.id_precision,
                    id_recall=metrics.id_recall,
                    idf1=metrics.idf1,
                    detection_accuracy=metrics.detection_accuracy,
                    association_accuracy=metrics.association_accuracy,
                    hota=metrics.hota,
                    mean_center_error=metrics.mean_center_error,
                    mean_depth_error=metrics.mean_depth_error,
                    mean_track_lifespan_frames=metrics.mean_track_lifespan_frames,
                    mean_track_continuity=metrics.mean_track_continuity,
                    matches=[
                        TrackingFrameMatch(
                            frame_index=match.frame_index,
                            reference_track_id=match.reference_track_id,
                            predicted_track_id=match.predicted_track_id,
                            iou=match.iou,
                            center_error=match.center_error,
                            depth_error=match.depth_error,
                        )
                        for match in metrics.matches
                    ],
                )
            )
        ranked = sorted(
            summaries,
            key=lambda item: (
                -item.hota,
                -item.idf1,
                -item.mota,
                item.identity_switch_count,
                item.candidate_name.casefold(),
            ),
        )
        return TrackingEvaluationResponse(
            minimum_iou=float(request.minimum_iou),
            maximum_depth_gap=(
                float(request.maximum_depth_gap)
                if request.maximum_depth_gap is not None
                else None
            ),
            ranked_by_hota=ranked,
            best_candidate_name=ranked[0].candidate_name,
            warnings=warnings,
        )
