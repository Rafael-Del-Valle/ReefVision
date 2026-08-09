"""Persistent workflow graph and execution API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from reefvision.schemas.workflow_graphs import WorkflowGraphRequest


class WorkflowGraphRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    graph_key: str
    name: str
    schema_version: str
    revision: int
    graph_json: dict[str, Any]
    graph_sha256: str
    created_at: datetime
    updated_at: datetime


class WorkflowGraphSaveRequest(BaseModel):
    graph: WorkflowGraphRequest
    create_new_revision: bool = True


class WorkflowRunCreateRequest(BaseModel):
    graph_record_id: str = Field(min_length=1, max_length=36)
    inputs: dict[str, Any] = Field(default_factory=dict)


class WorkflowReviewResumeRequest(BaseModel):
    reviewed_by: str = Field(default="local_user", min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=2000)


class WorkflowRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    workflow_graph_record_id: str
    job_id: str | None
    status: str
    graph_sha256: str
    input_json: dict[str, Any]
    result_json: dict[str, Any]
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class WorkflowNodeRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_run_id: str
    node_id: str
    node_type: str
    execution_order: int
    status: str
    parameters_json: dict[str, Any]
    input_artifact_ids_json: list[str]
    output_artifact_ids_json: list[str]
    result_json: dict[str, Any]
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None


class WorkflowArtifactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_run_id: str
    producer_node_run_id: str
    producer_port_id: str
    data_type: str
    payload_json: dict[str, Any]
    payload_sha256: str
    created_at: datetime


class WorkflowRunDetailResponse(BaseModel):
    run: WorkflowRunResponse
    nodes: list[WorkflowNodeRunResponse]
    artifacts: list[WorkflowArtifactResponse]
