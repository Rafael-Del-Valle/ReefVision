"""Typed workflow graph validation, persistence, and execution schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reefvision.schemas.jobs import JobResponse

WorkflowNodeType = Literal[
    "image_input",
    "video_input",
    "depth_estimation",
    "embedding_generation",
    "detector",
    "segmenter",
    "classifier",
    "tracker",
    "measurement",
    "behavior_analysis",
    "active_learning",
    "filter",
    "export",
]
WorkflowIssueSeverity = Literal["error", "warning"]
WorkflowStatus = Literal["draft", "published", "archived"]
WorkflowRunStatus = Literal[
    "queued",
    "running",
    "cancel_requested",
    "cancelled",
    "succeeded",
    "failed",
]


class WorkflowNode(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    node_type: WorkflowNodeType
    label: str | None = Field(default=None, max_length=200)
    configuration: dict[str, object] = Field(default_factory=dict)


class WorkflowEdge(BaseModel):
    source_node_id: str = Field(min_length=1, max_length=100)
    source_port: str = Field(min_length=1, max_length=100)
    target_node_id: str = Field(min_length=1, max_length=100)
    target_port: str = Field(min_length=1, max_length=100)


class WorkflowValidationRequest(BaseModel):
    name: str = Field(default="Untitled workflow", min_length=1, max_length=200)
    nodes: list[WorkflowNode] = Field(min_length=1, max_length=1000)
    edges: list[WorkflowEdge] = Field(default_factory=list, max_length=10_000)

    @model_validator(mode="after")
    def unique_node_ids(self) -> WorkflowValidationRequest:
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Workflow node IDs must be unique")
        return self


class WorkflowValidationIssue(BaseModel):
    severity: WorkflowIssueSeverity
    code: str
    message: str
    node_id: str | None = None
    edge_index: int | None = Field(default=None, ge=0)


class WorkflowExecutionStage(BaseModel):
    stage_index: int = Field(ge=0)
    node_ids: list[str]


class WorkflowPortDefinition(BaseModel):
    name: str
    data_type: str
    required: bool = True


class WorkflowNodeDefinition(BaseModel):
    node_type: WorkflowNodeType
    display_name: str
    inputs: list[WorkflowPortDefinition]
    outputs: list[WorkflowPortDefinition]
    requires_model: bool
    supported_model_tasks: list[str]


class WorkflowValidationResponse(BaseModel):
    project_id: str
    name: str
    valid: bool
    workflow_checksum: str
    topological_order: list[str]
    execution_stages: list[WorkflowExecutionStage]
    issues: list[WorkflowValidationIssue]


class WorkflowTemplate(BaseModel):
    template_id: str
    name: str
    description: str
    workflow: WorkflowValidationRequest


class WorkflowCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    workflow: WorkflowValidationRequest
    status: WorkflowStatus = "draft"
    creator: str = Field(default="local_user", min_length=1, max_length=100)


class WorkflowRevisionCreateRequest(BaseModel):
    workflow: WorkflowValidationRequest
    creator: str = Field(default="local_user", min_length=1, max_length=100)


class WorkflowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    name: str
    description: str | None
    status: WorkflowStatus
    current_revision_number: int
    created_by: str
    created_at: datetime
    updated_at: datetime


class WorkflowRevisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_id: str
    revision_number: int
    workflow_json: dict[str, Any]
    workflow_checksum: str
    validation_json: dict[str, Any]
    created_by: str
    created_at: datetime


class WorkflowDetailResponse(BaseModel):
    workflow: WorkflowResponse
    current_revision: WorkflowRevisionResponse
    validation: WorkflowValidationResponse


class WorkflowRunCreateRequest(BaseModel):
    workflow_revision_id: str | None = Field(default=None, max_length=36)
    inputs: dict[str, Any] = Field(default_factory=dict)
    use_cache: bool = True


class WorkflowArtifactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_run_id: str
    node_id: str
    port_name: str
    artifact_type: str
    checksum: str
    payload_json: dict[str, Any]
    managed_path: str | None
    size_bytes: int | None
    created_at: datetime


class WorkflowRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_id: str
    workflow_revision_id: str
    project_id: str
    job_id: str | None
    status: WorkflowRunStatus
    stage: str
    current_node_id: str | None
    input_json: dict[str, Any]
    result_json: dict[str, Any]
    node_state_json: dict[str, Any]
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class WorkflowRunCreateResponse(BaseModel):
    run: WorkflowRunResponse
    job: JobResponse
