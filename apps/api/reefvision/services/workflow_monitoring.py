"""Expose pinned Monitoring assessments in the standard typed workflow worker."""

from collections.abc import Mapping
from datetime import timedelta
from typing import Any, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator
from pydantic import ValidationError as InvalidParameters
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import WorkflowArtifact
from reefvision.db.models.workflow_schedule import WorkflowScheduleOccurrence
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.monitoring import (
    MAX_MONITORING_WINDOW_SECONDS,
    MonitoringAssessmentCreate,
    MonitoringDigest,
    MonitoringModel,
    MonitoringRuleRead,
    MonitoringWindow,
)
from reefvision.schemas.workflow_graphs import (
    WorkflowNodeDefinitionResponse,
    WorkflowPortDefinition,
)
from reefvision.services.monitoring import MonitoringService, verify_monitoring_rule
from reefvision.services.monitoring_evidence import monitoring_utc


class MonitoringWorkflowParameters(MonitoringModel):
    rule_id: UUID
    rule_sha256: MonitoringDigest
    window_start: AwareDatetime | None = None
    window_end: AwareDatetime | None = None
    window_seconds: int | None = Field(
        default=None, ge=1, le=MAX_MONITORING_WINDOW_SECONDS, strict=True
    )
    assessment_id: UUID | None = None
    assessment_sha256: MonitoringDigest | None = None

    @model_validator(mode="after")
    def separate_modes(self) -> Self:
        manual = self.window_start is not None and self.window_end is not None
        if (self.window_start is None) != (self.window_end is None):
            raise ValueError("Provide both fixed UTC window endpoints")
        readback = self.assessment_id is not None and self.assessment_sha256 is not None
        if (self.assessment_id is None) != (self.assessment_sha256 is None):
            raise ValueError("Provide both the saved assessment ID and result checksum")
        if sum((manual, self.window_seconds is not None, readback)) != 1:
            raise ValueError(
                "Choose a fixed UTC window, a scheduled lookback, or an immutable assessment"
            )
        if manual:
            MonitoringWindow.model_validate(
                {"window_start": self.window_start, "window_end": self.window_end},
            )
        return self


def _parameters(raw: Mapping[str, Any]) -> MonitoringWorkflowParameters:
    try:
        return MonitoringWorkflowParameters.model_validate(
            {
                name: value
                for name, value in raw.items()
                if name not in {"__workflow_run_id", "__workflow_node_run_id"}
            }
        )
    except InvalidParameters as exc:
        raise ValidationError(
            f"Invalid monitoring workflow parameters: {exc.errors()[0]['msg']}"
        ) from exc


def verify_scheduled_monitoring_rule(
    session: Session, project_id: str, parameters: Mapping[str, Any]
) -> MonitoringRuleRead:
    config = _parameters(parameters)
    if config.window_seconds is None:
        raise ValidationError("Scheduled monitoring requires a relative lookback in seconds")
    try:
        return verify_monitoring_rule(session, project_id, str(config.rule_id), config.rule_sha256)
    except (ConflictError, NotFoundError) as exc:
        raise ValidationError(str(exc)) from exc


def monitoring_assessment_node() -> WorkflowNodeDefinitionResponse:
    return WorkflowNodeDefinitionResponse(
        node_type="monitoring_assessment",
        display_name="Monitoring Assessment",
        category="Scientific analysis",
        description="Assess a pinned rule and propose alerts from immutable evidence.",
        input_ports=[
            WorkflowPortDefinition(
                port_id="project", display_name="Project", accepted_types=["project_reference"]
            )
        ],
        output_ports=[
            WorkflowPortDefinition(
                port_id="assessment",
                display_name="Monitoring assessment",
                accepted_types=["monitoring_assessment"],
                multiple=True,
            )
        ],
        required_parameters=["rule_id", "rule_sha256"],
        optional_parameters={
            "window_start": None,
            "window_end": None,
            "window_seconds": None,
            "assessment_id": None,
            "assessment_sha256": None,
        },
        execution_state="executable",
        executable=True,
        implementation_notes=[
            "Use a fixed UTC window, a scheduled lookback, or a saved assessment with its hash.",
            "Each assessment proposes alerts for explicit local review.",
        ],
    )


def execute_monitoring_assessment(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: Mapping[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    projects = inputs.get("project", [])
    if len(projects) != 1 or projects[0].payload_json.get("project_id") != project_id:
        raise ValidationError("Monitoring assessment requires the current project")
    config = _parameters(parameters)
    monitoring = MonitoringService(session, settings)
    if config.assessment_id is not None:
        # The result hash seals the original rule pin and window, even after the source changes.
        assessment = monitoring.get_assessment(project_id, str(config.assessment_id))
        if (
            assessment.rule_id != config.rule_id
            or assessment.result.rule_sha256 != config.rule_sha256
            or assessment.result_sha256 != config.assessment_sha256
        ):
            raise ConflictError("Saved monitoring assessment does not match its graph pins")
    else:
        start, end = config.window_start, config.window_end
        if config.window_seconds is not None:
            workflow_run_id = parameters.get("__workflow_run_id")
            occurrence = (
                session.scalar(
                    select(WorkflowScheduleOccurrence).where(
                        WorkflowScheduleOccurrence.project_id == project_id,
                        WorkflowScheduleOccurrence.workflow_run_id == workflow_run_id,
                    )
                )
                if workflow_run_id
                else None
            )
            if occurrence is None:
                raise ValidationError(
                    "A relative monitoring window requires a scheduled occurrence"
                )
            end = monitoring_utc(occurrence.scheduled_at)
            try:
                start = end - timedelta(seconds=config.window_seconds)
            except OverflowError as exc:
                raise ValidationError(
                    "The monitoring lookback falls outside the supported calendar"
                ) from exc
        assert start is not None and end is not None
        assessment = monitoring.create_assessment(
            project_id,
            MonitoringAssessmentCreate(
                rule_id=config.rule_id,
                rule_sha256=config.rule_sha256,
                window_start=start,
                window_end=end,
            ),
        )
    return [
        {
            "port_id": "assessment",
            "data_type": "monitoring_assessment",
            "payload": {
                "project_id": project_id,
                "assessment_id": str(assessment.id),
                "rule_id": str(assessment.rule_id),
                "rule_sha256": assessment.result.rule_sha256,
                "evidence_sha256": assessment.evidence_sha256,
                "result_sha256": assessment.result_sha256,
                "result": assessment.result.model_dump(mode="json"),
            },
        }
    ]
