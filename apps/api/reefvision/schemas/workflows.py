"""Typed workflow graph validation and planning schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

WorkflowNodeType = Literal[
    "image_input",
    "video_input",
    "detector",
    "segmenter",
    "classifier",
    "tracker",
    "measurement",
    "behavior_analysis",
    "active_learning",
    "export",
]
WorkflowIssueSeverity = Literal["error", "warning"]


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
