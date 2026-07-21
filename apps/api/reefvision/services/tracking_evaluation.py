"""Raw and persisted tracker comparison against explicitly verified tracks."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import Job, VideoAsset, VideoTrack, VideoTrackingEvaluation
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.ml.tracking_metrics import TrackBox, TrackingMetrics, evaluate_tracking
from reefvision.schemas.tracking_evaluation import (
    TrackingBox,
    TrackingCandidate,
    TrackingEvaluationRequest,
    TrackingEvaluationResponse,
    TrackingFrameMatch,
    TrackingFrameSummary,
    TrackingMetricSummary,
    TrackingTrackSummary,
    VideoTrackingEvaluationCreateRequest,
    VideoTrackingEvaluationRunResponse,
)
from reefvision.services.video_tracks import active_track_observations
from reefvision.storage.datasets import canonical_json_sha256


def _box(item: object) -> TrackBox:
    payload = item.model_dump(mode="python")  # type: ignore[attr-defined]
    return TrackBox(**payload)


def _summary(
    *,
    candidate_name: str,
    parameters: dict[str, object],
    metrics: TrackingMetrics,
) -> TrackingMetricSummary:
    return TrackingMetricSummary(
        candidate_name=candidate_name,
        parameters=parameters,
        reference_detection_count=metrics.reference_detection_count,
        predicted_detection_count=metrics.predicted_detection_count,
        matched_detection_count=metrics.matched_detection_count,
        false_positive_count=metrics.false_positive_count,
        false_negative_count=metrics.false_negative_count,
        false_positive_track_count=metrics.false_positive_track_count,
        false_negative_track_count=metrics.false_negative_track_count,
        identity_switch_count=metrics.identity_switch_count,
        fragmentation_count=metrics.fragmentation_count,
        mostly_tracked_count=metrics.mostly_tracked_count,
        mostly_lost_count=metrics.mostly_lost_count,
        mota=metrics.mota,
        motp=metrics.motp,
        localization_iou=metrics.localization_iou,
        detection_precision=metrics.detection_precision,
        detection_recall=metrics.detection_recall,
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
        per_frame=[
            TrackingFrameSummary(
                frame_index=item.frame_index,
                reference_count=item.reference_count,
                predicted_count=item.predicted_count,
                matched_count=item.matched_count,
                false_positive_count=item.false_positive_count,
                false_negative_count=item.false_negative_count,
                identity_switch_count=item.identity_switch_count,
                mean_iou=item.mean_iou,
            )
            for item in metrics.per_frame
        ],
        per_track=[
            TrackingTrackSummary(
                reference_track_id=item.reference_track_id,
                reference_observation_count=item.reference_observation_count,
                matched_observation_count=item.matched_observation_count,
                coverage=item.coverage,
                fragmentation_count=item.fragmentation_count,
                identity_switch_count=item.identity_switch_count,
                matched_prediction_track_ids=list(item.matched_prediction_track_ids),
                mostly_tracked=item.mostly_tracked,
                mostly_lost=item.mostly_lost,
            )
            for item in metrics.per_track
        ],
    )


class TrackingEvaluationService:
    def evaluate(self, request: TrackingEvaluationRequest) -> TrackingEvaluationResponse:
        references = [_box(item) for item in request.references]
        warnings: list[str] = []
        if not references:
            warnings.append(
                "No verified reference boxes were supplied; detection and identity scores are "
                "software outputs without ground-truth interpretation."
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
                _summary(
                    candidate_name=candidate.name,
                    parameters=candidate.parameters,
                    metrics=metrics,
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
                float(request.maximum_depth_gap) if request.maximum_depth_gap is not None else None
            ),
            ranked_by_hota=ranked,
            best_candidate_name=ranked[0].candidate_name,
            warnings=warnings,
        )


class PersistedTrackingEvaluationService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _video(self, video_id: str) -> VideoAsset:
        video = self.session.get(VideoAsset, video_id)
        if video is None:
            raise NotFoundError("Video not found")
        return video

    @staticmethod
    def _tracking_boxes(
        tracks: list[VideoTrack],
        video: VideoAsset,
        *,
        confidence_threshold: float | None,
    ) -> list[TrackingBox]:
        boxes: list[TrackingBox] = []
        for track in tracks:
            for observation in active_track_observations(track, video):
                if (
                    confidence_threshold is not None
                    and float(observation.confidence or 0.0) < confidence_threshold
                ):
                    continue
                boxes.append(
                    TrackingBox(
                        frame_index=observation.frame_index,
                        track_id=track.id,
                        x=float(observation.x_min),
                        y=float(observation.y_min),
                        width=float(observation.x_max) - float(observation.x_min),
                        height=float(observation.y_max) - float(observation.y_min),
                        confidence=observation.confidence,
                    )
                )
        return boxes

    def evaluate(
        self,
        video_id: str,
        request: VideoTrackingEvaluationCreateRequest,
    ) -> VideoTrackingEvaluationRunResponse:
        video = self._video(video_id)
        references = list(
            self.session.scalars(
                select(VideoTrack).where(
                    VideoTrack.video_id == video.id,
                    VideoTrack.deleted_at.is_(None),
                    VideoTrack.is_ground_truth.is_(True),
                    VideoTrack.status == "verified",
                )
            )
        )
        candidate_query = select(VideoTrack).where(
            VideoTrack.video_id == video.id,
            VideoTrack.origin_job_id.is_not(None),
        )
        if not request.include_archived_candidates:
            candidate_query = candidate_query.where(VideoTrack.deleted_at.is_(None))
        if request.candidate_job_ids:
            candidate_query = candidate_query.where(
                VideoTrack.origin_job_id.in_(request.candidate_job_ids)
            )
        candidate_tracks = list(self.session.scalars(candidate_query))
        tracks_by_job: defaultdict[str, list[VideoTrack]] = defaultdict(list)
        for track in candidate_tracks:
            if track.origin_job_id:
                tracks_by_job[track.origin_job_id].append(track)
        if request.candidate_job_ids:
            missing = sorted(set(request.candidate_job_ids) - set(tracks_by_job))
            if missing:
                raise ValidationError(
                    "Candidate tracking jobs have no tracks for this video: " + ", ".join(missing)
                )
        jobs = {job_id: self.session.get(Job, job_id) for job_id in sorted(tracks_by_job)}
        reference_boxes = self._tracking_boxes(
            references,
            video,
            confidence_threshold=None,
        )
        thresholds: list[float | None]
        if request.confidence_thresholds:
            thresholds = []
            for item in sorted(request.confidence_thresholds):
                thresholds.append(float(item))
        else:
            thresholds = [None]
        candidates: list[TrackingCandidate] = []
        for job_id, tracks in sorted(tracks_by_job.items()):
            job = jobs[job_id]
            job_request = dict(job.request_json or {}) if job is not None else {}
            tracker = str(job_request.get("tracker", "tracker"))
            configured_threshold = job_request.get("confidence_threshold")
            for threshold in thresholds:
                resolved_threshold = (
                    threshold
                    if threshold is not None
                    else float(configured_threshold)
                    if configured_threshold is not None
                    else None
                )
                threshold_label = (
                    f"{resolved_threshold:.3f}" if resolved_threshold is not None else "stored"
                )
                candidates.append(
                    TrackingCandidate(
                        name=f"{tracker} | {job_id[:8]} | confidence {threshold_label}",
                        parameters={
                            "job_id": job_id,
                            "tracker": tracker,
                            "confidence_threshold": resolved_threshold,
                            "iou_threshold": job_request.get("iou_threshold"),
                            "tracker_options": job_request.get("tracker_options", {}),
                            "model_id": job_request.get("model_id"),
                        },
                        boxes=self._tracking_boxes(
                            tracks,
                            video,
                            confidence_threshold=resolved_threshold,
                        ),
                    )
                )
        warnings = [
            "Tracking metrics are engineering evaluation outputs. Synthetic fixtures validate "
            "software behavior only and do not establish biological or real-fish tracking validity."
        ]
        ranked: list[TrackingMetricSummary] = []
        best_name: str | None = None
        if not reference_boxes:
            warnings.append(
                "No explicitly verified ground-truth tracks exist for this video; localization, "
                "detection, fragmentation, and identity metrics were not computed."
            )
        elif not candidates:
            warnings.append("No completed tracker output is available for comparison.")
        else:
            raw = TrackingEvaluationService().evaluate(
                TrackingEvaluationRequest(
                    references=reference_boxes,
                    candidates=candidates,
                    minimum_iou=request.minimum_iou,
                    mostly_tracked_threshold=request.mostly_tracked_threshold,
                    mostly_lost_threshold=request.mostly_lost_threshold,
                )
            )
            ranked = raw.ranked_by_hota
            best_name = raw.best_candidate_name
            warnings.extend(raw.warnings)
        all_tracks = [*references, *candidate_tracks]
        source_revisions: list[dict[str, object]] = [
            {
                "track_id": track.id,
                "revision": track.revision,
                "origin_job_id": track.origin_job_id,
                "is_ground_truth": track.is_ground_truth,
                "deleted": track.deleted_at is not None,
            }
            for track in sorted(all_tracks, key=lambda item: item.id)
        ]
        configuration: dict[str, object] = request.model_dump(mode="json")
        core: dict[str, Any] = {
            "video_id": video.id,
            "ground_truth_available": bool(reference_boxes),
            "minimum_iou": float(request.minimum_iou),
            "ranked_by_hota": [item.model_dump(mode="json") for item in ranked],
            "best_candidate_name": best_name,
            "configuration": configuration,
            "source_track_revisions": source_revisions,
            "warnings": warnings,
        }
        result_sha256 = canonical_json_sha256(core)
        existing = self.session.scalar(
            select(VideoTrackingEvaluation).where(
                VideoTrackingEvaluation.video_id == video.id,
                VideoTrackingEvaluation.result_sha256 == result_sha256,
            )
        )
        if existing is not None:
            return VideoTrackingEvaluationRunResponse.model_validate(existing.result_json)
        record = VideoTrackingEvaluation(
            video_id=video.id,
            configuration_json=configuration,
            reference_track_ids_json=[track.id for track in references],
            candidate_job_ids_json=sorted(tracks_by_job),
            source_revisions_json=source_revisions,
            result_json={},
            result_sha256=result_sha256,
        )
        self.session.add(record)
        self.session.flush()
        response = VideoTrackingEvaluationRunResponse(
            evaluation_id=record.id,
            evaluation_sha256=result_sha256,
            **core,
        )
        record.result_json = response.model_dump(mode="json")
        self.session.commit()
        return response

    def get(self, evaluation_id: str) -> VideoTrackingEvaluationRunResponse:
        record = self.session.get(VideoTrackingEvaluation, evaluation_id)
        if record is None:
            raise NotFoundError("Video tracking evaluation not found")
        return VideoTrackingEvaluationRunResponse.model_validate(record.result_json)

    def list(
        self,
        video_id: str,
        *,
        limit: int = 100,
    ) -> list[VideoTrackingEvaluationRunResponse]:
        self._video(video_id)
        records = list(
            self.session.scalars(
                select(VideoTrackingEvaluation)
                .where(VideoTrackingEvaluation.video_id == video_id)
                .order_by(
                    VideoTrackingEvaluation.created_at.desc(),
                    VideoTrackingEvaluation.id.desc(),
                )
                .limit(limit)
            )
        )
        return [
            VideoTrackingEvaluationRunResponse.model_validate(item.result_json) for item in records
        ]
