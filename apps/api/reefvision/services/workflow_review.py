"""Human-review pause and resume semantics for persistent workflow runs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
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
from reefvision.services.workflow_provenance import (
    verify_workflow_artifact,
    verify_workflow_run_node_graph_lineage,
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


def _input_artifacts(session: Session, node_run: WorkflowNodeRun) -> list[WorkflowArtifact]:
    raw_ids = node_run.input_artifact_ids_json
    if raw_ids is None:
        raw_ids = []
    if not isinstance(raw_ids, list) or any(
        not isinstance(value, str) or not value for value in raw_ids
    ):
        raise ConflictError("Workflow review input artifact IDs are invalid")
    # Even an empty saved list must be checked against frozen graph edges;
    # otherwise a paused review can be approved without scientific evidence.
    artifacts = list(
        session.scalars(select(WorkflowArtifact).where(WorkflowArtifact.id.in_(raw_ids)))
    )
    by_id = {artifact.id: artifact for artifact in artifacts}
    if len(by_id) != len(set(raw_ids)):
        raise ConflictError("Workflow review input artifact is missing")
    # A review approval must refer to the outputs that the frozen workflow
    # actually routed into this review node. Valid artifact hashes alone do
    # not prevent a different same-run artifact from being approved instead.
    run = session.get(WorkflowRun, node_run.workflow_run_id)
    graph = (
        session.get(WorkflowGraphRecord, run.workflow_graph_record_id) if run is not None else None
    )
    if (
        run is None
        or graph is None
        or graph.project_id != run.project_id
        or not isinstance(graph.graph_json, dict)
        or graph.graph_sha256 != run.graph_sha256
        or canonical_json_sha256(graph.graph_json) != run.graph_sha256
    ):
        raise ConflictError("Workflow review graph provenance checksum failed")
    # Paused runs are mutable database records, while approval is a scientific
    # audit event. Recheck the complete node identity, frozen parameters, and
    # execution order before recording review approval or post-review outputs.
    saved_nodes = list(
        session.scalars(select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run.id))
    )
    verify_workflow_run_node_graph_lineage(graph, saved_nodes)
    raw_edges = graph.graph_json.get("edges")
    if not isinstance(raw_edges, list) or any(
        not isinstance(edge, dict) or not isinstance(edge.get("edge_id"), str) for edge in raw_edges
    ):
        raise ConflictError("Workflow review graph edges are invalid")
    expected_bindings = [
        (edge.get("source_node_id"), edge.get("source_port_id"))
        for edge in sorted(raw_edges, key=lambda edge: edge["edge_id"])
        if edge.get("target_node_id") == node_run.node_id
    ]
    ordered_artifacts = [by_id[artifact_id] for artifact_id in raw_ids]
    actual_bindings: list[tuple[str, str]] = []
    for artifact in ordered_artifacts:
        verify_workflow_artifact(artifact, expected_run_id=node_run.workflow_run_id)
        producer = session.get(WorkflowNodeRun, artifact.producer_node_run_id)
        if (
            producer is None
            or producer.workflow_run_id != node_run.workflow_run_id
            or producer.status != "succeeded"
            or producer.execution_order >= node_run.execution_order
        ):
            raise ConflictError("Workflow review input lacks an earlier succeeded producer")
        # A hash-valid replacement from the same producer/port is not review
        # evidence unless it was declared by that completed node. Reject
        # ambiguous duplicate outputs rather than approving one arbitrarily.
        declared_output_ids = producer.output_artifact_ids_json
        if not isinstance(declared_output_ids, list) or artifact.id not in declared_output_ids:
            raise ConflictError("Workflow review input is not a declared producer output")
        producer_port_count = session.scalar(
            select(func.count(WorkflowArtifact.id)).where(
                WorkflowArtifact.workflow_run_id == node_run.workflow_run_id,
                WorkflowArtifact.producer_node_run_id == producer.id,
                WorkflowArtifact.producer_port_id == artifact.producer_port_id,
            )
        )
        if producer_port_count != 1:
            raise ConflictError("Workflow review producer output is ambiguous")
        actual_bindings.append((producer.node_id, artifact.producer_port_id))
    if actual_bindings != expected_bindings:
        raise ConflictError("Workflow review inputs do not match saved graph edges")
    return ordered_artifacts


def _pending_review_count(session: Session, artifacts: list[WorkflowArtifact]) -> int:
    proposal_ids: set[str] = set()
    classification_ids: set[str] = set()
    for artifact in artifacts:
        payload = dict(artifact.payload_json or {})
        if artifact.data_type in {"detection_proposals", "mask_proposals"}:
            proposal_ids.update(str(value) for value in payload.get("proposal_ids", []))
        elif artifact.data_type == "classification_predictions":
            classification_ids.update(str(value) for value in payload.get("prediction_ids", []))

    pending = 0
    if proposal_ids:
        pending += int(
            session.scalar(
                select(func.count(PredictionProposal.id)).where(
                    PredictionProposal.id.in_(proposal_ids),
                    PredictionProposal.review_status == "pending",
                )
            )
            or 0
        )
    if classification_ids:
        pending += int(
            session.scalar(
                select(func.count(ClassificationPrediction.id)).where(
                    ClassificationPrediction.id.in_(classification_ids),
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
    producer = session.get(WorkflowNodeRun, consensus_artifact.producer_node_run_id)
    if (
        producer is None
        or producer.workflow_run_id != consensus_artifact.workflow_run_id
        or not isinstance(producer.output_artifact_ids_json, list)
        or any(
            not isinstance(artifact_id, str) or not artifact_id
            for artifact_id in producer.output_artifact_ids_json
        )
    ):
        raise ConflictError("Workflow consensus producer outputs are invalid")
    declared_ids = producer.output_artifact_ids_json
    declared_outputs = list(
        session.scalars(select(WorkflowArtifact).where(WorkflowArtifact.id.in_(declared_ids)))
    )
    # An absent disagreement row must not silently suppress a scientist's
    # active-learning handoff when it is still listed in the producer manifest.
    if len(declared_outputs) != len(declared_ids) or any(
        artifact.workflow_run_id != consensus_artifact.workflow_run_id
        or artifact.producer_node_run_id != producer.id
        for artifact in declared_outputs
    ):
        raise ConflictError(
            "Workflow consensus declared producer output is missing or inconsistent"
        )

    disagreements = list(
        session.scalars(
            select(WorkflowArtifact).where(
                WorkflowArtifact.workflow_run_id == consensus_artifact.workflow_run_id,
                WorkflowArtifact.producer_node_run_id == consensus_artifact.producer_node_run_id,
                WorkflowArtifact.data_type == "detection_disagreements",
            )
        )
    )
    if not disagreements:
        return None
    # Never choose the newest of multiple checksum-valid outputs: that would
    # allow an undeclared artifact to change the scientist's AL handoff.
    if len(disagreements) != 1:
        raise ConflictError("Workflow consensus disagreement outputs are ambiguous")

    disagreement = disagreements[0]
    if disagreement.id not in declared_ids or disagreement.producer_port_id != "disagreements":
        raise ConflictError("Workflow disagreement is not a declared producer output")
    verify_workflow_artifact(
        disagreement,
        expected_run_id=consensus_artifact.workflow_run_id,
    )
    return disagreement


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

    raw_track_ids = payload.get("track_ids", [])

    if not isinstance(raw_track_ids, list) or any(
        not isinstance(value, str) or not value for value in raw_track_ids
    ):
        raise ValidationError("Pose Review artifact track_ids are invalid")
    if len(set(raw_track_ids)) != len(raw_track_ids):
        raise ValidationError("Pose Review artifact track_ids contain duplicates")

    track_ids = raw_track_ids

    if not track_ids:
        raise ValidationError("Pose Review requires at least one temporal pose track")

    expected_revisions: dict[str, int] = {}

    # A missing or malformed build revision must not silently bypass the
    # stale-track check when a scientist approves persisted temporal evidence.
    raw_builds = payload.get("builds")
    if not isinstance(raw_builds, list):
        raise ValidationError("Pose Review source track revisions are missing")
    for raw in raw_builds:
        if not isinstance(raw, dict):
            raise ValidationError("Pose Review source track revisions are invalid")

        track_id = raw.get("parent_video_track_id")
        revision = raw.get("source_track_revision")
        if (
            not isinstance(track_id, str)
            or track_id not in track_ids
            or track_id in expected_revisions
            or not isinstance(revision, int)
            or isinstance(revision, bool)
            or revision < 1
        ):
            raise ValidationError("Pose Review source track revisions are invalid")
        expected_revisions[track_id] = revision

    if set(expected_revisions) != set(track_ids):
        raise ValidationError("Pose Review requires a revision for every source track")

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

    if payload.get("project_id") not in {None, project_id}:
        raise ValidationError("Pose Active Learning Review received a round from another project")

    round_id = str(payload.get("round_id") or "")

    if not round_id:
        raise ValidationError("Pose Active Learning Review artifact is missing round_id")

    manifest = PoseActiveLearningService(session).export_manifest(round_id)

    if manifest.project_id != project_id:
        raise ValidationError("Pose Active Learning round belongs to another project")

    if payload.get("selection_sha256") != manifest.selection_sha256:
        raise ValidationError(
            "Pose Active Learning Review selection differs from saved workflow evidence"
        )

    candidate_ids = payload.get("candidate_ids")
    if (
        not isinstance(candidate_ids, list)
        or any(not isinstance(value, str) or not value for value in candidate_ids)
        or len(candidate_ids) != len(set(candidate_ids))
        or set(candidate_ids) != {candidate["candidate_id"] for candidate in manifest.candidates}
        or payload.get("candidate_count") != len(candidate_ids)
    ):
        raise ValidationError(
            "Pose Active Learning Review candidates differ from saved workflow evidence"
        )

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


def resume_review_gate(
    session: Session,
    node_run_id: str,
    request: WorkflowReviewResumeRequest,
) -> WorkflowRunResponse:
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

    artifacts = _input_artifacts(session, node_run)

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
