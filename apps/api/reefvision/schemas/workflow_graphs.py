"""Typed workflow graph schemas with explicit execution readiness."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

WorkflowDataType = Literal[
    "project_reference",
    "image_collection",
    "dataset_version",
    "classification_dataset",
    "model_reference",
    "video_reference",
    "box_annotations",
    "mask_annotations",
    "detection_proposals",
    "detection_consensus",
    "detection_disagreements",
    "mask_proposals",
    "classification_predictions",
    "reviewed_boxes",
    "reviewed_masks",
    "reviewed_labels",
    "measurement_table",
    "longitudinal_analysis",
    "ecology_identity_registry",
    "connected_branch_preview",
    "ecology_measurement_candidates",
    "ecology_measurement_csv",
    "ecology_population_csv",
    "ecology_candidate_report",
    "paired_count_comparison",
    "relative_depth_maps",
    "training_result",
    "video_tracks",
    "video_3d_trajectories",
    "pose_tracks",
    "pose_temporal_tracks",
    "reviewed_pose_tracks",
    "behavior_analysis",
    "pose_active_learning_round",
    "verified_pose_active_learning_round",
    "pose_training_dataset",
    "pose_training_package",
    "results_package",
    "project_exchange_package",
]


class WorkflowPortDefinition(BaseModel):
    port_id: str
    display_name: str
    accepted_types: list[WorkflowDataType]
    required: bool = True
    multiple: bool = False


class WorkflowNodeDefinitionResponse(BaseModel):
    node_type: str
    display_name: str
    category: str
    description: str
    input_ports: list[WorkflowPortDefinition]
    output_ports: list[WorkflowPortDefinition]
    required_parameters: list[str]
    optional_parameters: dict[str, Any]
    execution_state: str
    executable: bool = False
    implementation_notes: list[str]


class WorkflowNodeInstance(BaseModel):
    node_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    node_type: str = Field(min_length=1, max_length=100)
    parameters: dict[str, Any] = Field(default_factory=dict)
    position: dict[str, float] | None = None


class WorkflowEdge(BaseModel):
    edge_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    source_node_id: str
    source_port_id: str
    target_node_id: str
    target_port_id: str


class WorkflowGraphRequest(BaseModel):
    graph_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=200)
    schema_version: str = "workflow-graph-0001"
    nodes: list[WorkflowNodeInstance] = Field(min_length=1, max_length=100)
    edges: list[WorkflowEdge] = Field(default_factory=list, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowGraphIssue(BaseModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    node_id: str | None = None
    edge_id: str | None = None


class WorkflowGraphValidationResponse(BaseModel):
    valid: bool
    graph_id: str
    issues: list[WorkflowGraphIssue]
    topological_order: list[str]
    referenced_model_ids: list[str]
    referenced_dataset_version_ids: list[str]
    referenced_video_ids: list[str]


class WorkflowPlanInputBinding(BaseModel):
    target_port_id: str
    source_node_id: str
    source_port_id: str
    data_type: WorkflowDataType


class WorkflowPlanStep(BaseModel):
    order: int
    node_id: str
    node_type: str
    display_name: str
    execution_state: str
    executable: bool = False
    parameters: dict[str, Any]
    input_bindings: list[WorkflowPlanInputBinding]
    output_types: dict[str, list[WorkflowDataType]]
    action: str


class WorkflowGraphPlanResponse(BaseModel):
    valid: bool
    graph_id: str
    executable: bool
    issues: list[WorkflowGraphIssue]
    steps: list[WorkflowPlanStep]
    execution_blocker: str | None
