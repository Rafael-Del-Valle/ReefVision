"""Append explicit pose-output decisions in the native identity revision history."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from reefvision.db.models import (
    PoseAnimalIdentity,
    PoseIdentityAssociationRun,
    PoseIdentityCorrection,
    PoseIdentityObservation,
    TemporalReefPoseFrame,
    TemporalReefPoseRun,
)
from reefvision.db.models.project import utc_now
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.schemas.temporal_reefpose import TemporalReviewCreate, TemporalReviewRead
from reefvision.services.temporal_reefpose import TemporalReefPoseService, _check_checksum
from reefvision.services.temporal_reefpose_sources import TEMPORAL_METHOD
from reefvision.storage.datasets import canonical_json_sha256


def review_temporal_run(
    session: Session, project_id: str, run_id: str, payload: TemporalReviewCreate
) -> TemporalReviewRead:
    service = TemporalReefPoseService(session)
    row = service.run(project_id, run_id)
    if row.kind != "inference" or row.result_json is None:
        raise ValidationError("Only completed temporal predictions may be reviewed")
    # A conditional write gives the review an optimistic lock shared with other sessions.
    next_revision = payload.base_revision + 1
    changed = session.scalar(
        update(TemporalReefPoseRun)
        .where(
            TemporalReefPoseRun.id == run_id,
            TemporalReefPoseRun.review_revision == payload.base_revision,
        )
        .values(review_revision=next_revision)
        .returning(TemporalReefPoseRun.id)
    )
    if not changed:
        raise ConflictError("Temporal pose review has changed. Reopen its current revision.")
    if service.source_stale(row):
        raise ConflictError("Source prediction or identity changed. Refine the new revision first.")
    source = row.input_manifest_json["source"]
    recording, schema = source["recording"], source["schema"]
    frame_track = source["frame_track"]
    parameters = {
        "temporal_run_id": row.id,
        "temporal_model_sha256": row.result_json["temporal_model_sha256"],
        "frame_model_sha256": row.result_json["frame_model_sha256"],
        "source_frame_track_id": frame_track["id"],
        "source_frame_track_revision": frame_track["revision"],
        "source_identity": source.get("identity"),
        "pose_output": "scientist_selected_frame_or_temporal",
        "time_source": recording["time_source"],
        "source_discontinuities": [
            item["frame_index"] for item in source["frames"] if item["discontinuity"]
        ],
    }
    selected = {decision.frame_index: decision for decision in payload.frames}
    frames = list(
        session.scalars(
            select(TemporalReefPoseFrame)
            .where(
                TemporalReefPoseFrame.run_id == row.id,
                TemporalReefPoseFrame.frame_index.in_(selected),
            )
            .order_by(TemporalReefPoseFrame.frame_index)
        )
    )
    if len(frames) != len(selected):
        raise ValidationError(
            "Review may only use frames present in the frozen prediction evidence"
        )
    identity_run = (
        session.get(PoseIdentityAssociationRun, row.identity_run_id)
        if row.identity_run_id
        else None
    )
    animal = session.get(PoseAnimalIdentity, row.identity_id) if row.identity_id else None
    if identity_run is None and row.identity_run_id is None and payload.base_revision == 0:
        bounds = source["frames"][0]["frame_index"], source["frames"][-1]["frame_index"]
        identity_run = PoseIdentityAssociationRun(
            project_id=project_id,
            video_id=recording["id"],
            source_model_id=row.result_json.get("model_id"),
            source_job_id=row.job_id,
            pose_schema_id=schema["schema_id"],
            pose_schema_revision=schema["schema_revision"],
            pose_schema_content_hash=schema["content_hash"],
            algorithm=TEMPORAL_METHOD,
            algorithm_version="1",
            parameters_json=parameters,
            parameters_sha256=canonical_json_sha256(parameters),
            input_manifest_sha256=row.input_manifest_sha256,
            source_coordinate_space="source_pixels",
            source_width=recording["width"],
            source_height=recording["height"],
            status="completed",
            revision=next_revision,
            completed_at=utc_now(),
        )
        session.add(identity_run)
        session.flush()
        animal = PoseAnimalIdentity(
            association_run_id=identity_run.id,
            stable_identity_key=f"temporal:{row.id}",
            display_name=f"Reviewed temporal pose · {recording['name']}"[:200],
            origin="scientist",
            verification_state="scientist_confirmed",
            first_frame=bounds[0],
            last_frame=bounds[1],
            revision=next_revision,
        )
        session.add(animal)
        session.flush()
        row.identity_id, row.identity_run_id = animal.id, identity_run.id
    if (
        identity_run is None
        or animal is None
        or (payload.base_revision > 0 and identity_run.revision != payload.base_revision)
    ):
        raise ConflictError("Reviewed pose revisions changed in the identity workspace")

    existing = {
        item.frame_index: item
        for item in session.scalars(
            select(PoseIdentityObservation).where(
                PoseIdentityObservation.association_run_id == identity_run.id,
                PoseIdentityObservation.frame_index.in_(selected),
                PoseIdentityObservation.is_current.is_(True),
            )
        )
    }
    before: dict[str, Any] = {"run_revision": payload.base_revision, "changes": []}
    after: dict[str, Any] = {"run_revision": next_revision, "changes": []}
    expected_ids = {item["id"] for item in schema["landmarks"]}
    for frame in frames:
        evidence = frame.evidence_json
        _check_checksum(evidence, frame.evidence_sha256, "Temporal review evidence")
        decision = selected[frame.frame_index]
        previous = existing.get(frame.frame_index)
        before["changes"].append(
            {
                "frame_index": frame.frame_index,
                "source": frame.review_source,
                "observation_id": previous.id if previous else None,
            }
        )
        accepted = decision.source != "rejected"
        available = (
            (evidence["frame_points"] if decision.source == "frame" else evidence["refined_points"])
            if accepted
            else []
        )
        landmarks = {
            item["landmark_id"]: {**item, "source": decision.source}
            for item in (available or [])
            if item is not None
        }
        for correction in decision.corrections:
            if correction.landmark_id not in expected_ids or (
                correction.x > recording["width"] or correction.y > recording["height"]
            ):
                raise ValidationError("Correction is outside the frozen anatomy or source image")
            landmarks[correction.landmark_id] = {
                **correction.model_dump(mode="json"),
                "visibility": "visible",
                "confidence": None,
                "source": "corrected",
            }
        if accepted and not any(item["x"] is not None for item in landmarks.values()):
            raise ValidationError(
                "Selected pose has no coordinates. Add a correction or reject it."
            )
        if previous:
            previous.is_current = False
        replacement = PoseIdentityObservation(
            id=str(uuid4()),
            observation_series_id=previous.observation_series_id if previous else str(uuid4()),
            revision=previous.revision + 1 if previous else 1,
            supersedes_observation_id=previous.id if previous else None,
            association_run_id=identity_run.id,
            animal_identity_id=animal.id if accepted else None,
            source_video_track_id=frame_track["id"],
            source_detection_key=f"temporal:{row.id}:{frame.frame_index}",
            frame_index=frame.frame_index,
            time_s=evidence["timestamp_seconds"],
            bbox_json=evidence["bbox"],
            landmarks_json=list(landmarks.values()),
            assignment_source="scientist",
            verification_state="scientist_confirmed" if accepted else "rejected",
            visibility_state="visible" if accepted else "absent",
            coordinate_space="source_pixels",
            is_current=True,
        )
        session.add(replacement)
        frame.review_source = decision.source
        after["changes"].append(
            {
                **decision.model_dump(mode="json"),
                "observation_id": replacement.id,
                "evidence_sha256": frame.evidence_sha256,
            }
        )
    identity_run.revision = animal.revision = next_revision
    review = PoseIdentityCorrection(
        association_run_id=identity_run.id,
        revision=next_revision,
        action="review_temporal_pose",
        target_type="association_run",
        target_id=identity_run.id,
        frame_start=frames[0].frame_index,
        frame_end=frames[-1].frame_index,
        before_json=before,
        after_json=after,
        before_sha256=canonical_json_sha256(before),
        after_sha256=canonical_json_sha256(after),
        reason=payload.note,
    )
    session.add(review)
    session.flush()
    accepted_frames = (
        session.scalar(
            select(func.count())
            .select_from(PoseIdentityObservation)
            .where(
                PoseIdentityObservation.animal_identity_id == animal.id,
                PoseIdentityObservation.is_current.is_(True),
            )
        )
        or 0
    )
    session.commit()
    return TemporalReviewRead(
        id=review.id,
        revision=next_revision,
        identity_run_id=identity_run.id,
        identity_id=animal.id,
        accepted_frame_count=accepted_frames,
        source_stale=False,
    )
