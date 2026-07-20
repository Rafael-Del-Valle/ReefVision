"""Validate fusion workflow graphs and produce deterministic execution plans."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from sqlalchemy.orm import Session

from reefvision.db.models import ModelRegistration, Project
from reefvision.domain.errors import NotFoundError
from reefvision.schemas.workflows import (
    WorkflowEdge,
    WorkflowExecutionStage,
    WorkflowNode,
    WorkflowNodeDefinition,
    WorkflowPortDefinition,
    WorkflowTemplate,
    WorkflowValidationIssue,
    WorkflowValidationRequest,
    WorkflowValidationResponse,
)
from reefvision.storage.datasets import canonical_json_sha256


@dataclass(frozen=True)
class _NodeDefinition:
    display_name: str
    inputs: dict[str, tuple[str, bool]]
    outputs: dict[str, str]
    model_tasks: tuple[str, ...] = ()


NODE_DEFINITIONS: dict[str, _NodeDefinition] = {
    "image_input": _NodeDefinition(
        display_name="Image input",
        inputs={},
        outputs={"images": "images"},
    ),
    "video_input": _NodeDefinition(
        display_name="Video input",
        inputs={},
        outputs={"video": "video"},
    ),
    "detector": _NodeDefinition(
        display_name="Object detector",
        inputs={"images": ("images", True)},
        outputs={"detections": "detections"},
        model_tasks=("detect",),
    ),
    "segmenter": _NodeDefinition(
        display_name="Segmenter",
        inputs={
            "images": ("images", True),
            "prompts": ("detections", False),
        },
        outputs={"masks": "masks"},
        model_tasks=("segment", "semantic_segment"),
    ),
    "classifier": _NodeDefinition(
        display_name="Crop classifier",
        inputs={
            "images": ("images", True),
            "regions": ("detections", True),
        },
        outputs={"classifications": "classifications"},
        model_tasks=("classify",),
    ),
    "tracker": _NodeDefinition(
        display_name="Video tracker",
        inputs={"video": ("video", True)},
        outputs={"tracks": "tracks"},
        model_tasks=("detect",),
    ),
    "measurement": _NodeDefinition(
        display_name="Coral measurement",
        inputs={
            "masks": ("masks", True),
            "detections": ("detections", False),
        },
        outputs={"measurements": "measurements"},
    ),
    "behavior_analysis": _NodeDefinition(
        display_name="Behavior analysis",
        inputs={"tracks": ("tracks", True)},
        outputs={"measurements": "measurements"},
    ),
    "active_learning": _NodeDefinition(
        display_name="Active-learning selection",
        inputs={"predictions": ("predictions", True)},
        outputs={"review_batch": "review_batch"},
    ),
    "export": _NodeDefinition(
        display_name="Export",
        inputs={"artifact": ("artifact", True)},
        outputs={"archive": "export_archive"},
    ),
}

COMPATIBLE_SOURCE_TYPES: dict[str, set[str]] = {
    "predictions": {"detections", "masks", "classifications"},
    "artifact": {
        "detections",
        "masks",
        "classifications",
        "tracks",
        "measurements",
        "review_batch",
        "export_archive",
    },
}


class WorkflowService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    @staticmethod
    def definitions() -> list[WorkflowNodeDefinition]:
        return [
            WorkflowNodeDefinition(
                node_type=node_type,
                display_name=definition.display_name,
                inputs=[
                    WorkflowPortDefinition(
                        name=name,
                        data_type=data_type,
                        required=required,
                    )
                    for name, (data_type, required) in definition.inputs.items()
                ],
                outputs=[
                    WorkflowPortDefinition(
                        name=name,
                        data_type=data_type,
                        required=True,
                    )
                    for name, data_type in definition.outputs.items()
                ],
                requires_model=bool(definition.model_tasks),
                supported_model_tasks=list(definition.model_tasks),
            )
            for node_type, definition in NODE_DEFINITIONS.items()
        ]

    @staticmethod
    def templates() -> list[WorkflowTemplate]:
        return [
            WorkflowTemplate(
                template_id="coral-segmentation-measurement",
                name="Coral segmentation and measurement",
                description=(
                    "Segment coral imagery, calculate scientific measurements, "
                    "and export the resulting table."
                ),
                workflow=WorkflowValidationRequest(
                    name="Coral segmentation and measurement",
                    nodes=[
                        WorkflowNode(id="images", node_type="image_input"),
                        WorkflowNode(
                            id="segment",
                            node_type="segmenter",
                            configuration={"model_id": "<select-segmenter>"},
                        ),
                        WorkflowNode(id="measure", node_type="measurement"),
                        WorkflowNode(
                            id="export",
                            node_type="export",
                            configuration={"format": "csv"},
                        ),
                    ],
                    edges=[
                        WorkflowEdge(
                            source_node_id="images",
                            source_port="images",
                            target_node_id="segment",
                            target_port="images",
                        ),
                        WorkflowEdge(
                            source_node_id="segment",
                            source_port="masks",
                            target_node_id="measure",
                            target_port="masks",
                        ),
                        WorkflowEdge(
                            source_node_id="measure",
                            source_port="measurements",
                            target_node_id="export",
                            target_port="artifact",
                        ),
                    ],
                ),
            ),
            WorkflowTemplate(
                template_id="polyp-detection-classification",
                name="Polyp detection and classification",
                description=(
                    "Detect polyp regions, classify species/state crops, and export "
                    "reviewable predictions."
                ),
                workflow=WorkflowValidationRequest(
                    name="Polyp detection and classification",
                    nodes=[
                        WorkflowNode(id="images", node_type="image_input"),
                        WorkflowNode(
                            id="detect",
                            node_type="detector",
                            configuration={"model_id": "<select-detector>"},
                        ),
                        WorkflowNode(
                            id="classify",
                            node_type="classifier",
                            configuration={"model_id": "<select-classifier>"},
                        ),
                        WorkflowNode(id="export", node_type="export"),
                    ],
                    edges=[
                        WorkflowEdge(
                            source_node_id="images",
                            source_port="images",
                            target_node_id="detect",
                            target_port="images",
                        ),
                        WorkflowEdge(
                            source_node_id="images",
                            source_port="images",
                            target_node_id="classify",
                            target_port="images",
                        ),
                        WorkflowEdge(
                            source_node_id="detect",
                            source_port="detections",
                            target_node_id="classify",
                            target_port="regions",
                        ),
                        WorkflowEdge(
                            source_node_id="classify",
                            source_port="classifications",
                            target_node_id="export",
                            target_port="artifact",
                        ),
                    ],
                ),
            ),
            WorkflowTemplate(
                template_id="fish-tracking-behavior",
                name="Fish tracking and behavior",
                description=(
                    "Track fish in managed video, calculate behavior metrics, and "
                    "export research tables."
                ),
                workflow=WorkflowValidationRequest(
                    name="Fish tracking and behavior",
                    nodes=[
                        WorkflowNode(id="video", node_type="video_input"),
                        WorkflowNode(
                            id="track",
                            node_type="tracker",
                            configuration={"model_id": "<select-detector>"},
                        ),
                        WorkflowNode(
                            id="behavior",
                            node_type="behavior_analysis",
                        ),
                        WorkflowNode(id="export", node_type="export"),
                    ],
                    edges=[
                        WorkflowEdge(
                            source_node_id="video",
                            source_port="video",
                            target_node_id="track",
                            target_port="video",
                        ),
                        WorkflowEdge(
                            source_node_id="track",
                            source_port="tracks",
                            target_node_id="behavior",
                            target_port="tracks",
                        ),
                        WorkflowEdge(
                            source_node_id="behavior",
                            source_port="measurements",
                            target_node_id="export",
                            target_port="artifact",
                        ),
                    ],
                ),
            ),
        ]

    @staticmethod
    def _types_compatible(source_type: str, target_type: str) -> bool:
        if source_type == target_type:
            return True
        return source_type in COMPATIBLE_SOURCE_TYPES.get(target_type, set())

    def _validate_model(
        self,
        project_id: str,
        node: WorkflowNode,
        definition: _NodeDefinition,
        issues: list[WorkflowValidationIssue],
    ) -> None:
        if not definition.model_tasks:
            return
        model_id = node.configuration.get("model_id")
        if not isinstance(model_id, str) or not model_id.strip():
            issues.append(
                WorkflowValidationIssue(
                    severity="error",
                    code="model_required",
                    node_id=node.id,
                    message=f"{definition.display_name} requires a registered model.",
                )
            )
            return
        model = self.session.get(ModelRegistration, model_id)
        if model is None or model.project_id != project_id:
            issues.append(
                WorkflowValidationIssue(
                    severity="error",
                    code="model_not_found",
                    node_id=node.id,
                    message="The configured model is not registered in this project.",
                )
            )
            return
        if model.task not in definition.model_tasks:
            issues.append(
                WorkflowValidationIssue(
                    severity="error",
                    code="model_task_mismatch",
                    node_id=node.id,
                    message=(
                        f"Model task {model.task!r} is incompatible with {definition.display_name}."
                    ),
                )
            )

    def validate(
        self,
        project_id: str,
        request: WorkflowValidationRequest,
    ) -> WorkflowValidationResponse:
        self._project(project_id)
        issues: list[WorkflowValidationIssue] = []
        node_by_id = {node.id: node for node in request.nodes}
        incoming: dict[str, list[tuple[int, WorkflowEdge]]] = defaultdict(list)
        outgoing: dict[str, list[tuple[int, WorkflowEdge]]] = defaultdict(list)
        target_connections: set[tuple[str, str]] = set()
        valid_edges: list[WorkflowEdge] = []

        for node in request.nodes:
            definition = NODE_DEFINITIONS[node.node_type]
            self._validate_model(project_id, node, definition, issues)

        for edge_index, edge in enumerate(request.edges):
            source = node_by_id.get(edge.source_node_id)
            target = node_by_id.get(edge.target_node_id)
            if source is None or target is None:
                issues.append(
                    WorkflowValidationIssue(
                        severity="error",
                        code="edge_node_missing",
                        edge_index=edge_index,
                        message="Workflow edges must reference existing nodes.",
                    )
                )
                continue
            source_definition = NODE_DEFINITIONS[source.node_type]
            target_definition = NODE_DEFINITIONS[target.node_type]
            source_type = source_definition.outputs.get(edge.source_port)
            target_port = target_definition.inputs.get(edge.target_port)
            if source_type is None:
                issues.append(
                    WorkflowValidationIssue(
                        severity="error",
                        code="source_port_missing",
                        edge_index=edge_index,
                        node_id=source.id,
                        message=(f"Node {source.id!r} has no output port {edge.source_port!r}."),
                    )
                )
                continue
            if target_port is None:
                issues.append(
                    WorkflowValidationIssue(
                        severity="error",
                        code="target_port_missing",
                        edge_index=edge_index,
                        node_id=target.id,
                        message=(f"Node {target.id!r} has no input port {edge.target_port!r}."),
                    )
                )
                continue
            target_type, _required = target_port
            if not self._types_compatible(source_type, target_type):
                issues.append(
                    WorkflowValidationIssue(
                        severity="error",
                        code="port_type_mismatch",
                        edge_index=edge_index,
                        node_id=target.id,
                        message=(f"Cannot connect {source_type!r} to input type {target_type!r}."),
                    )
                )
                continue
            target_key = (target.id, edge.target_port)
            if target_key in target_connections:
                issues.append(
                    WorkflowValidationIssue(
                        severity="error",
                        code="input_already_connected",
                        edge_index=edge_index,
                        node_id=target.id,
                        message=(f"Input {edge.target_port!r} already has a connection."),
                    )
                )
                continue
            target_connections.add(target_key)
            incoming[target.id].append((edge_index, edge))
            outgoing[source.id].append((edge_index, edge))
            valid_edges.append(edge)

        for node in request.nodes:
            definition = NODE_DEFINITIONS[node.node_type]
            connected_ports = {edge.target_port for _index, edge in incoming[node.id]}
            for port_name, (_data_type, required) in definition.inputs.items():
                if required and port_name not in connected_ports:
                    issues.append(
                        WorkflowValidationIssue(
                            severity="error",
                            code="required_input_missing",
                            node_id=node.id,
                            message=(f"Required input {port_name!r} is not connected."),
                        )
                    )
            if definition.outputs and not outgoing[node.id] and node.node_type != "export":
                issues.append(
                    WorkflowValidationIssue(
                        severity="warning",
                        code="output_unused",
                        node_id=node.id,
                        message="This node's output is not used by another node.",
                    )
                )

        indegree = dict.fromkeys(node_by_id, 0)
        adjacency: dict[str, list[str]] = defaultdict(list)
        for edge in valid_edges:
            adjacency[edge.source_node_id].append(edge.target_node_id)
            indegree[edge.target_node_id] += 1
        ready = deque(sorted(node_id for node_id, degree in indegree.items() if degree == 0))
        topological_order: list[str] = []
        stages: list[WorkflowExecutionStage] = []
        stage_index = 0
        while ready:
            stage_nodes = sorted(ready)
            ready.clear()
            stages.append(
                WorkflowExecutionStage(
                    stage_index=stage_index,
                    node_ids=stage_nodes,
                )
            )
            stage_index += 1
            for node_id in stage_nodes:
                topological_order.append(node_id)
                for target_id in sorted(adjacency[node_id]):
                    indegree[target_id] -= 1
                    if indegree[target_id] == 0:
                        ready.append(target_id)
        if len(topological_order) != len(node_by_id):
            cyclic_nodes = sorted(set(node_by_id) - set(topological_order))
            issues.append(
                WorkflowValidationIssue(
                    severity="error",
                    code="workflow_cycle",
                    message=("The workflow contains a cycle involving: " + ", ".join(cyclic_nodes)),
                )
            )

        checksum = canonical_json_sha256(request.model_dump(mode="json"))
        return WorkflowValidationResponse(
            project_id=project_id,
            name=request.name,
            valid=not any(issue.severity == "error" for issue in issues),
            workflow_checksum=checksum,
            topological_order=topological_order,
            execution_stages=stages,
            issues=sorted(
                issues,
                key=lambda item: (
                    0 if item.severity == "error" else 1,
                    item.node_id or "",
                    item.edge_index if item.edge_index is not None else -1,
                    item.code,
                ),
            ),
        )
