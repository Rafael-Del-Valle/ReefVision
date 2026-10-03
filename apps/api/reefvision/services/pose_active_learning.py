"""Explainable pose-specific active learning for scientist review."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    ModelRegistration,
    PoseActiveLearningCandidate,
    PoseActiveLearningRound,
    PoseLandmarkAssociationDecision,
    PoseLandmarkCorrection,
    PoseLandmarkIdentityBreak,
    PoseLandmarkObservation,
    VideoAsset,
    VideoTrack,
)
from reefvision.db.models.project import utc_now
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.pose_active_learning import (
    PoseActiveLearningCandidateResponse,
    PoseActiveLearningExportManifestResponse,
    PoseActiveLearningReviewRequest,
    PoseActiveLearningReviewTarget,
    PoseActiveLearningRoundCreateRequest,
    PoseActiveLearningRoundResponse,
)
from reefvision.storage.datasets import canonical_json_sha256

SELECTION_ALGORITHM = "reefvision-pose-active-learning"
SELECTION_ALGORITHM_VERSION = "0001"

_VISIBILITY_RISK = {
    "visible": 0.0,
    "uncertain": 1.0,
    "occluded": 0.75,
    "absent": 0.75,
    "out_of_frame": 0.50,
}


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


class PoseActiveLearningService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _round(self, round_id: str) -> PoseActiveLearningRound:
        record = self.session.get(PoseActiveLearningRound, round_id)
        if record is None:
            raise NotFoundError("Pose active-learning round not found")
        return record

    def _candidate(self, candidate_id: str) -> PoseActiveLearningCandidate:
        record = self.session.get(PoseActiveLearningCandidate, candidate_id)
        if record is None:
            raise NotFoundError("Pose active-learning candidate not found")
        return record

    def _video(self, project_id: str, video_id: str) -> VideoAsset:
        record = self.session.get(VideoAsset, video_id)
        if record is None or record.project_id != project_id:
            raise ValidationError("Video must belong to the selected project")
        return record

    def _tracks(
        self,
        video: VideoAsset,
        requested_ids: list[str],
    ) -> list[VideoTrack]:
        statement = select(VideoTrack).where(
            VideoTrack.video_id == video.id,
            VideoTrack.deleted_at.is_(None),
        )
        if requested_ids:
            unique_ids = list(dict.fromkeys(requested_ids))
            statement = statement.where(VideoTrack.id.in_(unique_ids))

        tracks = list(self.session.scalars(statement))
        if requested_ids and len(tracks) != len(set(requested_ids)):
            raise ValidationError(
                "Every requested pose Active Learning track must belong to the video"
            )
        if not tracks:
            raise ValidationError("No eligible video tracks were found")
        return sorted(tracks, key=lambda item: (item.track_number, item.id))

    def _models(
        self,
        project_id: str,
        requested_ids: list[str],
    ) -> list[str]:
        model_ids = list(dict.fromkeys(requested_ids))
        if not model_ids:
            return []

        models = list(
            self.session.scalars(
                select(ModelRegistration).where(ModelRegistration.id.in_(model_ids))
            )
        )
        if len(models) != len(model_ids):
            raise ValidationError("One or more acquisition models were not found")
        if any(model.project_id != project_id for model in models):
            raise ValidationError("All pose acquisition models must belong to the project")
        if any("pose" not in model.task.lower() for model in models):
            raise ValidationError("Pose Active Learning model filters must reference pose models")
        return model_ids

    def _latest_observations(
        self,
        track_id: str,
    ) -> list[PoseLandmarkObservation]:
        rows = list(
            self.session.scalars(
                select(PoseLandmarkObservation)
                .where(PoseLandmarkObservation.parent_video_track_id == track_id)
                .order_by(
                    PoseLandmarkObservation.observation_series_id,
                    PoseLandmarkObservation.revision,
                )
            )
        )
        latest: dict[str, PoseLandmarkObservation] = {}
        for row in rows:
            previous = latest.get(row.observation_series_id)
            if previous is None or row.revision > previous.revision:
                latest[row.observation_series_id] = row
        return sorted(
            latest.values(),
            key=lambda item: (
                item.frame_index,
                item.semantic_label,
                item.occurrence_index,
                item.id,
            ),
        )

    def _latest_decisions(
        self,
        observations: list[PoseLandmarkObservation],
    ) -> dict[str, PoseLandmarkAssociationDecision]:
        observation_ids = [item.id for item in observations]
        if not observation_ids:
            return {}

        rows = list(
            self.session.scalars(
                select(PoseLandmarkAssociationDecision)
                .where(PoseLandmarkAssociationDecision.observation_id.in_(observation_ids))
                .order_by(
                    PoseLandmarkAssociationDecision.observation_id,
                    PoseLandmarkAssociationDecision.decision_revision,
                )
            )
        )
        latest: dict[str, PoseLandmarkAssociationDecision] = {}
        for row in rows:
            previous = latest.get(row.observation_id)
            if previous is None or row.decision_revision > previous.decision_revision:
                latest[row.observation_id] = row
        return latest

    def _breaks(
        self,
        track_id: str,
    ) -> list[PoseLandmarkIdentityBreak]:
        return list(
            self.session.scalars(
                select(PoseLandmarkIdentityBreak)
                .where(PoseLandmarkIdentityBreak.parent_video_track_id == track_id)
                .order_by(
                    PoseLandmarkIdentityBreak.break_after_frame,
                    PoseLandmarkIdentityBreak.id,
                )
            )
        )

    def _score_frame(
        self,
        *,
        observations: list[PoseLandmarkObservation],
        decisions: dict[str, PoseLandmarkAssociationDecision],
        identity_breaks: list[PoseLandmarkIdentityBreak],
        frame_index: int,
        clip_radius_frames: int,
        weights: dict[str, float],
    ) -> tuple[float, dict[str, float], list[str]]:
        confidence_risk = [
            1.0 - item.landmark_confidence if item.landmark_confidence is not None else 1.0
            for item in observations
        ]
        low_landmark_confidence = _bounded(_mean(confidence_risk))

        visibility_uncertainty = _bounded(
            _mean([_VISIBILITY_RISK.get(item.visibility_state, 1.0) for item in observations])
        )

        association_risk: list[float] = []
        motion_risk: list[float] = []

        for observation in observations:
            decision = decisions.get(observation.id)
            if decision is None:
                association_risk.append(1.0)
                motion_risk.append(0.0)
                continue

            if (
                decision.association_state
                in {
                    "unresolved",
                    "identity_break",
                }
                or decision.association_confidence is None
            ):
                association_risk.append(1.0)
            else:
                association_risk.append(1.0 - decision.association_confidence)

            breakdown = decision.cost_breakdown_json or {}
            raw_motion = breakdown.get("motion_cost", 0.0)
            if isinstance(raw_motion, int | float):
                motion_risk.append(_bounded(float(raw_motion)))
            else:
                motion_risk.append(0.0)

        association_uncertainty = _bounded(_mean(association_risk))
        motion_anomaly = _bounded(max(motion_risk, default=0.0))

        label_counts = Counter(item.semantic_label for item in observations)
        repeated_observations = [
            item for item in observations if label_counts[item.semantic_label] > 1
        ]

        repeated_risk: list[float] = []
        for observation in repeated_observations:
            decision = decisions.get(observation.id)
            if decision is None:
                repeated_risk.append(1.0)
                continue
            if decision.association_state in {
                "unresolved",
                "identity_break",
            }:
                repeated_risk.append(1.0)
                continue
            if decision.candidate_margin is not None:
                repeated_risk.append(_bounded((0.10 - decision.candidate_margin) / 0.10))
                continue
            if decision.association_confidence is not None:
                repeated_risk.append(1.0 - decision.association_confidence)

        repeated_landmark_ambiguity = _bounded(_mean(repeated_risk))

        identity_break_signal = 0.0
        for item in identity_breaks:
            break_frames = [item.break_after_frame]
            if item.successor_start_frame is not None:
                break_frames.append(item.successor_start_frame)
            distance = min(abs(frame_index - candidate_frame) for candidate_frame in break_frames)
            if distance == 0:
                identity_break_signal = 1.0
                break
            if distance <= max(clip_radius_frames, 1):
                identity_break_signal = max(
                    identity_break_signal,
                    0.65,
                )

        components = {
            "low_landmark_confidence": low_landmark_confidence,
            "visibility_uncertainty": visibility_uncertainty,
            "association_uncertainty": association_uncertainty,
            "repeated_landmark_ambiguity": repeated_landmark_ambiguity,
            "identity_break_signal": identity_break_signal,
            "motion_anomaly": motion_anomaly,
        }

        total_weight = sum(weights.values())
        if total_weight <= 0:
            raise ValidationError(
                "Pose Active Learning requires at least one positive score weight"
            )

        score = _bounded(sum(components[key] * weights[key] for key in components) / total_weight)

        reasons: list[str] = []
        if low_landmark_confidence >= 0.35:
            reasons.append("low_landmark_confidence")
        if visibility_uncertainty >= 0.25:
            reasons.append("uncertain_or_missing_landmarks")
        if association_uncertainty >= 0.35:
            reasons.append("low_temporal_association_confidence")
        if repeated_landmark_ambiguity >= 0.25:
            reasons.append("repeated_landmark_ambiguity")
        if identity_break_signal > 0:
            reasons.append("identity_break_or_nearby_break")
        if motion_anomaly >= 0.25:
            reasons.append("temporal_motion_anomaly")
        if not reasons and score > 0:
            reasons.append("composite_pose_uncertainty")

        return score, components, reasons

    def create_round(
        self,
        project_id: str,
        request: PoseActiveLearningRoundCreateRequest,
    ) -> PoseActiveLearningRoundResponse:
        video = self._video(project_id, request.video_id)
        tracks = self._tracks(video, request.track_ids)
        model_ids = self._models(project_id, request.model_ids)

        weights = request.weights.model_dump(mode="json")
        raw_candidates: list[dict[str, Any]] = []

        for track in tracks:
            observations = self._latest_observations(track.id)
            if not observations:
                continue

            decisions = self._latest_decisions(observations)
            identity_breaks = self._breaks(track.id)

            grouped: dict[int, list[PoseLandmarkObservation]] = defaultdict(list)
            for observation in observations:
                if (
                    model_ids
                    and observation.source_model_id is not None
                    and observation.source_model_id not in model_ids
                ):
                    continue
                grouped[observation.frame_index].append(observation)

            for frame_index, frame_observations in grouped.items():
                schema_pairs = {
                    (
                        item.pose_schema_id,
                        item.pose_schema_revision,
                    )
                    for item in frame_observations
                }
                if len(schema_pairs) != 1:
                    raise ValidationError(
                        "A pose Active Learning frame cannot mix pose schema revisions"
                    )

                pose_schema_id, pose_schema_revision = next(iter(schema_pairs))

                score, components, reasons = self._score_frame(
                    observations=frame_observations,
                    decisions=decisions,
                    identity_breaks=identity_breaks,
                    frame_index=frame_index,
                    clip_radius_frames=request.clip_radius_frames,
                    weights=weights,
                )

                if request.selection_unit == "frame":
                    frame_start = frame_index
                    frame_end = frame_index
                else:
                    frame_start = max(
                        0,
                        frame_index - request.clip_radius_frames,
                    )
                    frame_end = min(
                        video.frame_count - 1,
                        frame_index + request.clip_radius_frames,
                    )

                source_model_ids = sorted(
                    {
                        item.source_model_id
                        for item in frame_observations
                        if item.source_model_id is not None
                    }
                )
                source_job_ids = sorted(
                    {
                        item.source_job_id
                        for item in frame_observations
                        if item.source_job_id is not None
                    }
                )

                relevant_break_ids = sorted(
                    {
                        item.id
                        for item in identity_breaks
                        if (frame_start <= item.break_after_frame <= frame_end)
                        or (
                            item.successor_start_frame is not None
                            and frame_start <= item.successor_start_frame <= frame_end
                        )
                    }
                )

                decision_ids = sorted(
                    {
                        decision.id
                        for observation in frame_observations
                        if (decision := decisions.get(observation.id)) is not None
                    }
                )

                provenance = {
                    "schema_version": "pose-active-learning-provenance-0001",
                    "selection_algorithm": SELECTION_ALGORITHM,
                    "selection_algorithm_version": (SELECTION_ALGORITHM_VERSION),
                    "project_id": project_id,
                    "video_id": video.id,
                    "video_sha256": video.sha256,
                    "video_track_id": track.id,
                    "source_track_revision": track.revision,
                    "focus_frame": frame_index,
                    "frame_start": frame_start,
                    "frame_end": frame_end,
                    "pose_schema_id": pose_schema_id,
                    "pose_schema_revision": pose_schema_revision,
                    "observation_ids": sorted(item.id for item in frame_observations),
                    "association_decision_ids": decision_ids,
                    "identity_break_ids": relevant_break_ids,
                    "source_model_ids": source_model_ids,
                    "source_job_ids": source_job_ids,
                    "score_components": components,
                    "weights": weights,
                    "reason_codes": reasons,
                }

                raw_candidates.append(
                    {
                        "video_track_id": track.id,
                        "focus_frame": frame_index,
                        "frame_start": frame_start,
                        "frame_end": frame_end,
                        "acquisition_score": score,
                        "score_components": components,
                        "reason_codes": reasons,
                        "pose_schema_id": pose_schema_id,
                        "pose_schema_revision": pose_schema_revision,
                        "source_track_revision": track.revision,
                        "source_model_ids": source_model_ids,
                        "source_job_ids": source_job_ids,
                        "provenance": provenance,
                        "provenance_sha256": canonical_json_sha256(provenance),
                    }
                )

        if not raw_candidates:
            raise ValidationError(
                "No canonical temporal pose observations were available. "
                "Build pose temporal associations before creating a pose "
                "Active Learning round."
            )

        raw_candidates.sort(
            key=lambda item: (
                -float(item["acquisition_score"]),
                str(item["video_track_id"]),
                int(item["focus_frame"]),
            )
        )

        selected: list[dict[str, Any]] = []
        for candidate in raw_candidates:
            same_track = [
                item for item in selected if item["video_track_id"] == candidate["video_track_id"]
            ]

            too_close = any(
                abs(int(candidate["focus_frame"]) - int(previous["focus_frame"]))
                < request.minimum_frame_spacing
                for previous in same_track
            )

            overlapping_clip = request.selection_unit == "clip" and any(
                int(candidate["frame_start"]) <= int(previous["frame_end"])
                and int(candidate["frame_end"]) >= int(previous["frame_start"])
                for previous in same_track
            )

            if too_close or overlapping_clip:
                continue

            selected.append(candidate)
            if len(selected) >= request.requested_size:
                break

        if not selected:
            raise ValidationError(
                "Pose Active Learning selection constraints removed every candidate"
            )

        identity_manifest = {
            "schema_version": "pose-active-learning-selection-identity-0001",
            "selection_algorithm": SELECTION_ALGORITHM,
            "selection_algorithm_version": SELECTION_ALGORITHM_VERSION,
            "project_id": project_id,
            "video_id": video.id,
            "video_sha256": video.sha256,
            "selection_unit": request.selection_unit,
            "requested_size": request.requested_size,
            "clip_radius_frames": request.clip_radius_frames,
            "minimum_frame_spacing": request.minimum_frame_spacing,
            "model_ids": model_ids,
            "weights": weights,
            "items": [
                {
                    "video_track_id": item["video_track_id"],
                    "focus_frame": item["focus_frame"],
                    "frame_start": item["frame_start"],
                    "frame_end": item["frame_end"],
                    "acquisition_score": item["acquisition_score"],
                    "score_components": item["score_components"],
                    "reason_codes": item["reason_codes"],
                    "pose_schema_id": item["pose_schema_id"],
                    "pose_schema_revision": item["pose_schema_revision"],
                    "source_track_revision": item["source_track_revision"],
                    "provenance_sha256": item["provenance_sha256"],
                }
                for item in selected
            ],
        }

        selection_sha256 = canonical_json_sha256(identity_manifest)

        existing = self.session.scalar(
            select(PoseActiveLearningRound).where(
                PoseActiveLearningRound.project_id == project_id,
                PoseActiveLearningRound.selection_sha256 == selection_sha256,
            )
        )
        if existing is not None:
            return PoseActiveLearningRoundResponse.model_validate(existing)

        manifest = {
            **identity_manifest,
            "schema_version": "pose-active-learning-selection-0001",
        }

        round_record = PoseActiveLearningRound(
            project_id=project_id,
            video_id=video.id,
            name=request.name.strip(),
            status="open",
            selection_unit=request.selection_unit,
            requested_size=request.requested_size,
            selected_count=len(selected),
            clip_radius_frames=request.clip_radius_frames,
            minimum_frame_spacing=request.minimum_frame_spacing,
            model_ids_json=model_ids,
            scoring_config_json={
                "algorithm": SELECTION_ALGORITHM,
                "algorithm_version": SELECTION_ALGORITHM_VERSION,
                "weights": weights,
            },
            selection_manifest_json=manifest,
            selection_sha256=selection_sha256,
            created_by=request.created_by or "local_user",
        )
        self.session.add(round_record)
        self.session.flush()

        for item in selected:
            self.session.add(
                PoseActiveLearningCandidate(
                    round_id=round_record.id,
                    video_track_id=item["video_track_id"],
                    focus_frame=item["focus_frame"],
                    frame_start=item["frame_start"],
                    frame_end=item["frame_end"],
                    acquisition_score=item["acquisition_score"],
                    score_components_json=item["score_components"],
                    reason_codes_json=item["reason_codes"],
                    pose_schema_id=item["pose_schema_id"],
                    pose_schema_revision=item["pose_schema_revision"],
                    source_track_revision=item["source_track_revision"],
                    source_model_ids_json=item["source_model_ids"],
                    source_job_ids_json=item["source_job_ids"],
                    provenance_json=item["provenance"],
                    provenance_sha256=item["provenance_sha256"],
                    review_status="pending",
                )
            )

        self.session.commit()
        self.session.refresh(round_record)
        return PoseActiveLearningRoundResponse.model_validate(round_record)

    def list_rounds(
        self,
        project_id: str,
        video_id: str | None = None,
    ) -> list[PoseActiveLearningRoundResponse]:
        statement = (
            select(PoseActiveLearningRound)
            .where(PoseActiveLearningRound.project_id == project_id)
            .order_by(
                PoseActiveLearningRound.created_at.desc(),
                PoseActiveLearningRound.id,
            )
        )
        if video_id is not None:
            statement = statement.where(PoseActiveLearningRound.video_id == video_id)
        return [
            PoseActiveLearningRoundResponse.model_validate(item)
            for item in self.session.scalars(statement)
        ]

    def _candidate_response(
        self,
        candidate: PoseActiveLearningCandidate,
    ) -> PoseActiveLearningCandidateResponse:
        round_record = self._round(candidate.round_id)
        return PoseActiveLearningCandidateResponse(
            id=candidate.id,
            round_id=candidate.round_id,
            video_track_id=candidate.video_track_id,
            focus_frame=candidate.focus_frame,
            frame_start=candidate.frame_start,
            frame_end=candidate.frame_end,
            acquisition_score=candidate.acquisition_score,
            score_components_json=dict(candidate.score_components_json),
            reason_codes_json=list(candidate.reason_codes_json),
            pose_schema_id=candidate.pose_schema_id,
            pose_schema_revision=candidate.pose_schema_revision,
            source_track_revision=candidate.source_track_revision,
            source_model_ids_json=list(candidate.source_model_ids_json),
            source_job_ids_json=list(candidate.source_job_ids_json),
            provenance_json=dict(candidate.provenance_json),
            provenance_sha256=candidate.provenance_sha256,
            review_status=candidate.review_status,
            review_started_track_revision=(candidate.review_started_track_revision),
            verified_track_revision=(candidate.verified_track_revision),
            verified_pose_sha256=(candidate.verified_pose_sha256),
            correction_id=candidate.correction_id,
            reviewed_by=candidate.reviewed_by,
            reviewed_at=candidate.reviewed_at,
            created_at=candidate.created_at,
            review_target=PoseActiveLearningReviewTarget(
                video_id=round_record.video_id,
                video_track_id=candidate.video_track_id,
                focus_frame=candidate.focus_frame,
                frame_start=candidate.frame_start,
                frame_end=candidate.frame_end,
                pose_schema_id=candidate.pose_schema_id,
                pose_schema_revision=(candidate.pose_schema_revision),
            ),
        )

    def list_candidates(
        self,
        round_id: str,
    ) -> list[PoseActiveLearningCandidateResponse]:
        self._round(round_id)
        rows = list(
            self.session.scalars(
                select(PoseActiveLearningCandidate)
                .where(PoseActiveLearningCandidate.round_id == round_id)
                .order_by(
                    PoseActiveLearningCandidate.acquisition_score.desc(),
                    PoseActiveLearningCandidate.video_track_id,
                    PoseActiveLearningCandidate.focus_frame,
                )
            )
        )
        return [self._candidate_response(item) for item in rows]

    def _refresh_round_status(self, round_id: str) -> None:
        round_record = self._round(round_id)
        candidates = list(
            self.session.scalars(
                select(PoseActiveLearningCandidate).where(
                    PoseActiveLearningCandidate.round_id == round_id
                )
            )
        )
        if candidates and all(item.review_status in {"verified", "skipped"} for item in candidates):
            round_record.status = "complete"
            if round_record.completed_at is None:
                round_record.completed_at = utc_now()

    def review_candidate(
        self,
        candidate_id: str,
        request: PoseActiveLearningReviewRequest,
    ) -> PoseActiveLearningCandidateResponse:
        candidate = self._candidate(candidate_id)
        track = self.session.get(
            VideoTrack,
            candidate.video_track_id,
        )
        if track is None or track.deleted_at is not None:
            raise ConflictError("The source pose track no longer exists")

        if request.action == "start_review":
            if candidate.review_status == "verified":
                return self._candidate_response(candidate)
            if candidate.review_status == "skipped":
                raise ConflictError("Skipped pose Active Learning candidates cannot be reopened")
            if candidate.review_status == "in_review":
                return self._candidate_response(candidate)
            if track.revision != candidate.source_track_revision:
                raise ConflictError(
                    "Pose Active Learning candidate is stale against the "
                    "current track revision. Create a new acquisition round."
                )

            candidate.review_status = "in_review"
            candidate.review_started_track_revision = track.revision
            candidate.reviewed_by = request.reviewed_by
            self.session.commit()
            self.session.refresh(candidate)
            return self._candidate_response(candidate)

        if request.action == "skip":
            if candidate.review_status == "verified":
                raise ConflictError("Verified pose Active Learning candidates cannot be skipped")
            candidate.review_status = "skipped"
            candidate.reviewed_by = request.reviewed_by
            candidate.reviewed_at = utc_now()
            self._refresh_round_status(candidate.round_id)
            self.session.commit()
            self.session.refresh(candidate)
            return self._candidate_response(candidate)

        if candidate.review_status == "verified":
            return self._candidate_response(candidate)

        if (
            request.verified_track_revision is not None
            and request.verified_track_revision != track.revision
        ):
            raise ConflictError("Verified track revision does not match current canonical track")

        if candidate.review_status == "pending":
            if track.revision != candidate.source_track_revision:
                raise ConflictError(
                    "Pose Active Learning candidate changed before scientist "
                    "review started. Re-run acquisition."
                )
        elif candidate.review_status == "in_review":
            started_revision = candidate.review_started_track_revision
            if started_revision is None:
                raise ConflictError("Pose Active Learning review is missing its starting revision")
            if track.revision < started_revision:
                raise ConflictError("Canonical pose track revision moved backwards during review")
        else:
            raise ConflictError(f"Cannot verify candidate in state {candidate.review_status}")

        keyframe = next(
            (
                item
                for item in track.keyframes_json
                if int(item.get("frame", -1)) == candidate.focus_frame
            ),
            None,
        )
        if keyframe is None:
            raise ConflictError("Canonical track no longer contains the selected pose frame")

        pose_observations = keyframe.get(
            "pose_observations",
            [],
        )
        keypoints = keyframe.get("keypoints", [])
        if not pose_observations and not keypoints:
            raise ConflictError("Selected canonical keyframe does not contain pose annotations")

        verified_payload = {
            "schema_version": "pose-active-learning-verified-pose-0001",
            "video_track_id": track.id,
            "track_revision": track.revision,
            "focus_frame": candidate.focus_frame,
            "pose_schema_id": candidate.pose_schema_id,
            "pose_schema_revision": (candidate.pose_schema_revision),
            "pose_observations": pose_observations,
            "keypoints": keypoints,
        }
        verified_pose_sha256 = canonical_json_sha256(verified_payload)

        correction = PoseLandmarkCorrection(
            id=str(uuid4()),
            parent_video_track_id=track.id,
            action="verify_active_learning_pose",
            target_type="pose_active_learning_candidate",
            target_id=candidate.id,
            frame_start=candidate.focus_frame,
            frame_end=candidate.focus_frame,
            reason_code="scientist_verified_active_learning_pose",
            note=request.note,
            before_json={
                "candidate_id": candidate.id,
                "source_track_revision": (candidate.source_track_revision),
                "candidate_provenance_sha256": (candidate.provenance_sha256),
                "acquisition_score": (candidate.acquisition_score),
                "score_components": (candidate.score_components_json),
                "reason_codes": (candidate.reason_codes_json),
            },
            after_json={
                "verified_track_revision": track.revision,
                "verified_pose_sha256": verified_pose_sha256,
                "pose_schema_id": candidate.pose_schema_id,
                "pose_schema_revision": (candidate.pose_schema_revision),
            },
            actor=request.reviewed_by,
        )
        self.session.add(correction)

        candidate.review_status = "verified"
        candidate.verified_track_revision = track.revision
        candidate.verified_pose_sha256 = verified_pose_sha256
        candidate.correction_id = correction.id
        candidate.reviewed_by = request.reviewed_by
        candidate.reviewed_at = utc_now()

        self._refresh_round_status(candidate.round_id)
        self.session.commit()
        self.session.refresh(candidate)
        return self._candidate_response(candidate)

    def export_manifest(
        self,
        round_id: str,
    ) -> PoseActiveLearningExportManifestResponse:
        round_record = self._round(round_id)
        candidates = list(
            self.session.scalars(
                select(PoseActiveLearningCandidate)
                .where(PoseActiveLearningCandidate.round_id == round_id)
                .order_by(
                    PoseActiveLearningCandidate.video_track_id,
                    PoseActiveLearningCandidate.focus_frame,
                )
            )
        )

        verified = [item for item in candidates if item.review_status == "verified"]
        pending = [item for item in candidates if item.review_status in {"pending", "in_review"}]
        skipped = [item for item in candidates if item.review_status == "skipped"]

        return PoseActiveLearningExportManifestResponse(
            round_id=round_record.id,
            project_id=round_record.project_id,
            video_id=round_record.video_id,
            selection_sha256=round_record.selection_sha256,
            selection_algorithm=SELECTION_ALGORITHM,
            selection_algorithm_version=(SELECTION_ALGORITHM_VERSION),
            status=round_record.status,
            retraining_ready=(
                bool(verified)
                and not pending
                and all(item.verified_pose_sha256 is not None for item in verified)
            ),
            verified_candidate_count=len(verified),
            pending_candidate_count=len(pending),
            skipped_candidate_count=len(skipped),
            candidates=[
                {
                    "candidate_id": item.id,
                    "video_track_id": item.video_track_id,
                    "focus_frame": item.focus_frame,
                    "frame_start": item.frame_start,
                    "frame_end": item.frame_end,
                    "review_status": item.review_status,
                    "pose_schema_id": item.pose_schema_id,
                    "pose_schema_revision": (item.pose_schema_revision),
                    "source_track_revision": (item.source_track_revision),
                    "verified_track_revision": (item.verified_track_revision),
                    "verified_pose_sha256": (item.verified_pose_sha256),
                    "candidate_provenance_sha256": (item.provenance_sha256),
                    "source_model_ids": (item.source_model_ids_json),
                    "source_job_ids": (item.source_job_ids_json),
                    "acquisition_score": (item.acquisition_score),
                    "score_components": (item.score_components_json),
                    "reason_codes": (item.reason_codes_json),
                    "correction_id": item.correction_id,
                    "reviewed_by": item.reviewed_by,
                }
                for item in candidates
            ],
        )
