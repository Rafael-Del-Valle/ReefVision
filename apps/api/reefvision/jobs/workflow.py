"""Background execution for persistent typed workflow graphs."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    Job,
    WorkflowArtifact,
    WorkflowGraphRecord,
    WorkflowNodeRun,
    WorkflowRun,
)
from reefvision.schemas.workflow_graphs import WorkflowGraphRequest, WorkflowPlanInputBinding
from reefvision.services.workflow_execution import WorkflowExecutionService
from reefvision.services.workflow_graphs import WorkflowGraphService
from reefvision.services.workflow_provenance import (
    build_workflow_run_provenance,
    verify_succeeded_node_artifacts,
    verify_workflow_artifact,
)
from reefvision.services.workflow_review import WorkflowReviewRequired
from reefvision.storage.datasets import canonical_json_sha256


def _now() -> datetime:
    return datetime.now(UTC)


def _set_terminal(
    factory: sessionmaker[Session],
    job_id: str,
    run_id: str,
    *,
    status: str,
    error: str | None = None,
) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        run = session.get(WorkflowRun, run_id)
        if job is not None:
            job.status = status
            job.error_message = error
            job.completed_at = _now()
            result = dict(job.result_json or {})
            result["stage"] = status
            job.result_json = result
        if run is not None:
            run.status = status
            run.error_message = error
            run.completed_at = _now()
            result = dict(run.result_json or {})
            result["stage"] = status
            run.result_json = result
        session.commit()


def _set_waiting_for_review(
    factory: sessionmaker[Session],
    job_id: str,
    run_id: str,
    *,
    completed_nodes: int,
    review: WorkflowReviewRequired,
) -> None:
    with factory() as session:
        details = dict(review.details)
        requested_node_id = str(details.get("node_run_id") or "")
        node_run = session.get(WorkflowNodeRun, requested_node_id) if requested_node_id else None
        if node_run is None:
            node_run = session.scalar(
                select(WorkflowNodeRun)
                .where(
                    WorkflowNodeRun.workflow_run_id == run_id,
                    WorkflowNodeRun.status == "running",
                )
                .order_by(WorkflowNodeRun.execution_order)
            )
        if node_run is None:
            raise RuntimeError("Workflow review pause could not resolve the active review node")

        node_run.status = "waiting_for_review"
        node_run.error_message = None
        node_run.completed_at = None
        node_run.result_json = {
            **dict(node_run.result_json or {}),
            "review": {
                "message": str(review),
                **details,
            },
        }

        job = session.get(Job, job_id)
        run = session.get(WorkflowRun, run_id)
        if job is not None:
            job.status = "waiting_for_review"
            job.progress_current = completed_nodes
            job.error_message = None
            job.completed_at = None
            job.result_json = {
                **dict(job.result_json or {}),
                "stage": "waiting_for_review",
                "workflow_run_id": run_id,
                "completed_nodes": completed_nodes,
                "review_node_run_id": node_run.id,
                "review_node_id": node_run.node_id,
            }
        if run is not None:
            run.status = "waiting_for_review"
            run.error_message = None
            run.completed_at = None
            run.result_json = {
                **dict(run.result_json or {}),
                "stage": "waiting_for_review",
                "completed_nodes": completed_nodes,
                "review_node_run_id": node_run.id,
                "review_node_id": node_run.node_id,
            }
        session.commit()


def _cancel_requested(factory: sessionmaker[Session], job_id: str) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        return job is None or job.status == "cancel_requested"


def _cancel_remaining_nodes(factory: sessionmaker[Session], run_id: str) -> None:
    with factory() as session:
        nodes = list(
            session.scalars(
                select(WorkflowNodeRun).where(
                    WorkflowNodeRun.workflow_run_id == run_id,
                    WorkflowNodeRun.status.in_(("pending", "running", "waiting_for_review")),
                )
            )
        )
        now = _now()
        for node in nodes:
            node.status = "cancelled"
            node.completed_at = now
            node.error_message = "Workflow run was cancelled"
        session.commit()


def _input_artifacts(
    session: Session,
    *,
    run_id: str,
    step_node_id: str,
    bindings: list[WorkflowPlanInputBinding],
) -> tuple[dict[str, list[WorkflowArtifact]], list[str]]:
    inputs: dict[str, list[WorkflowArtifact]] = {}
    artifact_ids: list[str] = []
    for binding in bindings:
        target_port_id = str(binding.target_port_id)
        source_node_id = str(binding.source_node_id)
        source_port_id = str(binding.source_port_id)
        expected_type = str(binding.data_type)
        producer = session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_id == source_node_id,
            )
        )
        if producer is None or producer.status != "succeeded":
            raise RuntimeError(f"Node {step_node_id} requires unfinished producer {source_node_id}")
        artifact = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.workflow_run_id == run_id,
                WorkflowArtifact.producer_node_run_id == producer.id,
                WorkflowArtifact.producer_port_id == source_port_id,
                WorkflowArtifact.data_type == expected_type,
            )
        )
        if artifact is None:
            raise RuntimeError(
                f"Node {step_node_id} is missing artifact {source_node_id}.{source_port_id}"
            )

        verify_workflow_artifact(
            artifact,
            expected_run_id=run_id,
        )

        inputs.setdefault(
            target_port_id,
            [],
        ).append(artifact)
        artifact_ids.append(artifact.id)
    return inputs, artifact_ids


def process_workflow_run_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None or job.job_type != "workflow_run" or job.status != "queued":
            return False
        run_id = str((job.request_json or {}).get("workflow_run_id") or "")
        run = session.get(WorkflowRun, run_id)
        if run is None or run.job_id != job.id:
            job.status = "failed"
            job.error_message = "Workflow run record is missing or mismatched"
            job.completed_at = _now()
            session.commit()
            return False
        # A queued job and its run must remain in the same project. A stale
        # or corrupted job ownership field must not execute another project's
        # saved scientific workflow under the wrong job identity.
        if job.project_id != run.project_id:
            job.status = "failed"
            job.error_message = "Workflow job project ownership no longer matches run"
            job.completed_at = _now()
            run.status = "failed"
            run.error_message = job.error_message
            run.completed_at = job.completed_at
            session.commit()
            return False
        # A stale queued job must not reopen completed, failed, or cancelled
        # scientific work. Preserve the terminal run and its frozen artifacts.
        if run.status in {"succeeded", "failed", "cancelled"}:
            job.status = "failed"
            job.error_message = "Workflow run is already terminal; refusing queued job replay"
            job.completed_at = _now()
            session.commit()
            return False
        graph_record = session.get(WorkflowGraphRecord, run.workflow_graph_record_id)
        if graph_record is None:
            job.status = "failed"
            job.error_message = "Workflow graph revision is missing"
            job.completed_at = _now()
            run.status = "failed"
            run.error_message = job.error_message
            run.completed_at = job.completed_at
            session.commit()
            return False
        # A persisted graph can become malformed after queueing (for example,
        # through an interrupted migration). Fail the queued job explicitly
        # instead of leaving it queued after an uncaught Pydantic exception.
        try:
            graph = WorkflowGraphRequest.model_validate(graph_record.graph_json)
        except PydanticValidationError:
            job.status = "failed"
            job.error_message = "Saved workflow graph revision is invalid"
            job.completed_at = _now()
            run.status = "failed"
            run.error_message = job.error_message
            run.completed_at = job.completed_at
            session.commit()
            return False
        if canonical_json_sha256(graph.model_dump(mode="json")) != run.graph_sha256:
            job.status = "failed"
            job.error_message = "Workflow graph checksum no longer matches the queued run"
            job.completed_at = _now()
            run.status = "failed"
            run.error_message = job.error_message
            run.completed_at = job.completed_at
            session.commit()
            return False
        # A parseable graph can still lose its saved revision or project lineage
        # after queueing. Verify the raw stored JSON as well as the pinned run
        # digest: Pydantic may discard unknown keys during model validation.
        if (
            graph_record.project_id != run.project_id
            or graph_record.graph_key != graph.graph_id
            or graph_record.schema_version != graph.schema_version
            or graph_record.graph_sha256 != run.graph_sha256
            or canonical_json_sha256(graph_record.graph_json) != graph_record.graph_sha256
        ):
            job.status = "failed"
            job.error_message = "Workflow graph provenance checksum failed"
            job.completed_at = _now()
            run.status = "failed"
            run.error_message = job.error_message
            run.completed_at = job.completed_at
            session.commit()
            return False
        plan = WorkflowGraphService(session).plan(run.project_id, graph)
        if not plan.valid:
            job.status = "failed"
            first_error = next((issue for issue in plan.issues if issue.severity == "error"), None)
            job.error_message = (
                "Workflow graph no longer validates"
                if first_error is None
                else (
                    f"Workflow graph no longer validates ({first_error.code}): "
                    f"{first_error.message}"
                )
            )
            job.completed_at = _now()
            run.status = "failed"
            run.error_message = job.error_message
            run.completed_at = job.completed_at
            session.commit()
            return False
        now = _now()
        job.status = "running"
        job.started_at = job.started_at or now
        job.error_message = None
        job.result_json = {"stage": "running", "workflow_run_id": run.id}
        run.status = "running"
        run.started_at = run.started_at or now
        run.error_message = None
        run.result_json = {
            **dict(run.result_json or {}),
            "stage": "running",
        }
        for node in session.scalars(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run.id,
                WorkflowNodeRun.status == "running",
            )
        ):
            node.status = "pending"
            node.started_at = None
            node.error_message = "Recovered after interrupted workflow execution"
        session.commit()
        project_id = run.project_id

    completed_nodes = 0
    try:
        for step in plan.steps:
            if _cancel_requested(factory, job_id):
                _cancel_remaining_nodes(factory, run_id)
                _set_terminal(
                    factory,
                    job_id,
                    run_id,
                    status="cancelled",
                    error=None,
                )
                return False

            with factory() as session:
                node_run = session.scalar(
                    select(WorkflowNodeRun).where(
                        WorkflowNodeRun.workflow_run_id == run_id,
                        WorkflowNodeRun.node_id == step.node_id,
                    )
                )
                if node_run is None:
                    raise RuntimeError(f"Workflow node-run record is missing: {step.node_id}")
                if node_run.status == "succeeded":
                    try:
                        verify_succeeded_node_artifacts(
                            session,
                            run_id=run_id,
                            node_run=node_run,
                        )
                    except Exception as exc:
                        node_run.error_message = (
                            f"Persisted succeeded-node artifact integrity check failed: {exc}"
                        )
                        session.commit()
                        raise

                    completed_nodes += 1
                    continue
                inputs, input_artifact_ids = _input_artifacts(
                    session,
                    run_id=run_id,
                    step_node_id=step.node_id,
                    bindings=list(step.input_bindings),
                )
                node_run.status = "running"
                node_run.started_at = node_run.started_at or _now()
                node_run.completed_at = None
                node_run.error_message = None
                node_run.parameters_json = dict(step.parameters)
                node_run.input_artifact_ids_json = input_artifact_ids
                session.commit()

            with factory() as session:
                node_run = session.scalar(
                    select(WorkflowNodeRun).where(
                        WorkflowNodeRun.workflow_run_id == run_id,
                        WorkflowNodeRun.node_id == step.node_id,
                    )
                )
                if node_run is None:
                    raise RuntimeError(f"Workflow node-run record disappeared: {step.node_id}")
                inputs, _ = _input_artifacts(
                    session,
                    run_id=run_id,
                    step_node_id=step.node_id,
                    bindings=list(step.input_bindings),
                )
                service = WorkflowExecutionService(session, settings)
                specifications = service.execute_node(
                    project_id=project_id,
                    run_id=run_id,
                    node_run=node_run,
                    step=step,
                    inputs=inputs,
                )
                output_ids: list[str] = []
                output_summary: list[dict[str, object]] = []
                for specification in specifications:
                    artifact = service.persist_artifact(
                        run_id=run_id,
                        node_run=node_run,
                        specification=specification,
                    )
                    output_ids.append(artifact.id)
                    output_summary.append(
                        {
                            "artifact_id": artifact.id,
                            "port_id": specification.port_id,
                            "data_type": specification.data_type,
                            "payload_sha256": artifact.payload_sha256,
                        }
                    )
                node_run.status = "succeeded"
                node_run.output_artifact_ids_json = output_ids
                node_run.result_json = {
                    **dict(node_run.result_json or {}),
                    "outputs": output_summary,
                }
                node_run.completed_at = _now()
                session.commit()

            completed_nodes += 1
            with factory() as session:
                job = session.get(Job, job_id)
                run = session.get(WorkflowRun, run_id)
                if job is not None:
                    job.progress_current = completed_nodes
                    job.result_json = {
                        **dict(job.result_json or {}),
                        "stage": "running",
                        "workflow_run_id": run_id,
                        "completed_nodes": completed_nodes,
                    }
                if run is not None:
                    run.result_json = {
                        **dict(run.result_json or {}),
                        "stage": "running",
                        "completed_nodes": completed_nodes,
                    }
                session.commit()

        with factory() as session:
            service = WorkflowExecutionService(session, settings)
            counts = service.run_counts(run_id)
            artifacts = list(
                session.scalars(
                    select(WorkflowArtifact)
                    .where(WorkflowArtifact.workflow_run_id == run_id)
                    .order_by(WorkflowArtifact.created_at, WorkflowArtifact.id)
                )
            )
            terminal_artifacts = [
                {
                    "artifact_id": artifact.id,
                    "data_type": artifact.data_type,
                    "payload_sha256": artifact.payload_sha256,
                }
                for artifact in artifacts
            ]
            run = session.get(
                WorkflowRun,
                run_id,
            )
            job = session.get(
                Job,
                job_id,
            )
            now = _now()

            if run is None:
                raise RuntimeError("Workflow run disappeared during terminal provenance closeout")

            previous_run_result = dict(run.result_json or {})

            run.status = "succeeded"
            run.completed_at = now

            if job is not None:
                job.status = "succeeded"
                job.progress_current = completed_nodes
                job.completed_at = now

            session.flush()

            provenance = build_workflow_run_provenance(
                session,
                run_id=run_id,
            )

            provenance_sha256 = canonical_json_sha256(provenance)

            run.result_json = {
                **previous_run_result,
                "stage": "succeeded",
                "completed_nodes": (completed_nodes),
                **counts,
                "artifacts": (terminal_artifacts),
                "provenance_schema_version": (provenance["schema_version"]),
                "provenance_sha256": (provenance_sha256),
                "provenance_manifest": (provenance),
            }

            if job is not None:
                previous_job_result = dict(job.result_json or {})

                job.result_json = {
                    **previous_job_result,
                    "stage": "succeeded",
                    "workflow_run_id": (run_id),
                    "completed_nodes": (completed_nodes),
                    **counts,
                    "provenance_sha256": (provenance_sha256),
                }

            session.commit()
        return True
    except WorkflowReviewRequired as exc:
        _set_waiting_for_review(
            factory,
            job_id,
            run_id,
            completed_nodes=completed_nodes,
            review=exc,
        )
        return True
    except Exception as exc:
        with factory() as session:
            failed_node = session.scalar(
                select(WorkflowNodeRun)
                .where(
                    WorkflowNodeRun.workflow_run_id == run_id,
                    WorkflowNodeRun.status == "running",
                )
                .order_by(WorkflowNodeRun.execution_order)
            )
            if failed_node is not None:
                failed_node.status = "failed"
                failed_node.error_message = str(exc)
                failed_node.completed_at = _now()
            session.commit()
        _set_terminal(factory, job_id, run_id, status="failed", error=str(exc))
        return False
