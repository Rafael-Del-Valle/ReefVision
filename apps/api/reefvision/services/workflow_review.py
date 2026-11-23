"""Human-review pause and resume semantics for persistent workflow runs."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from reefvision.db.models import (
    ClassificationPrediction,
    Job,
    PredictionProposal,
    VideoAsset,
    VideoTrack,
    WorkflowArtifact,
    WorkflowGraphRecord,
    WorkflowNodeRun,
    WorkflowRun,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.workflow_execution import (
    WorkflowReviewResumeRequest,
    WorkflowRunResponse,
)
from reefvision.services.pose_active_learning import (
    PoseActiveLearningService,
)
from reefvision.services.pose_temporal_tracking import (
    PoseTemporalTrackingService,
)
from reefvision.services.workflow_auto_label import (
    ensure_disagreement_active_learning_round,
    materialize_consensus_annotations,
)
from reefvision.storage.datasets import canonical_json_sha256

REVIEW_GATE_NODE_TYPES = {
    "detection_review_gate",
    "mask_review_gate",
    "classification_review_gate",
    "pose_review_gate",
    "pose_active_learning_review_gate",
}


class WorkflowReviewRequired(RuntimeError):
    """Signal that execution reached a human-review boundary instead of failing."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = dict(details or {})


def _now() -> datetime:
    return datetime.now(UTC)


REVIEW_GATE_INPUT_TYPES: dict[str, frozenset[str]] = {
    "detection_review_gate": frozenset({"detection_proposals", "detection_consensus"}),
    "mask_review_gate": frozenset({"mask_proposals"}),
    "classification_review_gate": frozenset({"classification_predictions"}),
    "pose_review_gate": frozenset({"pose_temporal_tracks"}),
    "pose_active_learning_review_gate": frozenset({"pose_active_learning_round"}),
}



def _verify_review_graph_binding(
    session: Session,
    node_run: WorkflowNodeRun,
    producer: WorkflowNodeRun,
    artifact: WorkflowArtifact,
    *,
    project_id: str,
) -> None:
    """Bind an approval to its immutable saved graph edge, not only a producer row.

    A re-signed artifact from another succeeded node in the same run must not
    replace the research cohort originally wired to the human-review gate.
    """
    run = session.get(WorkflowRun, node_run.workflow_run_id)
    graph = (
        session.get(WorkflowGraphRecord, run.workflow_graph_record_id)
        if run is not None
        else None
    )
    graph_json = graph.graph_json if graph is not None else None
    if (
        run is None
        or run.project_id != project_id
        or graph is None
        or graph.project_id != project_id
        or graph.graph_sha256 != run.graph_sha256
        or not isinstance(graph_json, dict)
        or canonical_json_sha256(graph_json) != graph.graph_sha256
    ):
        raise ValidationError("Workflow review saved graph provenance failed validation")

    nodes = graph_json.get("nodes")
    edges = graph_json.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValidationError("Workflow review saved graph is missing node or edge evidence")

    review_nodes = [
        item
        for item in nodes
        if isinstance(item, dict) and item.get("node_id") == node_run.node_id
    ]
    producer_nodes = [
        item
        for item in nodes
        if isinstance(item, dict) and item.get("node_id") == producer.node_id
    ]
    if (
        len(review_nodes) != 1
        or review_nodes[0].get("node_type") != node_run.node_type
        or len(producer_nodes) != 1
        or producer_nodes[0].get("node_type") != producer.node_type
    ):
        raise ValidationError("Workflow review node or producer differs from saved graph")

    incoming = [
        edge
        for edge in edges
        if isinstance(edge, dict) and edge.get("target_node_id") == node_run.node_id
    ]
    if (
        len(incoming) != 1
        or incoming[0].get("source_node_id") != producer.node_id
        or incoming[0].get("source_port_id") != artifact.producer_port_id
        or not isinstance(incoming[0].get("target_port_id"), str)
        or not incoming[0]["target_port_id"]
    ):
        raise ValidationError("Workflow review input is not connected to its saved graph edge")

def _input_artifacts(
    session: Session, node_run: WorkflowNodeRun, *, project_id: str
) -> list[WorkflowArtifact]:
    """Require the original, intact, same-run scientific input before approval."""
    artifact_ids = node_run.input_artifact_ids_json
    if (
        not isinstance(artifact_ids, list)
        or len(artifact_ids) != 1
        or type(artifact_ids[0]) is not str
        or not artifact_ids[0]
    ):
        raise ValidationError("Workflow review gate has invalid saved input bindings")
    artifact = session.get(WorkflowArtifact, artifact_ids[0])
    if artifact is None:
        raise ValidationError("Workflow review input artifact no longer exists")
    if (
        artifact.workflow_run_id != node_run.workflow_run_id
        or artifact.data_type not in REVIEW_GATE_INPUT_TYPES[node_run.node_type]
    ):
        raise ValidationError("Workflow review input has invalid run or scientific data type")
    producer = session.get(WorkflowNodeRun, artifact.producer_node_run_id)
    if (
        producer is None
        or producer.workflow_run_id != node_run.workflow_run_id
        or producer.status != "succeeded"
        or not isinstance(producer.output_artifact_ids_json, list)
        or artifact.id not in producer.output_artifact_ids_json
    ):
        raise ValidationError("Workflow review input lost its saved producer provenance")
    _verify_review_graph_binding(
        session, node_run, producer, artifact, project_id=project_id
    )
    payload = artifact.payload_json
    if (
        not isinstance(payload, dict)
        or artifact.payload_sha256 != canonical_json_sha256(payload)
        or payload.get("project_id") not in (None, project_id)
    ):
        raise ValidationError("Workflow review input failed project or checksum validation")
    return [artifact]


def _pending_review_count(
    session: Session, artifacts: list[WorkflowArtifact], *, project_id: str
) -> int:
    proposal_ids: set[str] = set()
    classification_ids: set[str] = set()
    for artifact in artifacts:
        if artifact.data_type in {"detection_proposals", "mask_proposals"}:
            key = "proposal_ids"
            target = proposal_ids
        elif artifact.data_type == "classification_predictions":
            key = "prediction_ids"
            target = classification_ids
        else:
            continue
        raw_ids = artifact.payload_json.get(key, [])
        if not isinstance(raw_ids, list) or any(
            type(value) is not str or not value for value in raw_ids
        ):
            raise ValidationError("Workflow review input has malformed prediction identifiers")
        if len(raw_ids) != len(set(raw_ids)):
            raise ValidationError("Workflow review input has duplicate prediction identifiers")
        target.update(raw_ids)

    pending = 0
    if proposal_ids:
        matched = int(
            session.scalar(
                select(func.count(PredictionProposal.id)).where(
                    PredictionProposal.id.in_(proposal_ids),
                    PredictionProposal.project_id == project_id,
                )
            )
            or 0
        )
        if matched != len(proposal_ids):
            raise ValidationError(
                "Workflow review cannot approve missing or foreign prediction proposals"
            )
        pending += int(
            session.scalar(
                select(func.count(PredictionProposal.id)).where(
                    PredictionProposal.id.in_(proposal_ids),
                    PredictionProposal.project_id == project_id,
                    PredictionProposal.review_status == "pending",
                )
            )
            or 0
        )
    if classification_ids:
        matched = int(
            session.scalar(
                select(func.count(ClassificationPrediction.id)).where(
                    ClassificationPrediction.id.in_(classification_ids),
                    ClassificationPrediction.project_id == project_id,
                )
            )
            or 0
        )
        if matched != len(classification_ids):
            raise ValidationError(
                "Workflow review cannot approve missing or foreign classification predictions"
            )
        pending += int(
            session.scalar(
                select(func.count(ClassificationPrediction.id)).where(
                    ClassificationPrediction.id.in_(classification_ids),
                    ClassificationPrediction.project_id == project_id,
                    ClassificationPrediction.status == "pending",
                )
            )
            or 0
        )
    return pending


def _disagreement_artifact_for_consensus(
    session: Session,
    consensus_artifact: WorkflowArtifact,
) -> WorkflowArtifact | None:
    return session.scalar(
        select(WorkflowArtifact)
        .where(
            WorkflowArtifact.workflow_run_id == consensus_artifact.workflow_run_id,
            WorkflowArtifact.producer_node_run_id == consensus_artifact.producer_node_run_id,
            WorkflowArtifact.data_type == "detection_disagreements",
        )
        .order_by(WorkflowArtifact.created_at.desc(), WorkflowArtifact.id.desc())
        .limit(1)
    )


def _auto_label_post_review(
    session: Session,
    *,
    project_id: str,
    artifacts: list[WorkflowArtifact],
    reviewed_by: str,
) -> dict[str, Any]:
    consensus_artifacts = [
        artifact for artifact in artifacts if artifact.data_type == "detection_consensus"
    ]
    if not consensus_artifacts:
        return {}

    materialized: list[dict[str, Any]] = []
    active_learning: list[dict[str, Any]] = []
    for consensus_artifact in consensus_artifacts:
        materialized.append(
            materialize_consensus_annotations(
                session,
                project_id=project_id,
                artifact=consensus_artifact,
                reviewed_by=reviewed_by,
            )
        )
        disagreement_artifact = _disagreement_artifact_for_consensus(
            session,
            consensus_artifact,
        )
        if disagreement_artifact is None:
            continue
        handoff = ensure_disagreement_active_learning_round(
            session,
            project_id=project_id,
            artifact=disagreement_artifact,
            created_by=reviewed_by,
        )
        if handoff is not None:
            active_learning.append(
                {
                    "source_artifact_id": disagreement_artifact.id,
                    **handoff,
                }
            )

    return {
        "consensus_materialization": materialized,
        "active_learning_handoff": active_learning,
    }


def pose_temporal_review_status(
    session: Session,
    artifact: WorkflowArtifact,
    *,
    project_id: str,
) -> dict[str, Any]:
    """Return fail-closed readiness for scientist approval of temporal pose state."""

    if artifact.data_type != "pose_temporal_tracks":
        raise ValidationError("Pose Review requires a pose_temporal_tracks artifact")

    payload = dict(artifact.payload_json or {})

    if payload.get("project_id") not in {None, project_id}:
        raise ValidationError("Pose Review received temporal tracks from another project")

    raw_track_ids = payload.get("track_ids")

    # A reviewed scientific cohort must not silently discard malformed or
    # repeated identifiers. Every stored temporal build is evidence for one
    # specific source track at the revision used to create its association.
    if (
        not isinstance(raw_track_ids, list)
        or any(type(track_id) is not str or not track_id for track_id in raw_track_ids)
        or len(raw_track_ids) != len(set(raw_track_ids))
    ):
        raise ValidationError("Pose Review artifact has invalid or duplicate track identifiers")

    track_ids = list(raw_track_ids)
    if not track_ids:
        raise ValidationError("Pose Review requires at least one temporal pose track")
    if type(payload.get("count")) is not int or payload["count"] != len(track_ids):
        raise ValidationError("Pose Review source track count does not match saved evidence")

    raw_builds = payload.get("builds")
    if not isinstance(raw_builds, list) or len(raw_builds) != len(track_ids):
        raise ValidationError("Pose Review requires one saved temporal build per track")

    expected_revisions: dict[str, int] = {}
    for raw in raw_builds:
        if not isinstance(raw, dict):
            raise ValidationError("Pose Review has invalid saved temporal build evidence")
        track_id = raw.get("parent_video_track_id")
        revision = raw.get("source_track_revision")
        if (
            type(track_id) is not str
            or track_id not in track_ids
            or track_id in expected_revisions
            or type(revision) is not int
            or revision < 1
        ):
            raise ValidationError("Pose Review has missing or ambiguous temporal build lineage")
        expected_revisions[track_id] = revision

    service = PoseTemporalTrackingService(session)

    stale_track_ids: list[str] = []
    missing_decision_observation_ids: list[str] = []
    unreviewed_unresolved_observation_ids: list[str] = []
    unreviewed_identity_break_decision_ids: list[str] = []
    unverified_identity_break_ids: list[str] = []
    current_track_revisions: dict[str, int] = {}
    qc_by_track: list[dict[str, Any]] = []

    for track_id in track_ids:
        track = session.get(VideoTrack, track_id)

        if track is None or track.deleted_at is not None:
            raise ValidationError("A Pose Review source track no longer exists")

        video = session.get(VideoAsset, track.video_id)

        if video is None or video.project_id != project_id:
            raise ValidationError("A Pose Review source track belongs to another project")

        current_track_revisions[track.id] = track.revision

        expected_revision = expected_revisions.get(track.id)

        if expected_revision is not None and track.revision != expected_revision:
            stale_track_ids.append(track.id)

        summary = service.summary(track.id)

        latest_decisions: dict[str, Any] = {}

        for decision in summary.association_decisions:
            current = latest_decisions.get(decision.observation_id)

            if current is None or decision.decision_revision > current.decision_revision:
                latest_decisions[decision.observation_id] = decision

        for observation in summary.observations:
            latest_decision = latest_decisions.get(observation.id)

            if latest_decision is None:
                missing_decision_observation_ids.append(observation.id)
                continue

            if (
                latest_decision.association_state == "unresolved"
                and latest_decision.verification_state == "unreviewed"
            ):
                unreviewed_unresolved_observation_ids.append(observation.id)

            if (
                latest_decision.association_state == "identity_break"
                and latest_decision.verification_state == "unreviewed"
            ):
                unreviewed_identity_break_decision_ids.append(latest_decision.id)

        for identity_break in summary.identity_breaks:
            if not identity_break.human_verified:
                unverified_identity_break_ids.append(identity_break.id)

        qc = service.qc(track.id)

        qc_by_track.append(
            {
                "track_id": track.id,
                "issue_count": qc.issue_count,
                "flagged_frame_count": (qc.flagged_frame_count),
                "unresolved_identity_count": (qc.unresolved_identity_count),
                "low_association_confidence_count": (qc.low_association_confidence_count),
                "low_landmark_confidence_count": (qc.low_landmark_confidence_count),
                "high_motion_cost_count": (qc.high_motion_cost_count),
                "uncertain_visibility_count": (qc.uncertain_visibility_count),
                "identity_break_count": (qc.identity_break_count),
            }
        )

    ready = not any(
        (
            stale_track_ids,
            missing_decision_observation_ids,
            unreviewed_unresolved_observation_ids,
            unreviewed_identity_break_decision_ids,
            unverified_identity_break_ids,
        )
    )

    return {
        "schema_version": "pose-workflow-review-readiness-0001",
        "ready": ready,
        "project_id": project_id,
        "source_artifact_id": artifact.id,
        "track_ids": track_ids,
        "track_count": len(track_ids),
        "current_track_revisions": (current_track_revisions),
        "stale_track_ids": sorted(stale_track_ids),
        "missing_decision_observation_ids": sorted(set(missing_decision_observation_ids)),
        "unreviewed_unresolved_observation_ids": sorted(set(unreviewed_unresolved_observation_ids)),
        "unreviewed_identity_break_decision_ids": sorted(
            set(unreviewed_identity_break_decision_ids)
        ),
        "unverified_identity_break_ids": sorted(set(unverified_identity_break_ids)),
        "qc_by_track": qc_by_track,
    }


def pose_active_learning_review_status(
    session: Session,
    artifact: WorkflowArtifact,
    *,
    project_id: str,
) -> dict[str, Any]:
    """Return retraining readiness for one workflow Active Learning round."""

    if artifact.data_type != "pose_active_learning_round":
        raise ValidationError(
            "Pose Active Learning Review requires a pose_active_learning_round artifact"
        )

    payload = dict(artifact.payload_json or {})

    if payload.get("project_id") not in (None, project_id):
        raise ValidationError("Pose Active Learning Review received a round from another project")

    round_id = payload.get("round_id")
    if type(round_id) is not str or not round_id:
        raise ValidationError("Pose Active Learning Review artifact is missing round_id")

    manifest = PoseActiveLearningService(session).export_manifest(round_id)

    if manifest.project_id != project_id:
        raise ValidationError("Pose Active Learning round belongs to another project")

    # The workflow's immutable round selection is separate from the mutable
    # scientist-review status. Do not approve a different round, video, or
    # candidate cohort merely because its current record is retraining-ready.
    if payload.get("video_id") != manifest.video_id:
        raise ValidationError("Pose Active Learning review video lineage does not match")
    if payload.get("selection_sha256") != manifest.selection_sha256:
        raise ValidationError("Pose Active Learning review selection lineage does not match")

    candidate_ids = payload.get("candidate_ids")
    expected_ids = [item["candidate_id"] for item in manifest.candidates]
    if (
        not isinstance(candidate_ids, list)
        or any(type(value) is not str or not value for value in candidate_ids)
        or len(candidate_ids) != len(set(candidate_ids))
        or len(candidate_ids) != len(expected_ids)
        or set(candidate_ids) != set(expected_ids)
    ):
        raise ValidationError("Pose Active Learning review candidate cohort does not match")

    if (
        type(payload.get("candidate_count")) is not int
        or payload["candidate_count"] != len(expected_ids)
        or type(payload.get("selected_count")) is not int
        or payload["selected_count"] != len(expected_ids)
    ):
        raise ValidationError("Pose Active Learning review candidate counts do not match")

    ready = manifest.status == "complete" and manifest.retraining_ready

    return {
        "schema_version": ("pose-active-learning-workflow-review-readiness-0001"),
        "ready": ready,
        "project_id": project_id,
        "source_artifact_id": artifact.id,
        "round_id": manifest.round_id,
        "video_id": manifest.video_id,
        "selection_sha256": manifest.selection_sha256,
        "selection_algorithm": (manifest.selection_algorithm),
        "selection_algorithm_version": (manifest.selection_algorithm_version),
        "round_status": manifest.status,
        "retraining_ready": (manifest.retraining_ready),
        "verified_candidate_count": (manifest.verified_candidate_count),
        "pending_candidate_count": (manifest.pending_candidate_count),
        "skipped_candidate_count": (manifest.skipped_candidate_count),
    }


def _begin_serialized_workflow_review(session: Session) -> None:
    """Claim SQLite's writer turn before reading any review or scientific state.

    Concurrent local approvals must not both observe a waiting review gate and
    materialize duplicate consensus annotations. Also recheck a cancellation
    or prediction update committed by another writer before approval.
    """
    connection = session.connection()
    if connection.dialect.name != "sqlite":
        return
    if getattr(connection.connection.driver_connection, "in_transaction", False):
        raise ConflictError(
            "Workflow approval requires a fresh transaction; reload before approving"
        )
    try:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    except OperationalError as exc:
        session.rollback()
        raw = exc.orig
        code = getattr(raw, "sqlite_errorcode", None)
        if (
            isinstance(raw, sqlite3.OperationalError)
            and isinstance(code, int)
            and (code & 0xFF) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
        ):
            raise ConflictError(
                "Workflow review database is busy; reload and retry approval"
            ) from exc
        raise


def resume_review_gate(
    session: Session,
    node_run_id: str,
    request: WorkflowReviewResumeRequest,
) -> WorkflowRunResponse:
    _begin_serialized_workflow_review(session)
    node_run = session.get(WorkflowNodeRun, node_run_id)
    if node_run is None:
        raise NotFoundError("Workflow review node was not found")
    if node_run.node_type not in REVIEW_GATE_NODE_TYPES:
        raise ValidationError("Only human-review workflow nodes can be resumed")
    if node_run.status != "waiting_for_review":
        raise ConflictError("Workflow node is not waiting for review")

    run = session.get(WorkflowRun, node_run.workflow_run_id)
    if run is None or run.job_id is None:
        raise NotFoundError("Workflow run or parent job was not found")
    job = session.get(Job, run.job_id)
    if job is None:
        raise NotFoundError("Workflow parent job was not found")
    if run.status != "waiting_for_review" or job.status != "waiting_for_review":
        raise ConflictError("Workflow run is not paused at this review node")

    artifacts = _input_artifacts(session, node_run, project_id=run.project_id)

    review_context: dict[str, Any] = {}

    if node_run.node_type == "pose_review_gate":
        if len(artifacts) != 1:
            raise ValidationError("Pose Review requires exactly one temporal-pose artifact")

        pose_status = pose_temporal_review_status(
            session,
            artifacts[0],
            project_id=run.project_id,
        )

        if not pose_status["ready"]:
            raise ValidationError(
                "Pose review cannot be approved while stale tracks, "
                "unreviewed unresolved identities, unverified identity "
                "breaks, or missing association decisions remain"
            )

        review_context["pose_review_status"] = pose_status

    elif node_run.node_type == "pose_active_learning_review_gate":
        if len(artifacts) != 1:
            raise ValidationError("Pose Active Learning Review requires exactly one round artifact")

        active_learning_status = pose_active_learning_review_status(
            session,
            artifacts[0],
            project_id=run.project_id,
        )

        if not active_learning_status["ready"]:
            raise ValidationError(
                "Pose Active Learning round is not retraining-ready. "
                "Finish or skip every candidate and verify at least one pose."
            )

        review_context["pose_active_learning_review_status"] = active_learning_status

    else:
        pending_count = _pending_review_count(
            session,
            artifacts,
            project_id=run.project_id,
        )

        if pending_count:
            raise ValidationError(f"{pending_count} model prediction(s) are still pending review")

    auto_label_result = (
        _auto_label_post_review(
            session,
            project_id=run.project_id,
            artifacts=artifacts,
            reviewed_by=request.reviewed_by,
        )
        if node_run.node_type == "detection_review_gate"
        else {}
    )

    now = _now()
    result = dict(node_run.result_json or {})
    result["review_approval"] = {
        "reviewed_by": request.reviewed_by,
        "note": request.note,
        "approved_at": now.isoformat(),
        "input_artifact_ids": [artifact.id for artifact in artifacts],
        **review_context,
        **auto_label_result,
    }
    node_run.result_json = result
    node_run.status = "review_approved"
    node_run.error_message = None
    node_run.completed_at = None

    succeeded_count = int(
        session.scalar(
            select(func.count(WorkflowNodeRun.id)).where(
                WorkflowNodeRun.workflow_run_id == run.id,
                WorkflowNodeRun.status == "succeeded",
            )
        )
        or 0
    )
    run.status = "queued"
    run.error_message = None
    run.completed_at = None
    run.result_json = {
        **dict(run.result_json or {}),
        "stage": "queued",
        "completed_nodes": succeeded_count,
        "resumed_from_review_node_id": node_run.id,
    }
    job.status = "queued"
    job.progress_current = succeeded_count
    job.error_message = None
    job.completed_at = None
    job.result_json = {
        **dict(job.result_json or {}),
        "stage": "queued",
        "completed_nodes": succeeded_count,
        "resumed_from_review_node_id": node_run.id,
    }
    session.commit()
    session.refresh(run)
    return WorkflowRunResponse.model_validate(run)
