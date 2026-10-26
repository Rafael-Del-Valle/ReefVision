"""Persist workflow revisions and execute typed ReefVision node adapters."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, cast
from uuid import uuid4

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import (
    DatasetVersion,
    DatasetVersionItem,
    ImageAsset,
    Job,
    MaskAnnotation,
    ModelRegistration,
    PredictionProposal,
    Project,
    ProjectExchangePackage,
    VideoAsset,
    WorkflowArtifact,
    WorkflowGraphRecord,
    WorkflowNodeRun,
    WorkflowRun,
)
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.jobs.inference import process_inference_job
from reefvision.schemas.workflow_execution import (
    WorkflowArtifactResponse,
    WorkflowGraphRecordResponse,
    WorkflowGraphSaveRequest,
    WorkflowNodeRunResponse,
    WorkflowRunCreateRequest,
    WorkflowRunDetailResponse,
    WorkflowRunResponse,
)
from reefvision.schemas.workflow_graphs import WorkflowGraphRequest, WorkflowPlanStep
from reefvision.services.project_exchange import FORMAT_VERSION, ProjectExchangeService
from reefvision.services.workflow_classification import (
    materialize_workflow_classification_dataset,
    train_workflow_classifier,
)
from reefvision.services.workflow_consensus import build_detection_consensus
from reefvision.services.workflow_datasets import create_workflow_dataset_version
from reefvision.services.workflow_graphs import WorkflowGraphService
from reefvision.services.workflow_provenance import verify_workflow_artifact
from reefvision.services.workflow_runtime_adapters import (
    RUNTIME_ADAPTER_NODE_TYPES,
    execute_runtime_adapter,
)
from reefvision.services.workflow_training import (
    create_workflow_training_result,
    register_workflow_trained_model,
)
from reefvision.storage.datasets import canonical_json_sha256

EXECUTABLE_NODE_TYPES = {
    "project_source",
    "project_images",
    "dataset_version_source",
    "dataset_version_create",
    "registered_model_source",
    "project_video_source",
    "verified_masks_source",
    "detection_inference",
    "detection_consensus",
    "classification_dataset_materialize",
    "classification_training",
    "model_training",
    "register_trained_model",
    "project_exchange_export",
    *RUNTIME_ADAPTER_NODE_TYPES,
}


@dataclass(frozen=True, slots=True)
class WorkflowArtifactSpec:
    port_id: str
    data_type: str
    payload: dict[str, Any]


class WorkflowExecutionService:
    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings
        self.graphs = WorkflowGraphService(session)

    def _required_settings(self) -> Settings:
        if self.settings is None:
            raise ValidationError("Workflow execution requires application settings")
        return self.settings

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _graph_record(self, graph_record_id: str) -> WorkflowGraphRecord:
        record = self.session.get(WorkflowGraphRecord, graph_record_id)
        if record is None:
            raise NotFoundError("Workflow graph revision not found")
        return record

    def _run(self, run_id: str) -> WorkflowRun:
        run = self.session.get(WorkflowRun, run_id)
        if run is None:
            raise NotFoundError("Workflow run not found")
        return run

    def list_graphs(self, project_id: str) -> list[WorkflowGraphRecordResponse]:
        self._project(project_id)
        records = list(
            self.session.scalars(
                select(WorkflowGraphRecord)
                .where(WorkflowGraphRecord.project_id == project_id)
                .order_by(
                    WorkflowGraphRecord.graph_key,
                    WorkflowGraphRecord.revision.desc(),
                )
            )
        )
        return [WorkflowGraphRecordResponse.model_validate(record) for record in records]

    def save_graph(
        self,
        project_id: str,
        request: WorkflowGraphSaveRequest,
    ) -> WorkflowGraphRecordResponse:
        self._project(project_id)
        validation = self.graphs.validate(project_id, request.graph)
        if not validation.valid:
            messages = "; ".join(
                issue.message for issue in validation.issues if issue.severity == "error"
            )
            raise ValidationError(f"Cannot save invalid workflow graph: {messages}")

        graph_json = request.graph.model_dump(mode="json")
        checksum = canonical_json_sha256(graph_json)
        latest = self.session.scalar(
            select(WorkflowGraphRecord)
            .where(
                WorkflowGraphRecord.project_id == project_id,
                WorkflowGraphRecord.graph_key == request.graph.graph_id,
            )
            .order_by(WorkflowGraphRecord.revision.desc())
            .limit(1)
        )
        if latest is not None and latest.graph_sha256 == checksum:
            # Idempotent saves must not return a revision whose persisted
            # graph was changed after it was signed. Require a new reviewed
            # revision rather than silently blessing altered science.
            if canonical_json_sha256(latest.graph_json) != latest.graph_sha256:
                raise ConflictError("Workflow graph revision checksum failed")
            return WorkflowGraphRecordResponse.model_validate(latest)

        record = WorkflowGraphRecord(
            project_id=project_id,
            graph_key=request.graph.graph_id,
            name=request.graph.name,
            schema_version=request.graph.schema_version,
            revision=(latest.revision + 1 if latest is not None else 1),
            graph_json=graph_json,
            graph_sha256=checksum,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return WorkflowGraphRecordResponse.model_validate(record)

    def list_runs(self, project_id: str) -> list[WorkflowRunResponse]:
        self._project(project_id)
        runs = list(
            self.session.scalars(
                select(WorkflowRun)
                .where(WorkflowRun.project_id == project_id)
                .order_by(WorkflowRun.created_at.desc(), WorkflowRun.id)
            )
        )
        return [WorkflowRunResponse.model_validate(run) for run in runs]

    def get_run_detail(self, run_id: str) -> WorkflowRunDetailResponse:
        run = self._run(run_id)
        # Run-detail retrieval must enforce the same saved-graph lineage as
        # provenance export. Artifact checksums alone cannot establish which
        # workflow produced a scientific result after its graph is altered.
        graph = self.session.get(WorkflowGraphRecord, run.workflow_graph_record_id)
        if (
            graph is None
            or graph.project_id != run.project_id
            or graph.graph_sha256 != run.graph_sha256
            or not isinstance(graph.graph_json, dict)
            or canonical_json_sha256(graph.graph_json) != run.graph_sha256
        ):
            raise ConflictError("Workflow graph provenance checksum failed")
        nodes = list(
            self.session.scalars(
                select(WorkflowNodeRun)
                .where(WorkflowNodeRun.workflow_run_id == run.id)
                .order_by(WorkflowNodeRun.execution_order, WorkflowNodeRun.node_id)
            )
        )
        artifacts = list(
            self.session.scalars(
                select(WorkflowArtifact)
                .where(WorkflowArtifact.workflow_run_id == run.id)
                .order_by(WorkflowArtifact.created_at, WorkflowArtifact.id)
            )
        )
        # A run-detail response is a scientific-data read path. Do not return
        # altered persisted artifacts as if they were verified workflow output.
        for artifact in artifacts:
            verify_workflow_artifact(artifact, expected_run_id=run.id)
        return WorkflowRunDetailResponse(
            run=WorkflowRunResponse.model_validate(run),
            nodes=[WorkflowNodeRunResponse.model_validate(node) for node in nodes],
            artifacts=[WorkflowArtifactResponse.model_validate(item) for item in artifacts],
        )

    def queue_run(
        self,
        project_id: str,
        request: WorkflowRunCreateRequest,
    ) -> WorkflowRunResponse:
        self._project(project_id)
        record = self._graph_record(request.graph_record_id)
        if record.project_id != project_id:
            raise ValidationError("Workflow graph revision does not belong to this project")
        try:
            graph = WorkflowGraphRequest.model_validate(record.graph_json)
        except PydanticValidationError as exc:
            raise ValidationError("Saved workflow graph revision is invalid") from exc
        # A saved revision may have been altered since it was persisted. Reject
        # structurally valid but modified graphs before queueing a run whose
        # pinned provenance would otherwise fail only after dequeue.
        if canonical_json_sha256(graph.model_dump(mode="json")) != record.graph_sha256:
            raise ValidationError(
                "Workflow graph revision checksum no longer matches saved contents"
            )
        plan = self.graphs.plan(project_id, graph)
        if not plan.valid:
            raise ValidationError("Workflow graph is no longer valid")
        unsupported = [
            step.node_type
            for step in plan.steps
            if step.node_type not in EXECUTABLE_NODE_TYPES
            and step.node_type not in RUNTIME_ADAPTER_NODE_TYPES
        ]
        if unsupported:
            raise ValidationError(
                "Workflow contains nodes that are not executable yet: "
                + ", ".join(sorted(set(unsupported)))
            )

        run = WorkflowRun(
            project_id=project_id,
            workflow_graph_record_id=record.id,
            status="queued",
            graph_sha256=record.graph_sha256,
            input_json=dict(request.inputs),
            result_json={"stage": "queued", "completed_nodes": 0},
        )
        self.session.add(run)
        self.session.flush()
        for step in plan.steps:
            self.session.add(
                WorkflowNodeRun(
                    workflow_run_id=run.id,
                    node_id=step.node_id,
                    node_type=step.node_type,
                    execution_order=step.order,
                    status="pending",
                    parameters_json=dict(step.parameters),
                    input_artifact_ids_json=[],
                    output_artifact_ids_json=[],
                    result_json={},
                )
            )
        job = Job(
            project_id=project_id,
            job_type="workflow_run",
            status="queued",
            progress_current=0,
            progress_total=len(plan.steps),
            request_json={"workflow_run_id": run.id},
            result_json={"stage": "queued", "workflow_run_id": run.id},
        )
        self.session.add(job)
        self.session.flush()
        run.job_id = job.id
        self.session.commit()
        self.session.refresh(run)
        return WorkflowRunResponse.model_validate(run)

    def execute_node(
        self,
        *,
        project_id: str,
        run_id: str,
        node_run: WorkflowNodeRun,
        step: WorkflowPlanStep,
        inputs: dict[str, list[WorkflowArtifact]],
    ) -> list[WorkflowArtifactSpec]:
        if self.settings is None:
            raise ValidationError("Workflow execution requires application settings")
        if (
            step.node_type not in EXECUTABLE_NODE_TYPES
            and step.node_type not in RUNTIME_ADAPTER_NODE_TYPES
        ):
            raise ValidationError(f"Workflow node is not executable: {step.node_type}")
        handler = getattr(self, f"_execute_{step.node_type}", None)
        if handler is not None:
            return cast(
                list[WorkflowArtifactSpec],
                handler(
                    project_id=project_id,
                    run_id=run_id,
                    node_run=node_run,
                    parameters=step.parameters,
                    inputs=inputs,
                ),
            )
        if step.node_type in RUNTIME_ADAPTER_NODE_TYPES:
            runtime_parameters = {
                **step.parameters,
                "__workflow_run_id": run_id,
                "__workflow_node_run_id": node_run.id,
            }
            outputs = execute_runtime_adapter(
                step.node_type,
                session=self.session,
                settings=self.settings,
                project_id=project_id,
                parameters=runtime_parameters,
                inputs=inputs,
            )
            return [
                WorkflowArtifactSpec(
                    port_id=str(output["port_id"]),
                    data_type=str(output["data_type"]),
                    payload=dict(output["payload"]),
                )
                for output in outputs
            ]
        raise ValidationError(f"Workflow node is not executable: {step.node_type}")

    @staticmethod
    def _single_payload(
        inputs: dict[str, list[WorkflowArtifact]],
        port_id: str,
    ) -> dict[str, Any]:
        items = inputs.get(port_id, [])
        if len(items) != 1:
            raise ValidationError(f"Workflow input requires exactly one artifact: {port_id}")
        return dict(items[0].payload_json)

    @staticmethod
    def _optional_payload(
        inputs: dict[str, list[WorkflowArtifact]],
        port_id: str,
    ) -> dict[str, Any] | None:
        items = inputs.get(port_id, [])
        if len(items) > 1:
            raise ValidationError(f"Workflow input accepts at most one artifact: {port_id}")
        return dict(items[0].payload_json) if items else None

    def _execute_project_source(
        self,
        *,
        project_id: str,
        **_: object,
    ) -> list[WorkflowArtifactSpec]:
        project = self._project(project_id)
        return [
            WorkflowArtifactSpec(
                port_id="project",
                data_type="project_reference",
                payload={
                    "project_id": project.id,
                    "project_name": project.name,
                    "storage_root": project.storage_root,
                },
            )
        ]

    def _execute_project_images(
        self,
        *,
        project_id: str,
        parameters: dict[str, Any],
        inputs: dict[str, list[WorkflowArtifact]],
        **_: object,
    ) -> list[WorkflowArtifactSpec]:
        project_payload = self._single_payload(inputs, "project")
        if project_payload.get("project_id") != project_id:
            raise ValidationError("Project Images received a foreign project reference")
        statement = select(ImageAsset).where(ImageAsset.project_id == project_id)
        annotation_status = parameters.get("annotation_status")
        group_key = parameters.get("group_key")
        if annotation_status:
            statement = statement.where(ImageAsset.annotation_status == str(annotation_status))
        if group_key:
            statement = statement.where(ImageAsset.group_key == str(group_key))
        images = list(
            self.session.scalars(statement.order_by(ImageAsset.created_at, ImageAsset.id))
        )
        return [
            WorkflowArtifactSpec(
                port_id="images",
                data_type="image_collection",
                payload={
                    "project_id": project_id,
                    "image_ids": [image.id for image in images],
                    "image_sha256": {image.id: image.sha256 for image in images},
                    "count": len(images),
                },
            )
        ]

    def _execute_dataset_version_source(
        self,
        *,
        project_id: str,
        parameters: dict[str, Any],
        inputs: dict[str, list[WorkflowArtifact]],
        **_: object,
    ) -> list[WorkflowArtifactSpec]:
        project_payload = self._single_payload(inputs, "project")
        if project_payload.get("project_id") != project_id:
            raise ValidationError("Dataset source received a foreign project reference")
        version_id = str(parameters.get("dataset_version_id") or "")
        version = self.session.get(DatasetVersion, version_id)
        if version is None or version.project_id != project_id or version.status != "complete":
            raise ValidationError("Dataset version is not a complete version in this project")
        all_items = list(
            self.session.scalars(
                select(DatasetVersionItem)
                .where(DatasetVersionItem.dataset_version_id == version.id)
                .order_by(DatasetVersionItem.id)
            )
        )
        split_counts = dict(Counter(str(item.split) for item in all_items))
        split = parameters.get("split")
        items = [item for item in all_items if item.split == str(split)] if split else all_items
        image_ids = [item.image_id for item in items]
        return [
            WorkflowArtifactSpec(
                port_id="dataset",
                data_type="dataset_version",
                payload={
                    "project_id": project_id,
                    "dataset_version_id": version.id,
                    "manifest_sha256": version.manifest_sha256,
                    "version_number": version.version_number,
                    "split_method": version.resolved_split_method,
                    "split": split,
                    "split_counts": split_counts,
                    "image_count": version.image_count,
                    "annotation_count": version.annotation_count,
                    "mask_annotation_count": version.mask_annotation_count,
                },
            ),
            WorkflowArtifactSpec(
                port_id="images",
                data_type="image_collection",
                payload={
                    "project_id": project_id,
                    "image_ids": image_ids,
                    "count": len(image_ids),
                    "dataset_version_id": version.id,
                    "dataset_manifest_sha256": version.manifest_sha256,
                    "split": split,
                },
            ),
        ]

    def _execute_dataset_version_create(
        self,
        *,
        project_id: str,
        run_id: str,
        node_run: WorkflowNodeRun,
        parameters: dict[str, Any],
        inputs: dict[str, list[WorkflowArtifact]],
    ) -> list[WorkflowArtifactSpec]:
        project_payload = self._single_payload(inputs, "project")
        parent_payload = self._optional_payload(inputs, "parent_dataset")
        reviewed_payloads = [dict(artifact.payload_json) for artifact in inputs.get("reviewed", [])]
        result = create_workflow_dataset_version(
            self.session,
            self._required_settings(),
            project_id=project_id,
            run_id=run_id,
            node_run_id=node_run.id,
            parameters=parameters,
            project_payload=project_payload,
            parent_dataset_payload=parent_payload,
            reviewed_payloads=reviewed_payloads,
        )
        image_ids = [str(value) for value in result.get("image_ids", [])]
        return [
            WorkflowArtifactSpec(
                port_id="dataset",
                data_type="dataset_version",
                payload=result,
            ),
            WorkflowArtifactSpec(
                port_id="images",
                data_type="image_collection",
                payload={
                    "project_id": project_id,
                    "image_ids": image_ids,
                    "count": len(image_ids),
                    "dataset_version_id": result["dataset_version_id"],
                    "dataset_manifest_sha256": result["manifest_sha256"],
                },
            ),
        ]

    def _execute_registered_model_source(
        self,
        *,
        project_id: str,
        parameters: dict[str, Any],
        inputs: dict[str, list[WorkflowArtifact]],
        **_: object,
    ) -> list[WorkflowArtifactSpec]:
        project_payload = self._single_payload(inputs, "project")
        if project_payload.get("project_id") != project_id:
            raise ValidationError("Model source received a foreign project reference")
        model_id = str(parameters.get("model_id") or "")
        model = self.session.get(ModelRegistration, model_id)
        if model is None or model.project_id != project_id:
            raise ValidationError("Registered model does not belong to this project")
        return [
            WorkflowArtifactSpec(
                port_id="model",
                data_type="model_reference",
                payload={
                    "project_id": project_id,
                    "model_id": model.id,
                    "model_sha256": model.sha256,
                    "purpose": model.purpose,
                    "task": model.task,
                    "provider_name": model.provider_name,
                    "provider_version": model.provider_version,
                },
            )
        ]

    def _execute_detection_inference(
        self,
        *,
        project_id: str,
        run_id: str,
        node_run: WorkflowNodeRun,
        parameters: dict[str, Any],
        inputs: dict[str, list[WorkflowArtifact]],
    ) -> list[WorkflowArtifactSpec]:
        image_payload = self._single_payload(inputs, "images")
        model_payload = self._single_payload(inputs, "model")
        if image_payload.get("project_id") != project_id:
            raise ValidationError("Detection inference received a foreign image collection")
        image_ids = [str(image_id) for image_id in image_payload.get("image_ids", [])]
        if not image_ids:
            raise ValidationError("Detection inference requires at least one image")
        model_id = str(model_payload.get("model_id") or "")
        model = self.session.get(ModelRegistration, model_id)
        if model is None or model.project_id != project_id:
            raise ValidationError("Detection inference model does not belong to this project")
        if model.task != "detect":
            raise ValidationError("Detection Inference requires a model with task='detect'")

        child_job = Job(
            project_id=project_id,
            job_type="inference",
            status="queued",
            progress_current=0,
            progress_total=len(image_ids),
            request_json={
                "model_id": model.id,
                "image_ids": image_ids,
                "confidence_threshold": float(parameters.get("confidence", 0.25)),
                "iou_threshold": float(parameters.get("iou", 0.5)),
                "device": str(parameters.get("device", "auto")),
                "model_task": "detect",
                "created_by_workflow": True,
                "workflow_run_id": run_id,
                "workflow_node_run_id": node_run.id,
            },
            result_json={"stage": "queued", "created_by_workflow": True},
        )
        self.session.add(child_job)
        self.session.commit()
        child_job_id = child_job.id

        bind = self.session.get_bind()
        factory = sessionmaker(bind=bind, expire_on_commit=False)
        process_inference_job(self._required_settings(), factory, child_job_id)
        self.session.expire_all()
        completed_job = self.session.get(Job, child_job_id)
        if completed_job is None or completed_job.status != "succeeded":
            detail = completed_job.error_message if completed_job is not None else "job disappeared"
            raise ValidationError(f"Detection inference child job failed: {detail}")

        proposals = list(
            self.session.scalars(
                select(PredictionProposal)
                .where(PredictionProposal.inference_job_id == child_job_id)
                .order_by(
                    PredictionProposal.image_id,
                    PredictionProposal.created_at,
                    PredictionProposal.id,
                )
            )
        )
        detections = [
            {
                "proposal_id": proposal.id,
                "image_id": proposal.image_id,
                "label_class_id": proposal.label_class_id,
                "predicted_label": proposal.predicted_label,
                "predicted_index": proposal.predicted_index,
                "confidence": proposal.confidence,
                "geometry_kind": proposal.geometry_kind,
                "box": {
                    "x_min": proposal.x_min,
                    "y_min": proposal.y_min,
                    "x_max": proposal.x_max,
                    "y_max": proposal.y_max,
                },
                "provenance": dict(proposal.provenance_json or {}),
            }
            for proposal in proposals
        ]
        return [
            WorkflowArtifactSpec(
                port_id="proposals",
                data_type="detection_proposals",
                payload={
                    "schema_version": "detection-proposals-0001",
                    "project_id": project_id,
                    "source_id": model.id,
                    "source_kind": "registered_model",
                    "source_model_id": model.id,
                    "source_model_sha256": model.sha256,
                    "provider_name": model.provider_name,
                    "provider_version": model.provider_version,
                    "inference_job_id": child_job_id,
                    "image_ids": image_ids,
                    "proposal_ids": [proposal.id for proposal in proposals],
                    "count": len(proposals),
                    "detections": detections,
                },
            )
        ]

    def _execute_detection_consensus(
        self,
        *,
        project_id: str,
        parameters: dict[str, Any],
        inputs: dict[str, list[WorkflowArtifact]],
        **_: object,
    ) -> list[WorkflowArtifactSpec]:
        prediction_artifacts = inputs.get("predictions", [])
        if not prediction_artifacts:
            raise ValidationError("Detection Consensus requires prediction artifacts")
        sources: list[dict[str, Any]] = []
        for artifact in prediction_artifacts:
            payload = dict(artifact.payload_json)
            if payload.get("project_id") != project_id:
                raise ValidationError(
                    "Detection Consensus received predictions from another project"
                )
            payload.setdefault("source_id", artifact.id)
            sources.append(payload)
        result = build_detection_consensus(
            sources,
            required_votes=int(parameters.get("required_votes", 2)),
            iou_threshold=float(parameters.get("iou_threshold", 0.5)),
            confidence_threshold=float(parameters.get("confidence_threshold", 0.0)),
            class_aware=bool(parameters.get("class_aware", True)),
            box_strategy=str(parameters.get("box_strategy", "mean")),
        )
        common = {
            "schema_version": result["schema_version"],
            "project_id": project_id,
            "source_ids": result["source_ids"],
            "source_count": result["source_count"],
            "required_votes": result["required_votes"],
            "iou_threshold": result["iou_threshold"],
            "confidence_threshold": result["confidence_threshold"],
            "class_aware": result["class_aware"],
            "box_strategy": result["box_strategy"],
        }
        return [
            WorkflowArtifactSpec(
                port_id="consensus",
                data_type="detection_consensus",
                payload={
                    **common,
                    "count": result["consensus_count"],
                    "detections": result["consensus"],
                },
            ),
            WorkflowArtifactSpec(
                port_id="disagreements",
                data_type="detection_disagreements",
                payload={
                    **common,
                    "count": result["disagreement_count"],
                    "detections": result["disagreements"],
                },
            ),
        ]

    def _execute_classification_dataset_materialize(
        self,
        *,
        project_id: str,
        parameters: dict[str, Any],
        inputs: dict[str, list[WorkflowArtifact]],
        **_: object,
    ) -> list[WorkflowArtifactSpec]:
        dataset_payload = self._single_payload(inputs, "dataset")
        result = materialize_workflow_classification_dataset(
            self.session,
            self._required_settings(),
            project_id=project_id,
            dataset_payload=dataset_payload,
            parameters=parameters,
        )
        return [
            WorkflowArtifactSpec(
                port_id="classification_dataset",
                data_type="classification_dataset",
                payload=result,
            )
        ]

    def _execute_classification_training(
        self,
        *,
        project_id: str,
        run_id: str,
        node_run: WorkflowNodeRun,
        parameters: dict[str, Any],
        inputs: dict[str, list[WorkflowArtifact]],
    ) -> list[WorkflowArtifactSpec]:
        dataset_payload = self._single_payload(inputs, "classification_dataset")
        result = train_workflow_classifier(
            self.session,
            self._required_settings(),
            project_id=project_id,
            dataset_payload=dataset_payload,
            parameters=parameters,
            workflow_run_id=run_id,
            workflow_node_run_id=node_run.id,
        )
        return [
            WorkflowArtifactSpec(
                port_id="model",
                data_type="model_reference",
                payload=result,
            )
        ]

    def _execute_model_training(
        self,
        *,
        project_id: str,
        run_id: str,
        node_run: WorkflowNodeRun,
        parameters: dict[str, Any],
        inputs: dict[str, list[WorkflowArtifact]],
    ) -> list[WorkflowArtifactSpec]:
        dataset_payload = self._single_payload(inputs, "dataset")
        initial_model_payload = self._optional_payload(inputs, "initial_model")
        result = create_workflow_training_result(
            self.session,
            self._required_settings(),
            project_id=project_id,
            dataset_payload=dataset_payload,
            parameters=parameters,
            initial_model_payload=initial_model_payload,
            workflow_run_id=run_id,
            workflow_node_run_id=node_run.id,
        )
        return [
            WorkflowArtifactSpec(
                port_id="training",
                data_type="training_result",
                payload=result,
            )
        ]

    def _execute_register_trained_model(
        self,
        *,
        project_id: str,
        parameters: dict[str, Any],
        inputs: dict[str, list[WorkflowArtifact]],
        **_: object,
    ) -> list[WorkflowArtifactSpec]:
        training_payload = self._single_payload(inputs, "training")
        result = register_workflow_trained_model(
            self.session,
            self._required_settings(),
            project_id=project_id,
            training_payload=training_payload,
            parameters=parameters,
        )
        return [
            WorkflowArtifactSpec(
                port_id="model",
                data_type="model_reference",
                payload=result,
            )
        ]

    def _execute_project_video_source(
        self,
        *,
        project_id: str,
        parameters: dict[str, Any],
        inputs: dict[str, list[WorkflowArtifact]],
        **_: object,
    ) -> list[WorkflowArtifactSpec]:
        project_payload = self._single_payload(inputs, "project")
        if project_payload.get("project_id") != project_id:
            raise ValidationError("Video source received a foreign project reference")
        video_id = str(parameters.get("video_id") or "")
        video = self.session.get(VideoAsset, video_id)
        if video is None or video.project_id != project_id:
            raise ValidationError("Video does not belong to this project")
        return [
            WorkflowArtifactSpec(
                port_id="video",
                data_type="video_reference",
                payload={
                    "project_id": project_id,
                    "video_id": video.id,
                    "sha256": video.sha256,
                    "frame_count": video.frame_count,
                    "fps": video.fps,
                    "duration_seconds": video.duration_seconds,
                },
            )
        ]

    def _execute_verified_masks_source(
        self,
        *,
        project_id: str,
        parameters: dict[str, Any],
        inputs: dict[str, list[WorkflowArtifact]],
        **_: object,
    ) -> list[WorkflowArtifactSpec]:
        project_payload = self._single_payload(inputs, "project")
        if project_payload.get("project_id") != project_id:
            raise ValidationError("Mask source received a foreign project reference")
        statement = (
            select(MaskAnnotation)
            .join(ImageAsset, ImageAsset.id == MaskAnnotation.image_id)
            .where(
                ImageAsset.project_id == project_id,
                MaskAnnotation.deleted_at.is_(None),
                MaskAnnotation.status == "verified",
            )
        )
        label_class_ids = [str(item) for item in parameters.get("label_class_ids", [])]
        image_ids = [str(item) for item in parameters.get("image_ids", [])]
        if label_class_ids:
            statement = statement.where(MaskAnnotation.label_class_id.in_(label_class_ids))
        if image_ids:
            statement = statement.where(MaskAnnotation.image_id.in_(image_ids))
        masks = list(
            self.session.scalars(statement.order_by(MaskAnnotation.created_at, MaskAnnotation.id))
        )
        return [
            WorkflowArtifactSpec(
                port_id="masks",
                data_type="mask_annotations",
                payload={
                    "project_id": project_id,
                    "mask_annotation_ids": [mask.id for mask in masks],
                    "count": len(masks),
                },
            )
        ]

    def _execute_project_exchange_export(
        self,
        *,
        project_id: str,
        parameters: dict[str, Any],
        inputs: dict[str, list[WorkflowArtifact]],
        **_: object,
    ) -> list[WorkflowArtifactSpec]:
        project_payload = self._single_payload(inputs, "project")
        if project_payload.get("project_id") != project_id:
            raise ValidationError("Project export received a foreign project reference")
        project = self._project(project_id)
        package_id = str(uuid4())
        package = ProjectExchangePackage(
            id=package_id,
            project_id=project_id,
            job_id=None,
            direction="export",
            status="queued",
            format_version=FORMAT_VERSION,
            manifest_json={},
            manifest_sha256="",
            archive_path=f"{project.storage_root}/exchanges/{package_id}.reefvision.zip",
            options_json={
                "include_media": bool(parameters.get("include_media", False)),
                "include_model_weights": bool(parameters.get("include_model_weights", False)),
                "include_generated_artifacts": bool(
                    parameters.get("include_generated_artifacts", False)
                ),
                "created_by_workflow": True,
            },
        )
        self.session.add(package)
        self.session.commit()
        result = ProjectExchangeService(self.session, self._required_settings()).build_export(
            package.id
        )
        return [
            WorkflowArtifactSpec(
                port_id="package",
                data_type="project_exchange_package",
                payload={
                    "package_id": result.id,
                    "manifest_sha256": result.manifest_sha256,
                    "archive_path": result.archive_path,
                    "format_version": result.format_version,
                },
            )
        ]

    @staticmethod
    def artifact_checksum(payload: dict[str, Any]) -> str:
        return canonical_json_sha256(payload)

    def persist_artifact(
        self,
        *,
        run_id: str,
        node_run: WorkflowNodeRun,
        specification: WorkflowArtifactSpec,
    ) -> WorkflowArtifact:
        checksum = self.artifact_checksum(specification.payload)

        existing = list(
            self.session.scalars(
                select(WorkflowArtifact)
                .where(
                    WorkflowArtifact.workflow_run_id == run_id,
                    WorkflowArtifact.producer_node_run_id == node_run.id,
                    WorkflowArtifact.producer_port_id == specification.port_id,
                    WorkflowArtifact.data_type == specification.data_type,
                )
                .order_by(
                    WorkflowArtifact.created_at,
                    WorkflowArtifact.id,
                )
            )
        )

        for candidate in existing:
            candidate_actual = self.artifact_checksum(dict(candidate.payload_json or {}))

            if candidate_actual != candidate.payload_sha256:
                raise ConflictError("Existing workflow artifact failed checksum verification")

            if candidate.payload_sha256 == checksum:
                return candidate

        if existing:
            raise ConflictError(
                "Workflow node already persisted a different artifact for this output"
            )

        artifact = WorkflowArtifact(
            workflow_run_id=run_id,
            producer_node_run_id=node_run.id,
            producer_port_id=(specification.port_id),
            data_type=(specification.data_type),
            payload_json=dict(specification.payload),
            payload_sha256=checksum,
        )

        self.session.add(artifact)

        self.session.flush()

        return artifact

    def run_counts(self, run_id: str) -> dict[str, int]:
        total_nodes = (
            self.session.scalar(
                select(func.count(WorkflowNodeRun.id)).where(
                    WorkflowNodeRun.workflow_run_id == run_id
                )
            )
            or 0
        )
        artifacts = (
            self.session.scalar(
                select(func.count(WorkflowArtifact.id)).where(
                    WorkflowArtifact.workflow_run_id == run_id
                )
            )
            or 0
        )
        return {"node_count": int(total_nodes), "artifact_count": int(artifacts)}
