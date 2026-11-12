"""Transactional persistence and review operations for pose animal identities."""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    Job,
    PoseAnimalIdentity,
    PoseIdentityAssociationDecision,
    PoseIdentityAssociationRun,
    PoseIdentityCorrection,
    PoseIdentityEvaluationRun,
    PoseIdentityObservation,
    PoseIdentityOcclusion,
    PoseIdentityTruthDataset,
    Project,
    VideoAsset,
    VideoTrack,
)
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.domain.pose_identity_evaluation import (
    IdentityObservation,
    evaluate_pose_identities,
)
from reefvision.domain.pose_identity_tracking import (
    AssociationConfig,
    Landmark,
    PoseDetection,
    associate_pose_identities,
)
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.pose_identity_tracking import (
    PoseAnimalIdentityResponse,
    PoseIdentityAssociationCreateRequest,
    PoseIdentityAssociationRunResponse,
    PoseIdentityCorrectionRequest,
    PoseIdentityCorrectionResponse,
    PoseIdentityEvaluationRequest,
    PoseIdentityEvaluationResponse,
    PoseIdentityObservationResponse,
    PoseIdentityTruthDatasetCreateRequest,
    PoseIdentityTruthDatasetResponse,
)
from reefvision.schemas.videos import VideoTrackKeyframe
from reefvision.storage.datasets import canonical_json_sha256


class PoseIdentityTrackingCancelled(Exception):
    pass


def _json_hash(value: Any) -> str:
    return canonical_json_sha256(value)


class PoseIdentityTrackingService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _run(self, run_id: str) -> PoseIdentityAssociationRun:
        run = self.session.get(PoseIdentityAssociationRun, run_id)
        if run is None:
            raise NotFoundError("Pose identity association run not found")
        return run

    def _tracks(
        self, project_id: str, payload: PoseIdentityAssociationCreateRequest
    ) -> tuple[Project, VideoAsset, list[VideoTrack]]:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        video = self.session.get(VideoAsset, payload.video_id)
        if video is None or video.project_id != project_id:
            raise ValidationError("Selected video does not belong to the project")
        unique_ids = list(dict.fromkeys(payload.source_track_ids))
        tracks = list(
            self.session.scalars(
                select(VideoTrack).where(
                    VideoTrack.id.in_(unique_ids), VideoTrack.deleted_at.is_(None)
                )
            )
        )
        by_id = {track.id: track for track in tracks}
        if len(by_id) != len(unique_ids):
            raise ValidationError("All source pose tracks must exist and be active")
        ordered = [by_id[track_id] for track_id in unique_ids]
        if any(track.video_id != video.id for track in ordered):
            raise ValidationError("All source pose tracks must belong to the selected video")
        expected = (
            payload.pose_schema_id,
            payload.pose_schema_revision,
            payload.pose_schema_content_hash,
        )
        for track in ordered:
            binding = dict((track.metadata_json or {}).get("pose_landmark_schema") or {})
            if (
                binding
                and (
                    str(binding.get("schema_id")),
                    int(binding.get("schema_revision") or 0),
                    str(binding.get("content_hash")),
                )
                != expected
            ):
                raise ValidationError(
                    "Source pose track schema identity, revision, or content hash does not match"
                )
        return project, video, ordered

    def submit(self, project_id: str, payload: PoseIdentityAssociationCreateRequest) -> JobResponse:
        _project, video, tracks = self._tracks(project_id, payload)
        manifest = {
            "video_id": video.id,
            "video_sha256": video.sha256,
            "pose_schema": {
                "id": payload.pose_schema_id,
                "revision": payload.pose_schema_revision,
                "content_hash": payload.pose_schema_content_hash,
            },
            "tracks": [
                {
                    "id": track.id,
                    "revision": track.revision,
                    "keyframes_sha256": _json_hash(track.keyframes_json),
                }
                for track in tracks
            ],
        }
        parameters = payload.parameters.model_dump(mode="json")
        run = PoseIdentityAssociationRun(
            project_id=project_id,
            video_id=video.id,
            source_model_id=next(
                (track.source_model_id for track in tracks if track.source_model_id), None
            ),
            pose_schema_id=payload.pose_schema_id,
            pose_schema_revision=payload.pose_schema_revision,
            pose_schema_content_hash=payload.pose_schema_content_hash,
            algorithm="reefpose-geometric-motion-association",
            algorithm_version="1.0.0",
            parameters_json=parameters,
            parameters_sha256=_json_hash(parameters),
            input_manifest_sha256=_json_hash(manifest),
            source_coordinate_space="source_pixels",
            source_width=video.width_px,
            source_height=video.height_px,
            status="queued",
            progress_json={"stage": "queued", "current": 0, "total": len(tracks)},
        )
        self.session.add(run)
        self.session.flush()
        request_json = {
            "run_id": run.id,
            "project_id": project_id,
            "video_id": video.id,
            "source_track_ids": [track.id for track in tracks],
            "pose_schema_id": payload.pose_schema_id,
            "pose_schema_revision": payload.pose_schema_revision,
            "pose_schema_content_hash": payload.pose_schema_content_hash,
            "parameters": parameters,
            "device": payload.device,
            "input_manifest": manifest,
        }
        job = Job(
            project_id=project_id,
            job_type="pose_identity_tracking",
            status="queued",
            progress_current=0,
            progress_total=max(1, sum(len(track.keyframes_json or []) for track in tracks)),
            request_json=request_json,
            result_json={"run_id": run.id, "stage": "queued"},
        )
        self.session.add(job)
        self.session.flush()
        run.source_job_id = job.id
        self.session.commit()
        self.session.refresh(job)
        return JobResponse.model_validate(job)

    @staticmethod
    def _detections(tracks: list[VideoTrack]) -> list[PoseDetection]:
        detections: list[PoseDetection] = []
        for track in tracks:
            for raw in track.keyframes_json or []:
                try:
                    keyframe = VideoTrackKeyframe.model_validate(raw)
                except ValueError as exc:
                    raise ValidationError("Stored pose track keyframes are invalid") from exc
                landmarks = tuple(
                    Landmark(
                        landmark_id=item.landmark_id or item.id,
                        x=float(item.x),
                        y=float(item.y),
                        confidence=float(item.confidence) if item.confidence is not None else None,
                        visibility=item.status,
                    )
                    for item in keyframe.pose_observations or []
                )
                detections.append(
                    PoseDetection(
                        detection_id=f"{track.id}:{keyframe.frame}",
                        source_track_id=track.id,
                        frame_index=keyframe.frame,
                        bbox=(
                            float(keyframe.bbox[0]),
                            float(keyframe.bbox[1]),
                            float(keyframe.bbox[2]),
                            float(keyframe.bbox[3]),
                        ),
                        landmarks=landmarks,
                        confidence=float(keyframe.confidence or 0.0),
                    )
                )
        return detections

    def execute(
        self,
        run_id: str,
        source_track_ids: list[str],
        *,
        cancellation_check: Callable[[], None] | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> PoseIdentityAssociationRun:
        run = self._run(run_id)
        tracks = list(
            self.session.scalars(
                select(VideoTrack)
                .where(VideoTrack.id.in_(source_track_ids), VideoTrack.deleted_at.is_(None))
                .order_by(VideoTrack.id)
            )
        )
        if len(tracks) != len(set(source_track_ids)):
            raise ValidationError("One or more source pose tracks disappeared")
        detections = self._detections(tracks)
        if not detections:
            raise ValidationError("Source pose tracks contain no detections")
        if cancellation_check:
            cancellation_check()
        config = AssociationConfig(**dict(run.parameters_json or {}))
        result = associate_pose_identities(detections, config)
        detection_by_id = {item.detection_id: item for item in detections}
        identity_by_key: dict[str, PoseAnimalIdentity] = {}
        for summary in result.identities:
            record = PoseAnimalIdentity(
                association_run_id=run.id,
                stable_identity_key=summary.identity_key,
                display_name=summary.identity_key,
                origin="model",
                verification_state="unreviewed",
                lifecycle_state=summary.lifecycle_state,
                first_frame=summary.first_frame,
                last_frame=summary.last_frame,
                mean_association_confidence=summary.mean_association_confidence,
            )
            self.session.add(record)
            identity_by_key[summary.identity_key] = record
        self.session.flush()

        observation_by_detection: dict[str, PoseIdentityObservation] = {}
        total = len(result.assignments)
        for index, assignment in enumerate(result.assignments, start=1):
            if cancellation_check:
                cancellation_check()
            detection = detection_by_id[assignment.detection_id]
            identity = (
                identity_by_key.get(assignment.identity_key) if assignment.identity_key else None
            )
            observation = PoseIdentityObservation(
                observation_series_id=_json_hash(
                    {"run_id": run.id, "detection_id": detection.detection_id}
                )[:36],
                revision=1,
                association_run_id=run.id,
                animal_identity_id=identity.id if identity else None,
                source_video_track_id=detection.source_track_id,
                source_detection_key=detection.detection_id,
                frame_index=detection.frame_index,
                time_s=None,
                bbox_json=list(detection.bbox),
                landmarks_json=[asdict(item) for item in detection.landmarks],
                detection_confidence=detection.confidence,
                association_confidence=assignment.association_confidence,
                visibility_state="visible",
                assignment_source="model",
                verification_state="unreviewed",
                coordinate_space="source_pixels",
                is_current=True,
            )
            self.session.add(observation)
            observation_by_detection[detection.detection_id] = observation
            if progress:
                progress(index, total)
        self.session.flush()

        latest_by_identity: dict[str, PoseIdentityObservation] = {}
        for decision in sorted(
            result.decisions, key=lambda item: (item.frame_index, item.detection_id)
        ):
            observation = observation_by_detection[decision.detection_id]
            previous = (
                latest_by_identity.get(decision.candidate_identity_key)
                if decision.candidate_identity_key
                else None
            )
            self.session.add(
                PoseIdentityAssociationDecision(
                    association_run_id=run.id,
                    observation_id=observation.id,
                    candidate_identity_id=(
                        identity_by_key[decision.candidate_identity_key].id
                        if decision.candidate_identity_key
                        else None
                    ),
                    previous_observation_id=previous.id if previous else None,
                    candidate_rank=decision.candidate_rank,
                    selected=decision.selected,
                    passed_gate=decision.passed_gate,
                    gate_reason=decision.gate_reason,
                    total_cost=decision.total_cost,
                    acceptance_threshold=decision.acceptance_threshold,
                    score_components_json=decision.score_components,
                    association_confidence=decision.association_confidence,
                    algorithm=result.algorithm,
                    algorithm_version=result.algorithm_version,
                    parameters_sha256=result.parameters_sha256,
                )
            )
            if decision.selected and decision.candidate_identity_key:
                latest_by_identity[decision.candidate_identity_key] = observation
        for interval in result.occlusions:
            self.session.add(
                PoseIdentityOcclusion(
                    association_run_id=run.id,
                    animal_identity_id=identity_by_key[interval.identity_key].id,
                    start_frame=interval.start_frame,
                    end_frame=interval.end_frame,
                    reason="missed_detection",
                    recovery_confidence=interval.recovery_confidence,
                )
            )
        run.status = "completed"
        run.progress_json = {"stage": "completed", "current": total, "total": total}
        run.completed_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(run)
        return run

    def get(self, run_id: str) -> PoseIdentityAssociationRunResponse:
        return PoseIdentityAssociationRunResponse.model_validate(self._run(run_id))

    def list_for_project(
        self, project_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[PoseIdentityAssociationRunResponse]:
        records = self.session.scalars(
            select(PoseIdentityAssociationRun)
            .where(PoseIdentityAssociationRun.project_id == project_id)
            .order_by(PoseIdentityAssociationRun.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return [PoseIdentityAssociationRunResponse.model_validate(item) for item in records]

    def identities(self, run_id: str) -> list[PoseAnimalIdentityResponse]:
        self._run(run_id)
        records = self.session.scalars(
            select(PoseAnimalIdentity)
            .where(PoseAnimalIdentity.association_run_id == run_id)
            .order_by(PoseAnimalIdentity.stable_identity_key)
        )
        return [PoseAnimalIdentityResponse.model_validate(item) for item in records]

    def observations(
        self, run_id: str, *, include_history: bool = False
    ) -> list[PoseIdentityObservationResponse]:
        self._run(run_id)
        statement = select(PoseIdentityObservation).where(
            PoseIdentityObservation.association_run_id == run_id
        )
        if not include_history:
            statement = statement.where(PoseIdentityObservation.is_current.is_(True))
        records = self.session.scalars(
            statement.order_by(
                PoseIdentityObservation.frame_index,
                PoseIdentityObservation.source_detection_key,
                PoseIdentityObservation.revision,
            )
        )
        return [PoseIdentityObservationResponse.model_validate(item) for item in records]

    def decisions(self, run_id: str) -> list[dict[str, Any]]:
        self._run(run_id)
        records = self.session.scalars(
            select(PoseIdentityAssociationDecision)
            .where(PoseIdentityAssociationDecision.association_run_id == run_id)
            .order_by(
                PoseIdentityAssociationDecision.observation_id,
                PoseIdentityAssociationDecision.candidate_rank,
            )
        )
        return [
            {
                "id": item.id,
                "observation_id": item.observation_id,
                "candidate_identity_id": item.candidate_identity_id,
                "candidate_rank": item.candidate_rank,
                "selected": item.selected,
                "passed_gate": item.passed_gate,
                "gate_reason": item.gate_reason,
                "total_cost": item.total_cost,
                "acceptance_threshold": item.acceptance_threshold,
                "association_confidence": item.association_confidence,
                "score_components_json": dict(item.score_components_json),
                "algorithm": item.algorithm,
                "algorithm_version": item.algorithm_version,
                "parameters_sha256": item.parameters_sha256,
            }
            for item in records
        ]

    def review_queue(self, run_id: str) -> list[PoseIdentityObservationResponse]:
        run = self._run(run_id)
        threshold = float((run.parameters_json or {}).get("low_confidence_threshold", 0.6))
        records = self.session.scalars(
            select(PoseIdentityObservation)
            .where(
                PoseIdentityObservation.association_run_id == run_id,
                PoseIdentityObservation.is_current.is_(True),
                PoseIdentityObservation.association_confidence < threshold,
            )
            .order_by(PoseIdentityObservation.association_confidence)
        )
        return [PoseIdentityObservationResponse.model_validate(item) for item in records]

    def _revision_copy(
        self,
        observation: PoseIdentityObservation,
        *,
        identity_id: str | None,
        verification_state: str,
    ) -> PoseIdentityObservation:
        observation.is_current = False
        replacement = PoseIdentityObservation(
            observation_series_id=observation.observation_series_id,
            revision=observation.revision + 1,
            supersedes_observation_id=observation.id,
            association_run_id=observation.association_run_id,
            animal_identity_id=identity_id,
            source_video_track_id=observation.source_video_track_id,
            source_detection_key=observation.source_detection_key,
            frame_index=observation.frame_index,
            time_s=observation.time_s,
            bbox_json=list(observation.bbox_json),
            landmarks_json=list(observation.landmarks_json),
            detection_confidence=observation.detection_confidence,
            association_confidence=observation.association_confidence,
            visibility_state=observation.visibility_state,
            assignment_source="scientist",
            verification_state=verification_state,
            coordinate_space=observation.coordinate_space,
            is_current=True,
        )
        self.session.add(replacement)
        return replacement

    def correct(
        self, run_id: str, payload: PoseIdentityCorrectionRequest
    ) -> PoseIdentityCorrectionResponse:
        run = self._run(run_id)
        if run.status != "completed":
            raise ValidationError("Only completed identity runs can be corrected")
        before: dict[str, Any] = {"run_revision": run.revision, "changes": []}
        after: dict[str, Any] = {"run_revision": run.revision + 1, "changes": []}

        destination = None
        if payload.destination_identity_id:
            destination = self.session.get(PoseAnimalIdentity, payload.destination_identity_id)
            if destination is None or destination.association_run_id != run.id:
                raise ValidationError("Destination identity does not belong to this run")

        observations: list[PoseIdentityObservation]
        if payload.target_type == "observation":
            observation = self.session.get(PoseIdentityObservation, payload.target_id)
            if (
                observation is None
                or observation.association_run_id != run.id
                or not observation.is_current
            ):
                raise ValidationError("Target observation is not a current revision in this run")
            observations = [observation]
        else:
            identity = self.session.get(PoseAnimalIdentity, payload.target_id)
            if identity is None or identity.association_run_id != run.id:
                raise ValidationError("Target identity does not belong to this run")
            statement = select(PoseIdentityObservation).where(
                PoseIdentityObservation.association_run_id == run.id,
                PoseIdentityObservation.animal_identity_id == identity.id,
                PoseIdentityObservation.is_current.is_(True),
            )
            if payload.frame_start is not None:
                statement = statement.where(
                    PoseIdentityObservation.frame_index >= payload.frame_start
                )
            if payload.frame_end is not None:
                statement = statement.where(
                    PoseIdentityObservation.frame_index <= payload.frame_end
                )
            observations = list(self.session.scalars(statement))

        if not observations:
            raise ValidationError("Correction target contains no current observations")

        swap_observations: list[PoseIdentityObservation] = []
        if payload.action == "swap":
            if payload.target_type == "observation" or destination is None:
                raise ValidationError("swap requires two identity targets")
            swap_statement = select(PoseIdentityObservation).where(
                PoseIdentityObservation.association_run_id == run.id,
                PoseIdentityObservation.animal_identity_id == destination.id,
                PoseIdentityObservation.is_current.is_(True),
            )
            if payload.frame_start is not None:
                swap_statement = swap_statement.where(
                    PoseIdentityObservation.frame_index >= payload.frame_start
                )
            if payload.frame_end is not None:
                swap_statement = swap_statement.where(
                    PoseIdentityObservation.frame_index <= payload.frame_end
                )
            swap_observations = list(self.session.scalars(swap_statement))
            if not swap_observations:
                raise ValidationError("Destination identity has no observations in the swap range")

        if payload.action == "split":
            source_identity = self.session.get(
                PoseAnimalIdentity, observations[0].animal_identity_id
            )
            assert source_identity is not None
            count = int(
                self.session.scalar(
                    select(func.count(PoseAnimalIdentity.id)).where(
                        PoseAnimalIdentity.association_run_id == run.id
                    )
                )
                or 0
            )
            destination = PoseAnimalIdentity(
                association_run_id=run.id,
                stable_identity_key=f"animal-scientist-{count + 1:04d}",
                display_name=f"Split from {source_identity.display_name}",
                origin="scientist",
                verification_state="scientist_confirmed",
                lifecycle_state="active",
                first_frame=min(item.frame_index for item in observations),
                last_frame=max(item.frame_index for item in observations),
                revision=1,
            )
            self.session.add(destination)
            self.session.flush()

        if payload.action == "reject":
            destination_id = None
            verification = "scientist_rejected"
        elif payload.action == "accept":
            destination_id = observations[0].animal_identity_id
            verification = "scientist_confirmed"
        else:
            if destination is None:
                raise ValidationError(f"{payload.action} requires a destination identity")
            destination_id = destination.id
            verification = "scientist_confirmed"

        correction_targets = [(observation, destination_id) for observation in observations]
        if payload.action == "swap":
            correction_targets.extend(
                (observation, payload.target_id) for observation in swap_observations
            )

        for observation, corrected_identity_id in correction_targets:
            before["changes"].append(
                {
                    "observation_id": observation.id,
                    "identity_id": observation.animal_identity_id,
                    "revision": observation.revision,
                }
            )
            replacement = self._revision_copy(
                observation,
                identity_id=corrected_identity_id,
                verification_state=verification,
            )
            self.session.flush()
            after["changes"].append(
                {
                    "observation_id": replacement.id,
                    "identity_id": replacement.animal_identity_id,
                    "revision": replacement.revision,
                    "supersedes_observation_id": observation.id,
                }
            )

        if payload.action == "accept" and observations[0].animal_identity_id:
            identity = self.session.get(PoseAnimalIdentity, observations[0].animal_identity_id)
            if identity is not None:
                identity.verification_state = "scientist_confirmed"
                identity.revision += 1
        if payload.action == "merge" and payload.target_type != "observation":
            source_identity = self.session.get(PoseAnimalIdentity, payload.target_id)
            if source_identity is not None:
                source_identity.lifecycle_state = "merged"
                source_identity.revision += 1

        run.revision += 1
        correction = PoseIdentityCorrection(
            association_run_id=run.id,
            revision=run.revision,
            action=payload.action,
            target_type=payload.target_type,
            target_id=payload.target_id,
            frame_start=payload.frame_start,
            frame_end=payload.frame_end,
            before_json=before,
            after_json=after,
            before_sha256=_json_hash(before),
            after_sha256=_json_hash(after),
            reason=payload.reason,
            actor=payload.actor,
        )
        self.session.add(correction)
        self.session.commit()
        self.session.refresh(correction)
        return PoseIdentityCorrectionResponse.model_validate(correction)

    def corrections(self, run_id: str) -> list[PoseIdentityCorrectionResponse]:
        self._run(run_id)
        records = self.session.scalars(
            select(PoseIdentityCorrection)
            .where(PoseIdentityCorrection.association_run_id == run_id)
            .order_by(PoseIdentityCorrection.revision)
        )
        return [PoseIdentityCorrectionResponse.model_validate(item) for item in records]

    def export_json(self, run_id: str) -> dict[str, Any]:
        return {
            "schema_version": "reefpose-identity-export-0001",
            "coordinate_space": "source_pixels",
            "association_run": self.get(run_id).model_dump(mode="json"),
            "identities": [item.model_dump(mode="json") for item in self.identities(run_id)],
            "observations": [
                item.model_dump(mode="json")
                for item in self.observations(run_id, include_history=True)
            ],
            "decisions": self.decisions(run_id),
            "corrections": [item.model_dump(mode="json") for item in self.corrections(run_id)],
        }

    def export_csv(self, run_id: str) -> str:
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(
            [
                "run_id",
                "run_revision",
                "observation_id",
                "observation_revision",
                "frame_index",
                "identity_id",
                "source_video_track_id",
                "association_confidence",
                "verification_state",
                "coordinate_space",
            ]
        )
        run = self._run(run_id)
        for item in self.observations(run_id):
            writer.writerow(
                [
                    run.id,
                    run.revision,
                    item.id,
                    item.revision,
                    item.frame_index,
                    item.animal_identity_id or "",
                    item.source_video_track_id,
                    item.association_confidence,
                    item.verification_state,
                    item.coordinate_space,
                ]
            )
        return output.getvalue()

    def create_truth_dataset(
        self, project_id: str, payload: PoseIdentityTruthDatasetCreateRequest
    ) -> PoseIdentityTruthDatasetResponse:
        project = self.session.get(Project, project_id)
        video = self.session.get(VideoAsset, payload.video_id)
        if project is None:
            raise NotFoundError("Project not found")
        if video is None or video.project_id != project_id:
            raise ValidationError("Identity truth video does not belong to the project")
        normalized: list[dict[str, Any]] = []
        keys: set[tuple[str, int]] = set()
        for raw in payload.observations:
            identity_id = str(raw.get("identity_id") or "")
            frame_index = raw.get("frame_index")
            bbox = raw.get("bbox")
            if not identity_id or not isinstance(frame_index, int):
                raise ValidationError(
                    "Truth observations require identity_id and integer frame_index"
                )
            if frame_index < 0 or frame_index >= video.frame_count:
                raise ValidationError("Truth observation frame exceeds the source video")
            if (
                not isinstance(bbox, list)
                or len(bbox) != 4
                or any(not isinstance(value, int | float) for value in bbox)
            ):
                raise ValidationError("Truth observations require a four-value bounding box")
            box = [float(value) for value in bbox]
            if box[0] < 0 or box[1] < 0 or box[2] <= 0 or box[3] <= 0:
                raise ValidationError("Truth bounding boxes must use source-pixel coordinates")
            key = (identity_id, frame_index)
            if key in keys:
                raise ValidationError("Truth contains duplicate identity/frame observations")
            keys.add(key)
            normalized.append({"identity_id": identity_id, "frame_index": frame_index, "bbox": box})
        manifest = {
            "schema_version": "reefpose-identity-truth-0001",
            "project_id": project_id,
            "video_id": video.id,
            "video_sha256": video.sha256,
            "coordinate_space": "source_pixels",
            "scientific_context": payload.scientific_context,
            "pose_schema": {
                "id": payload.pose_schema_id,
                "revision": payload.pose_schema_revision,
                "content_hash": payload.pose_schema_content_hash,
            },
            "observations": sorted(
                normalized, key=lambda item: (item["frame_index"], item["identity_id"])
            ),
        }
        manifest_sha256 = _json_hash(manifest)
        existing = self.session.scalar(
            select(PoseIdentityTruthDataset).where(
                PoseIdentityTruthDataset.manifest_sha256 == manifest_sha256
            )
        )
        if existing is not None:
            return PoseIdentityTruthDatasetResponse.model_validate(existing)
        now = datetime.now(UTC)
        record = PoseIdentityTruthDataset(
            project_id=project_id,
            video_id=video.id,
            name=payload.name,
            pose_schema_id=payload.pose_schema_id,
            pose_schema_revision=payload.pose_schema_revision,
            pose_schema_content_hash=payload.pose_schema_content_hash,
            manifest_json=manifest,
            manifest_sha256=manifest_sha256,
            verification_state="scientist_verified",
            verified_by=payload.verified_by,
            verified_at=now,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return PoseIdentityTruthDatasetResponse.model_validate(record)

    def evaluate(
        self, run_id: str, payload: PoseIdentityEvaluationRequest
    ) -> PoseIdentityEvaluationResponse:
        run = self._run(run_id)
        if run.status != "completed":
            raise ValidationError("Only completed identity runs can be evaluated")
        truth = self.session.get(PoseIdentityTruthDataset, payload.truth_dataset_id)
        if truth is None:
            raise NotFoundError("Identity truth dataset not found")
        if truth.verification_state != "scientist_verified":
            raise ValidationError("Identity evaluation requires scientist-verified truth")
        if truth.project_id != run.project_id or truth.video_id != run.video_id:
            raise ValidationError("Identity truth and association run must share project and video")
        if (
            truth.pose_schema_id != run.pose_schema_id
            or truth.pose_schema_revision != run.pose_schema_revision
            or truth.pose_schema_content_hash != run.pose_schema_content_hash
        ):
            raise ValidationError("Identity truth pose schema is incompatible with the run")

        truth_observations = [
            IdentityObservation(
                identity_id=str(item["identity_id"]),
                frame_index=int(item["frame_index"]),
                bbox=(
                    float(item["bbox"][0]),
                    float(item["bbox"][1]),
                    float(item["bbox"][2]),
                    float(item["bbox"][3]),
                ),
            )
            for item in list((truth.manifest_json or {}).get("observations") or [])
        ]
        prediction_records = list(
            self.session.scalars(
                select(PoseIdentityObservation).where(
                    PoseIdentityObservation.association_run_id == run.id,
                    PoseIdentityObservation.is_current.is_(True),
                    PoseIdentityObservation.animal_identity_id.is_not(None),
                    PoseIdentityObservation.verification_state != "scientist_rejected",
                )
            )
        )
        predictions = [
            IdentityObservation(
                identity_id=str(item.animal_identity_id),
                frame_index=item.frame_index,
                bbox=(
                    float(item.bbox_json[0]),
                    float(item.bbox_json[1]),
                    float(item.bbox_json[2]),
                    float(item.bbox_json[3]),
                ),
            )
            for item in prediction_records
        ]
        report = evaluate_pose_identities(
            truth_observations,
            predictions,
            iou_threshold=payload.spatial_iou_threshold,
        )
        metrics = asdict(report)
        warnings = [
            "Identity association metrics do not measure anatomical landmark localization accuracy."
        ]
        if (truth.manifest_json or {}).get("scientific_context") == "synthetic_engineering":
            warnings.append(
                "Synthetic engineering truth validates software behavior, not biological accuracy."
            )
        configuration = {
            "spatial_iou_threshold": payload.spatial_iou_threshold,
            "spatial_matching_policy": "global-frame-iou",
            "identity_mapping_policy": "global-maximum-overlap-count",
        }
        provenance = {
            "schema_version": "reefpose-identity-evaluation-0001",
            "association_run_id": run.id,
            "association_run_revision": run.revision,
            "association_parameters_sha256": run.parameters_sha256,
            "association_input_manifest_sha256": run.input_manifest_sha256,
            "truth_dataset_id": truth.id,
            "truth_manifest_sha256": truth.manifest_sha256,
            "pose_schema_id": run.pose_schema_id,
            "pose_schema_revision": run.pose_schema_revision,
            "pose_schema_content_hash": run.pose_schema_content_hash,
            "coordinate_space": run.source_coordinate_space,
        }
        result_payload = {
            "configuration": configuration,
            "metrics": metrics,
            "warnings": warnings,
            "provenance": provenance,
        }
        record = PoseIdentityEvaluationRun(
            association_run_id=run.id,
            association_run_revision=run.revision,
            truth_dataset_id=truth.id,
            configuration_json=configuration,
            metrics_json=metrics,
            warnings_json=warnings,
            provenance_json=provenance,
            result_sha256=_json_hash(result_payload),
        )
        existing = self.session.scalar(
            select(PoseIdentityEvaluationRun).where(
                PoseIdentityEvaluationRun.result_sha256 == record.result_sha256
            )
        )
        if existing is not None:
            return PoseIdentityEvaluationResponse.model_validate(existing)
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return PoseIdentityEvaluationResponse.model_validate(record)

    def get_evaluation(self, evaluation_id: str) -> PoseIdentityEvaluationResponse:
        record = self.session.get(PoseIdentityEvaluationRun, evaluation_id)
        if record is None:
            raise NotFoundError("Pose identity evaluation not found")
        return PoseIdentityEvaluationResponse.model_validate(record)
