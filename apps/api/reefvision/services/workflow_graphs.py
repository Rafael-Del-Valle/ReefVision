"""Validate typed workflow graphs and produce execution-aware dry-run plans."""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from reefvision.db.models import (
    DatasetVersion,
    LabelClass,
    ModelRegistration,
    Project,
    VideoAsset,
)
from reefvision.schemas.workflow_graphs import (
    WorkflowEdge,
    WorkflowGraphIssue,
    WorkflowGraphPlanResponse,
    WorkflowGraphRequest,
    WorkflowGraphValidationResponse,
    WorkflowNodeDefinitionResponse,
    WorkflowPlanInputBinding,
    WorkflowPlanStep,
)
from reefvision.services.workflow_node_registry import workflow_node_registry
from reefvision.services.workflow_vlm import SUPPORTED_VLM_PROVIDERS

SUPPORTED_GRAPH_SCHEMA = "workflow-graph-0001"
_WORKFLOW_TRAINING_TASKS = {"detect", "segment", "semantic_segment"}


def install_workflow_node_registry(
    registry: Callable[[], dict[str, WorkflowNodeDefinitionResponse]],
) -> None:
    """Install an extended node registry for validation and planning."""

    global workflow_node_registry
    workflow_node_registry = registry


_MODEL_PURPOSES_BY_NODE: dict[str, set[str]] = {
    "detection_inference": {"detector"},
    "segmentation_inference": {"segmenter", "semantic_segmenter"},
    "classification_inference": {"classifier"},
    "prompt_assist_masks": {"assist"},
    "relative_depth_estimation": {"depth"},
    "video_tracking": {"detector", "segmenter"},
    "pose_inference": {"detector"},
    "pose_model_training": {"detector"},
}

_ACTIONS: dict[str, str] = {
    "project_source": "Resolve the project selected in the API route.",
    "project_images": "Resolve project images using the configured filters.",
    "dataset_version_source": "Load one immutable dataset version and its image membership.",
    "dataset_version_create": (
        "Freeze current reviewed project state into a new immutable dataset version."
    ),
    "registered_model_source": (
        "Resolve one registered project model and verify its checkpoint metadata."
    ),
    "project_video_source": "Resolve one managed source video.",
    "verified_masks_source": "Read existing non-deleted verified mask annotations.",
    "detection_inference": "Run the existing detector inference operation for the resolved images.",
    "vlm_detection": "Send images to one opted-in cloud vision provider and normalize boxes.",
    "detection_consensus": "Match independent detections and apply configurable N-of-M voting.",
    "segmentation_inference": "Run registered segmentation inference for the resolved images.",
    "classification_inference": "Run existing top-k classification inference.",
    "classification_dataset_materialize": (
        "Materialize an immutable whole-image or crop classification dataset."
    ),
    "classification_training": (
        "Run the production classification trainer and return its registered classifier."
    ),
    "model_training": (
        "Run the existing task-aware Training workspace against an immutable dataset version."
    ),
    "register_trained_model": (
        "Register a completed training checkpoint with dataset, split, and experiment lineage."
    ),
    "training_results_package": (
        "Build and verify a scientific Results Package from the completed training run."
    ),
    "detection_review_gate": "Pause until detection proposals are reviewed by a human.",
    "prompt_assist_masks": "Generate reviewable raster masks from reviewed detection boxes.",
    "relative_depth_estimation": (
        "Generate checksummed relative-depth arrays and previews for project images."
    ),
    "mask_review_gate": "Pause until mask proposals are reviewed by a human.",
    "classification_review_gate": "Pause until class predictions are reviewed by a human.",
    "mask_measurements": "Calculate Phase 4 measurements and create the selected table export.",
    "video_tracking": "Run existing detector-plus-tracker video tracking.",
    "video_depth_3d_analytics": (
        "Reconstruct calibrated metric 3D trajectories from video tracks and depth samples."
    ),
    "video_metric_depth_3d": (
        "Estimate model-metric video depth and reconstruct Scientific 3D fish trajectories."
    ),
    "pose_inference": (
        "Run the registered pose backend and persist canonical pose-bearing video tracks."
    ),
    "pose_temporal_association": (
        "Build persistent landmark identities, association confidence, occlusion state, "
        "and identity-break provenance."
    ),
    "pose_review_gate": ("Pause until temporal pose state has explicit scientist review."),
    "behavior_dynamics": (
        "Calculate deterministic behavior dynamics from scientist-reviewed tracks."
    ),
    "pose_active_learning": (
        "Create an explainable pose-specific Active Learning acquisition round."
    ),
    "pose_active_learning_review_gate": (
        "Pause until Active Learning candidates have explicit scientist review outcomes."
    ),
    "pose_training_dataset_freeze": (
        "Freeze only verified pose candidates into immutable Phase 9 training truth."
    ),
    "pose_training_export": (
        "Export the immutable pose dataset through the validated Phase 9 exporters."
    ),
    "pose_model_training": (
        "Retrain an Ultralytics pose checkpoint from immutable scientist-verified pose truth."
    ),
    "project_exchange_export": "Build a Phase 9 checksummed project exchange export inline.",
    "ecology_identity_registry_source": (
        "Snapshot versioned project-owned organism identities; scientist review remains required."
    ),
    "ecology_measurement_csv_export": (
        "Export source-linked projected measurements with rechecked QC; "
        "retain unverified evidence and scientist review."
    ),
    "ecology_longitudinal_analysis": (
        "Analyze repeated organism observations; label source evidence unverified."
    ),
    "ecology_paired_count_comparison": (
        "Compare human-model counts without claiming verified agreement."
    ),
}


class WorkflowGraphService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.registry = workflow_node_registry()

    def node_registry(self) -> list[WorkflowNodeDefinitionResponse]:
        return sorted(
            self.registry.values(),
            key=lambda item: (item.category, item.display_name, item.node_type),
        )

    def _project(self, project_id: str) -> Project | None:
        return self.session.get(Project, project_id)

    @staticmethod
    def _issue(
        severity: str,
        code: str,
        message: str,
        *,
        node_id: str | None = None,
        edge_id: str | None = None,
    ) -> WorkflowGraphIssue:
        return WorkflowGraphIssue(
            severity=severity,
            code=code,
            message=message,
            node_id=node_id,
            edge_id=edge_id,
        )

    @staticmethod
    def _port_map(
        definition: WorkflowNodeDefinitionResponse,
        *,
        inputs: bool,
    ) -> dict[str, Any]:
        ports = definition.input_ports if inputs else definition.output_ports
        return {port.port_id: port for port in ports}

    def _validate_dataset_source(
        self,
        project_id: str,
        node_id: str,
        parameters: dict[str, Any],
        issues: list[WorkflowGraphIssue],
        referenced_dataset_ids: set[str],
    ) -> None:
        version_id = str(parameters.get("dataset_version_id", ""))
        if not version_id:
            return
        referenced_dataset_ids.add(version_id)
        version = self.session.get(DatasetVersion, version_id)
        if version is None or version.project_id != project_id:
            issues.append(
                self._issue(
                    "error",
                    "dataset_scope_mismatch",
                    "Dataset version does not belong to this project",
                    node_id=node_id,
                )
            )
        elif version.status != "complete":
            issues.append(
                self._issue(
                    "error",
                    "dataset_incomplete",
                    "Dataset version must be complete",
                    node_id=node_id,
                )
            )

    def _validate_model_source(
        self,
        project_id: str,
        node_id: str,
        parameters: dict[str, Any],
        issues: list[WorkflowGraphIssue],
        referenced_model_ids: set[str],
    ) -> None:
        model_id = str(parameters.get("model_id", ""))
        if not model_id:
            return
        referenced_model_ids.add(model_id)
        model = self.session.get(ModelRegistration, model_id)
        if model is None or model.project_id != project_id:
            issues.append(
                self._issue(
                    "error",
                    "model_scope_mismatch",
                    "Registered model does not belong to this project",
                    node_id=node_id,
                )
            )

    def _validate_video_source(
        self,
        project_id: str,
        node_id: str,
        parameters: dict[str, Any],
        issues: list[WorkflowGraphIssue],
        referenced_video_ids: set[str],
    ) -> None:
        video_id = str(parameters.get("video_id", ""))
        if not video_id:
            return
        referenced_video_ids.add(video_id)
        video = self.session.get(VideoAsset, video_id)
        if video is None or video.project_id != project_id:
            issues.append(
                self._issue(
                    "error",
                    "video_scope_mismatch",
                    "Video does not belong to this project",
                    node_id=node_id,
                )
            )

    def _validate_vlm_node(
        self,
        project_id: str,
        node_id: str,
        parameters: dict[str, Any],
        issues: list[WorkflowGraphIssue],
    ) -> None:
        provider = str(parameters.get("provider") or "").strip().lower()
        if provider and provider not in SUPPORTED_VLM_PROVIDERS:
            issues.append(
                self._issue(
                    "error",
                    "unsupported_vlm_provider",
                    f"Cloud VLM provider must be one of {sorted(SUPPORTED_VLM_PROVIDERS)}",
                    node_id=node_id,
                )
            )
        class_ids = [str(value) for value in parameters.get("label_class_ids", [])]
        if len(class_ids) != len(set(class_ids)):
            issues.append(
                self._issue(
                    "error",
                    "duplicate_vlm_class",
                    "Cloud VLM label_class_ids must be unique",
                    node_id=node_id,
                )
            )
        for class_id in class_ids:
            label_class = self.session.get(LabelClass, class_id)
            if label_class is None or label_class.project_id != project_id:
                issues.append(
                    self._issue(
                        "error",
                        "vlm_class_scope_mismatch",
                        "Every Cloud VLM class must belong to the selected project",
                        node_id=node_id,
                    )
                )
                break

    def _validate_training_node(
        self,
        node_id: str,
        parameters: dict[str, Any],
        issues: list[WorkflowGraphIssue],
    ) -> None:
        task = str(parameters.get("task") or "").strip()
        if task and task not in _WORKFLOW_TRAINING_TASKS:
            issues.append(
                self._issue(
                    "error",
                    "unsupported_training_task",
                    "Model Training task must be detect, segment, or semantic_segment",
                    node_id=node_id,
                )
            )
        if parameters.get("catalog_model_id") and parameters.get("architecture"):
            issues.append(
                self._issue(
                    "warning",
                    "training_catalog_architecture_override",
                    "catalog_model_id resolves its own architecture; the explicit "
                    "architecture may be ignored",
                    node_id=node_id,
                )
            )

    def validate(
        self,
        project_id: str,
        graph: WorkflowGraphRequest,
    ) -> WorkflowGraphValidationResponse:
        issues: list[WorkflowGraphIssue] = []
        referenced_model_ids: set[str] = set()
        referenced_dataset_ids: set[str] = set()
        referenced_video_ids: set[str] = set()

        project = self._project(project_id)
        if project is None:
            issues.append(self._issue("error", "project_not_found", "Project not found"))
        if graph.schema_version != SUPPORTED_GRAPH_SCHEMA:
            issues.append(
                self._issue(
                    "error",
                    "unsupported_schema",
                    f"Graph schema must be {SUPPORTED_GRAPH_SCHEMA}",
                )
            )

        node_counts = Counter(node.node_id for node in graph.nodes)
        for node_id, count in node_counts.items():
            if count > 1:
                issues.append(
                    self._issue(
                        "error",
                        "duplicate_node_id",
                        f"Node ID appears {count} times",
                        node_id=node_id,
                    )
                )
        nodes = {node.node_id: node for node in graph.nodes}
        definitions: dict[str, WorkflowNodeDefinitionResponse] = {}

        for node in graph.nodes:
            definition = self.registry.get(node.node_type)
            if definition is None:
                issues.append(
                    self._issue(
                        "error",
                        "unknown_node_type",
                        f"Unknown node type: {node.node_type}",
                        node_id=node.node_id,
                    )
                )
                continue
            definitions[node.node_id] = definition
            for parameter in definition.required_parameters:
                value = node.parameters.get(parameter)
                if value in (None, "", [], {}):
                    issues.append(
                        self._issue(
                            "error",
                            "missing_parameter",
                            f"Required parameter is missing: {parameter}",
                            node_id=node.node_id,
                        )
                    )

            if node.node_type == "dataset_version_source":
                self._validate_dataset_source(
                    project_id,
                    node.node_id,
                    node.parameters,
                    issues,
                    referenced_dataset_ids,
                )
            elif node.node_type == "registered_model_source":
                self._validate_model_source(
                    project_id,
                    node.node_id,
                    node.parameters,
                    issues,
                    referenced_model_ids,
                )
            elif node.node_type == "project_video_source":
                self._validate_video_source(
                    project_id,
                    node.node_id,
                    node.parameters,
                    issues,
                    referenced_video_ids,
                )
            elif node.node_type == "vlm_detection":
                self._validate_vlm_node(project_id, node.node_id, node.parameters, issues)
            elif node.node_type == "model_training":
                self._validate_training_node(node.node_id, node.parameters, issues)

        edge_counts = Counter(edge.edge_id for edge in graph.edges)
        for edge_id, count in edge_counts.items():
            if count > 1:
                issues.append(
                    self._issue(
                        "error",
                        "duplicate_edge_id",
                        f"Edge ID appears {count} times",
                        edge_id=edge_id,
                    )
                )

        incoming: dict[tuple[str, str], list[WorkflowEdge]] = defaultdict(list)
        outgoing_nodes: dict[str, set[str]] = defaultdict(set)
        indegree: dict[str, int] = {node_id: 0 for node_id in nodes}

        for edge in graph.edges:
            source = nodes.get(edge.source_node_id)
            target = nodes.get(edge.target_node_id)
            if source is None or target is None:
                issues.append(
                    self._issue(
                        "error",
                        "edge_node_missing",
                        "Edge references a node that is not present",
                        edge_id=edge.edge_id,
                    )
                )
                continue
            if edge.source_node_id == edge.target_node_id:
                issues.append(
                    self._issue(
                        "error",
                        "self_edge",
                        "A node cannot connect to itself",
                        edge_id=edge.edge_id,
                    )
                )
                continue
            source_definition = definitions.get(source.node_id)
            target_definition = definitions.get(target.node_id)
            if source_definition is None or target_definition is None:
                continue
            source_port = self._port_map(source_definition, inputs=False).get(edge.source_port_id)
            target_port = self._port_map(target_definition, inputs=True).get(edge.target_port_id)
            if source_port is None:
                issues.append(
                    self._issue(
                        "error",
                        "source_port_missing",
                        f"Unknown source port: {edge.source_port_id}",
                        edge_id=edge.edge_id,
                    )
                )
                continue
            if target_port is None:
                issues.append(
                    self._issue(
                        "error",
                        "target_port_missing",
                        f"Unknown target port: {edge.target_port_id}",
                        edge_id=edge.edge_id,
                    )
                )
                continue
            compatible = [
                item for item in source_port.accepted_types if item in target_port.accepted_types
            ]
            if not compatible:
                issues.append(
                    self._issue(
                        "error",
                        "incompatible_port_types",
                        (
                            f"{source.node_id}.{source_port.port_id} produces "
                            f"{source_port.accepted_types}, but "
                            f"{target.node_id}.{target_port.port_id} accepts "
                            f"{target_port.accepted_types}"
                        ),
                        edge_id=edge.edge_id,
                    )
                )
                continue
            incoming[(target.node_id, target_port.port_id)].append(edge)
            if target.node_id not in outgoing_nodes[source.node_id]:
                outgoing_nodes[source.node_id].add(target.node_id)
                indegree[target.node_id] += 1

        for node_id, definition in definitions.items():
            for port in definition.input_ports:
                bindings = incoming.get((node_id, port.port_id), [])
                if port.required and not bindings:
                    issues.append(
                        self._issue(
                            "error",
                            "required_input_missing",
                            f"Required input is not connected: {port.port_id}",
                            node_id=node_id,
                        )
                    )
                if not port.multiple and len(bindings) > 1:
                    issues.append(
                        self._issue(
                            "error",
                            "multiple_input_bindings",
                            f"Input accepts one connection: {port.port_id}",
                            node_id=node_id,
                        )
                    )

        for node in graph.nodes:
            accepted_purposes = _MODEL_PURPOSES_BY_NODE.get(node.node_type)
            if accepted_purposes is None:
                continue
            model_edges = incoming.get((node.node_id, "model"), [])
            if len(model_edges) != 1:
                continue
            source_node = nodes.get(model_edges[0].source_node_id)
            if source_node is not None and source_node.node_type == "register_trained_model":
                continue
            if source_node is None or source_node.node_type != "registered_model_source":
                issues.append(
                    self._issue(
                        "error",
                        "model_source_required",
                        "Model input must come from a registered-model source or training "
                        "registration node",
                        node_id=node.node_id,
                    )
                )
                continue
            model_id = str(source_node.parameters.get("model_id", ""))
            model = self.session.get(ModelRegistration, model_id) if model_id else None
            if (
                model is not None
                and model.project_id == project_id
                and model.purpose not in accepted_purposes
            ):
                issues.append(
                    self._issue(
                        "error",
                        "model_purpose_mismatch",
                        (
                            f"{node.node_type} requires model purpose "
                            f"{sorted(accepted_purposes)}, found {model.purpose}"
                        ),
                        node_id=node.node_id,
                    )
                )

        queue = deque(sorted(node_id for node_id, degree in indegree.items() if degree == 0))
        topological_order: list[str] = []
        remaining_indegree = dict(indegree)
        while queue:
            node_id = queue.popleft()
            topological_order.append(node_id)
            for target_id in sorted(outgoing_nodes.get(node_id, set())):
                remaining_indegree[target_id] -= 1
                if remaining_indegree[target_id] == 0:
                    queue.append(target_id)
        if len(topological_order) != len(nodes):
            issues.append(
                self._issue(
                    "error",
                    "cycle_detected",
                    "Workflow graphs must be acyclic",
                )
            )
            topological_order = []

        valid = not any(issue.severity == "error" for issue in issues)
        return WorkflowGraphValidationResponse(
            valid=valid,
            graph_id=graph.graph_id,
            issues=issues,
            topological_order=topological_order,
            referenced_model_ids=sorted(referenced_model_ids),
            referenced_dataset_version_ids=sorted(referenced_dataset_ids),
            referenced_video_ids=sorted(referenced_video_ids),
        )

    def plan(
        self,
        project_id: str,
        graph: WorkflowGraphRequest,
    ) -> WorkflowGraphPlanResponse:
        validation = self.validate(project_id, graph)
        if not validation.valid:
            return WorkflowGraphPlanResponse(
                valid=False,
                graph_id=graph.graph_id,
                executable=False,
                issues=validation.issues,
                steps=[],
                execution_blocker="Graph validation failed. Invalid graphs are never executed.",
            )

        nodes = {node.node_id: node for node in graph.nodes}
        edge_by_target: dict[str, list[WorkflowEdge]] = defaultdict(list)
        for edge in graph.edges:
            edge_by_target[edge.target_node_id].append(edge)
        steps: list[WorkflowPlanStep] = []
        blocked_nodes: list[str] = []
        for order, node_id in enumerate(validation.topological_order, start=1):
            node = nodes[node_id]
            definition = self.registry[node.node_type]
            if not definition.executable:
                blocked_nodes.append(f"{node.node_id} ({definition.display_name})")
            source_definitions = {
                edge.edge_id: self.registry[nodes[edge.source_node_id].node_type]
                for edge in edge_by_target.get(node_id, [])
            }
            bindings: list[WorkflowPlanInputBinding] = []
            for edge in sorted(edge_by_target.get(node_id, []), key=lambda item: item.edge_id):
                source_port = self._port_map(source_definitions[edge.edge_id], inputs=False)[
                    edge.source_port_id
                ]
                target_port = self._port_map(definition, inputs=True)[edge.target_port_id]
                data_type = next(
                    item
                    for item in source_port.accepted_types
                    if item in target_port.accepted_types
                )
                bindings.append(
                    WorkflowPlanInputBinding(
                        target_port_id=edge.target_port_id,
                        source_node_id=edge.source_node_id,
                        source_port_id=edge.source_port_id,
                        data_type=data_type,
                    )
                )
            steps.append(
                WorkflowPlanStep(
                    order=order,
                    node_id=node.node_id,
                    node_type=node.node_type,
                    display_name=definition.display_name,
                    execution_state=definition.execution_state,
                    executable=definition.executable,
                    parameters={**definition.optional_parameters, **node.parameters},
                    input_bindings=bindings,
                    output_types={
                        port.port_id: port.accepted_types for port in definition.output_ports
                    },
                    action=_ACTIONS[node.node_type],
                )
            )
        executable = not blocked_nodes
        return WorkflowGraphPlanResponse(
            valid=True,
            graph_id=graph.graph_id,
            executable=executable,
            issues=validation.issues,
            steps=steps,
            execution_blocker=(
                None
                if executable
                else "Workflow contains nodes without execution adapters: "
                + ", ".join(blocked_nodes)
            ),
        )
