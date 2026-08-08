"""Validate typed workflow graphs and produce non-executing dry-run plans."""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from typing import Any

from sqlalchemy.orm import Session

from reefvision.db.models import DatasetVersion, ModelRegistration, Project, VideoAsset
from reefvision.schemas.workflow_graphs import (
    WorkflowDataType,
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

SUPPORTED_GRAPH_SCHEMA = "workflow-graph-0001"

_MODEL_PURPOSES_BY_NODE: dict[str, set[str]] = {
    "detection_inference": {"detector"},
    "segmentation_inference": {"segmenter", "semantic_segmenter"},
    "classification_inference": {"classifier"},
    "video_tracking": {"detector", "segmenter"},
}

_ACTIONS: dict[str, str] = {
    "project_source": "Resolve the project selected in the API route.",
    "project_images": "Resolve project images using the configured filters.",
    "dataset_version_source": "Load one immutable dataset version and its image membership.",
    "registered_model_source": "Resolve one registered project model and verify its checkpoint metadata.",
    "project_video_source": "Resolve one managed source video.",
    "verified_masks_source": "Read existing non-deleted mask annotations.",
    "detection_inference": "Queue the existing detector inference job for the resolved images.",
    "segmentation_inference": "Queue the existing segmentation inference job for the resolved images.",
    "classification_inference": "Queue the existing top-k classification inference job.",
    "detection_review_gate": "Pause until detection proposals are reviewed by a human.",
    "mask_review_gate": "Pause until mask proposals are reviewed by a human.",
    "classification_review_gate": "Pause until class predictions are reviewed by a human.",
    "mask_measurements": "Calculate Phase 4 measurements and create the selected table export.",
    "video_tracking": "Queue the existing detector-plus-tracker video job.",
    "project_exchange_export": "Queue a Phase 9 checksummed project exchange export.",
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
                version_id = str(node.parameters.get("dataset_version_id", ""))
                if version_id:
                    referenced_dataset_ids.add(version_id)
                    version = self.session.get(DatasetVersion, version_id)
                    if version is None or version.project_id != project_id:
                        issues.append(
                            self._issue(
                                "error",
                                "dataset_scope_mismatch",
                                "Dataset version does not belong to this project",
                                node_id=node.node_id,
                            )
                        )
                    elif version.status != "complete":
                        issues.append(
                            self._issue(
                                "error",
                                "dataset_incomplete",
                                "Dataset version must be complete",
                                node_id=node.node_id,
                            )
                        )
            elif node.node_type == "registered_model_source":
                model_id = str(node.parameters.get("model_id", ""))
                if model_id:
                    referenced_model_ids.add(model_id)
                    model = self.session.get(ModelRegistration, model_id)
                    if model is None or model.project_id != project_id:
                        issues.append(
                            self._issue(
                                "error",
                                "model_scope_mismatch",
                                "Registered model does not belong to this project",
                                node_id=node.node_id,
                            )
                        )
            elif node.node_type == "project_video_source":
                video_id = str(node.parameters.get("video_id", ""))
                if video_id:
                    referenced_video_ids.add(video_id)
                    video = self.session.get(VideoAsset, video_id)
                    if video is None or video.project_id != project_id:
                        issues.append(
                            self._issue(
                                "error",
                                "video_scope_mismatch",
                                "Video does not belong to this project",
                                node_id=node.node_id,
                            )
                        )

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
        valid_edge_types: dict[str, WorkflowDataType] = {}

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
            source_port = self._port_map(source_definition, inputs=False).get(
                edge.source_port_id
            )
            target_port = self._port_map(target_definition, inputs=True).get(
                edge.target_port_id
            )
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
                item
                for item in source_port.accepted_types
                if item in target_port.accepted_types
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
            valid_edge_types[edge.edge_id] = compatible[0]
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
            if source_node is None or source_node.node_type != "registered_model_source":
                issues.append(
                    self._issue(
                        "error",
                        "model_source_required",
                        "Model input must come from a Registered Model source node",
                        node_id=node.node_id,
                    )
                )
                continue
            model_id = str(source_node.parameters.get("model_id", ""))
            model = self.session.get(ModelRegistration, model_id) if model_id else None
            if model is not None and model.project_id == project_id:
                if model.purpose not in accepted_purposes:
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
                    "Workflow graphs must be acyclic in the Phase 10 foundation",
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
                execution_blocker=(
                    "Graph validation failed. Phase 10 never executes invalid graphs."
                ),
            )

        nodes = {node.node_id: node for node in graph.nodes}
        edge_by_target: dict[str, list[WorkflowEdge]] = defaultdict(list)
        for edge in graph.edges:
            edge_by_target[edge.target_node_id].append(edge)
        steps: list[WorkflowPlanStep] = []
        for order, node_id in enumerate(validation.topological_order, start=1):
            node = nodes[node_id]
            definition = self.registry[node.node_type]
            source_definitions = {
                edge.edge_id: self.registry[nodes[edge.source_node_id].node_type]
                for edge in edge_by_target.get(node_id, [])
            }
            bindings: list[WorkflowPlanInputBinding] = []
            for edge in sorted(edge_by_target.get(node_id, []), key=lambda item: item.edge_id):
                source_port = self._port_map(
                    source_definitions[edge.edge_id], inputs=False
                )[edge.source_port_id]
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
                    parameters={**definition.optional_parameters, **node.parameters},
                    input_bindings=bindings,
                    output_types={
                        port.port_id: port.accepted_types
                        for port in definition.output_ports
                    },
                    action=_ACTIONS[node.node_type],
                )
            )
        return WorkflowGraphPlanResponse(
            valid=True,
            graph_id=graph.graph_id,
            executable=False,
            issues=validation.issues,
            steps=steps,
            execution_blocker=(
                "Phase 10 defines and validates graph semantics only. "
                "No graph executor, scheduling engine, or automatic review-gate continuation is enabled."
            ),
        )
