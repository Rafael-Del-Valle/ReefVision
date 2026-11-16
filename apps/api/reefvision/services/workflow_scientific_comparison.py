"""Publish a saved scientific comparison to a typed workflow report."""

from typing import Any
from uuid import UUID

from pydantic import ValidationError as InvalidConfiguration
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job, WorkflowArtifact
from reefvision.domain.errors import ConflictError, ValidationError, WorkflowExecutionCancelled
from reefvision.jobs.static_comparison import process_static_comparison_job
from reefvision.schemas.scientific_comparison import ComparisonRecord, ComparisonRequest
from reefvision.schemas.static_comparison import StaticComparisonRecord, StaticComparisonRequest
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services.scientific_comparison import create_comparison, read_comparison
from reefvision.services.static_comparison import (
    STATIC_COMPARISON_JOB,
    read_static_comparison,
    submit_static_comparison,
)


def comparison_artifact(record: ComparisonRecord | StaticComparisonRecord) -> dict[str, str]:
    if isinstance(record, StaticComparisonRecord):
        return {
            "project_id": str(record.project_id),
            "comparison_id": str(record.id),
            "content_sha256": record.content_sha256,
            "method": record.snapshot.method,
            "data_kind": record.snapshot.evaluation_status,
            "export_path": f"/projects/{record.project_id}/static-comparisons/{record.id}/export",
        }
    return {
        "project_id": str(record.project_id),
        "comparison_id": str(record.id),
        "content_sha256": record.content_sha256,
        "method": record.snapshot.method,
        "data_kind": record.snapshot.data_kind,
        "export_path": f"/projects/{record.project_id}/scientific-comparisons/{record.id}/export",
    }


def _calculate_static(
    session: Session,
    settings: Settings,
    project_id: str,
    configuration: StaticComparisonRequest,
    workflow_run_id: str | None,
    workflow_node_run_id: str | None,
) -> StaticComparisonRecord:
    existing = None
    if workflow_node_run_id:
        existing = session.scalar(
            select(Job)
            .where(
                Job.project_id == project_id,
                Job.job_type == STATIC_COMPARISON_JOB,
                Job.status.in_(("queued", "succeeded")),
                Job.request_json["workflow_node_run_id"].as_string() == workflow_node_run_id,
            )
            .order_by(Job.created_at.desc(), Job.id)
            .limit(1)
        )
    identifier = (
        existing.id
        if existing
        else submit_static_comparison(
            session,
            settings,
            project_id,
            configuration,
            workflow_run_id=workflow_run_id,
            workflow_node_run_id=workflow_node_run_id,
        ).id
    )
    if existing is None or existing.status == "queued":
        session.commit()
        process_static_comparison_job(
            settings,
            sessionmaker(bind=session.get_bind(), expire_on_commit=False),
            identifier,
        )
        session.expire_all()
    child = session.get(Job, identifier)
    if child is not None and child.status in {"cancel_requested", "cancelled"}:
        raise WorkflowExecutionCancelled("Static comparison was cancelled")
    if child is None or child.status != "succeeded":
        raise ValidationError(
            child.error_message
            if child and child.error_message
            else "Static comparison did not complete"
        )
    return read_static_comparison(session, project_id, identifier, settings)


def execute(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    if set(parameters) - {
        "comparison_id",
        "configuration",
        "static_comparison_id",
        "static_configuration",
        "__workflow_run_id",
        "__workflow_node_run_id",
    }:
        raise ValidationError("Unsupported scientific comparison parameters")
    projects = inputs.get("project", [])
    if len(projects) != 1 or projects[0].payload_json.get("project_id") != project_id:
        raise ValidationError("Scientific comparison requires the current project")
    identifier = parameters.get("comparison_id")
    configuration = parameters.get("configuration")
    static_identifier = parameters.get("static_comparison_id")
    static_configuration = parameters.get("static_configuration")
    if sum(map(bool, (identifier, configuration, static_identifier, static_configuration))) != 1:
        raise ValidationError("Provide exactly one saved comparison ID or comparison configuration")
    report: ComparisonRecord | StaticComparisonRecord
    try:
        if static_identifier:
            report = read_static_comparison(
                session,
                project_id,
                str(UUID(str(static_identifier))),
                settings,
            )
        elif static_configuration:
            report = _calculate_static(
                session,
                settings,
                project_id,
                StaticComparisonRequest.model_validate(static_configuration),
                parameters.get("__workflow_run_id"),
                parameters.get("__workflow_node_run_id"),
            )
        elif identifier:
            report = read_comparison(session, project_id, str(UUID(str(identifier))))
        else:
            report = create_comparison(
                session, project_id, ComparisonRequest.model_validate(configuration)
            )
    except InvalidConfiguration as exc:
        raise ValidationError(f"Invalid comparison configuration: {exc}") from exc
    except ValueError as exc:
        raise ValidationError("Choose a saved comparison UUID") from exc
    if report.stale:
        raise ConflictError("Source evidence changed; save a fresh comparison")
    return [
        {
            "port_id": "report",
            "data_type": "scientific_comparison_report",
            "payload": comparison_artifact(report),
        }
    ]


def register_scientific_comparison_nodes() -> dict[str, WorkflowNodeDefinitionResponse]:
    from reefvision.services import workflow_runtime_adapters as runtime

    node_type = "scientific_comparison"
    runtime.RUNTIME_ADAPTER_NODE_TYPES.add(node_type)
    runtime._ADAPTERS[node_type] = execute
    return {
        node_type: WorkflowNodeDefinitionResponse(
            node_type=node_type,
            display_name="Publish Scientific Comparison",
            category="Scientific analysis",
            description="Compare detectors against reviewed static-image counts or replay "
            "a saved scientific comparison.",
            input_ports=[
                WorkflowPortDefinition(
                    port_id="project", display_name="Project", accepted_types=["project_reference"]
                )
            ],
            output_ports=[
                WorkflowPortDefinition(
                    port_id="report",
                    display_name="Scientific comparison",
                    accepted_types=["scientific_comparison_report"],
                )
            ],
            required_parameters=[],
            optional_parameters={
                "comparison_id": "",
                "configuration": {},
                "static_comparison_id": "",
                "static_configuration": {},
            },
            execution_state="executable",
            executable=True,
            implementation_notes=[
                "Choose a saved comparison or configure a new calculation.",
                "Reuses the same immutable analysis and checks source evidence on replay.",
            ],
        )
    }
