"""Workflow persistence, immutable revisions, and queued executions."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    Job,
    Project,
    Workflow,
    WorkflowArtifact,
    WorkflowRevision,
    WorkflowRun,
)
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.jobs import JobResponse
from reefvision.schemas.workflows import (
    WorkflowArtifactResponse,
    WorkflowCreateRequest,
    WorkflowDetailResponse,
    WorkflowResponse,
    WorkflowRevisionCreateRequest,
    WorkflowRevisionResponse,
    WorkflowRunCreateRequest,
    WorkflowRunCreateResponse,
    WorkflowRunResponse,
    WorkflowValidationRequest,
    WorkflowValidationResponse,
)
from reefvision.services.workflows import (
    COMPATIBLE_SOURCE_TYPES,
    NODE_DEFINITIONS,
    WorkflowService,
    _NodeDefinition,
)


NODE_DEFINITIONS.update(
    {
        "depth_estimation": _NodeDefinition(
            display_name="Depth estimation",
            inputs={"images": ("images", True)},
            outputs={"depth_maps": "depth_maps"},
        ),
        "embedding_generation": _NodeDefinition(
            display_name="Image embedding generation",
            inputs={"images": ("images", True)},
            outputs={"embeddings": "embeddings"},
        ),
        "filter": _NodeDefinition(
            display_name="Artifact filter",
            inputs={"artifact": ("artifact", True)},
            outputs={"artifact": "artifact"},
        ),
    }
)
COMPATIBLE_SOURCE_TYPES.setdefault("artifact", set()).update(
    {"images", "video", "depth_maps", "embeddings"}
)
COMPATIBLE_SOURCE_TYPES.setdefault("predictions", set()).add("embeddings")


class PersistentWorkflowService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.validator = WorkflowService(session)

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _workflow(self, workflow_id: str) -> Workflow:
        workflow = self.session.get(Workflow, workflow_id)
        if workflow is None:
            raise NotFoundError("Workflow not found")
        return workflow

    def _revision(self, revision_id: str) -> WorkflowRevision:
        revision = self.session.get(WorkflowRevision, revision_id)
        if revision is None:
            raise NotFoundError("Workflow revision not found")
        return revision

    def _current_revision(self, workflow: Workflow) -> WorkflowRevision:
        revision = self.session.scalar(
            select(WorkflowRevision).where(
                WorkflowRevision.workflow_id == workflow.id,
                WorkflowRevision.revision_number == workflow.current_revision_number,
            )
        )
        if revision is None:
            raise NotFoundError("The workflow's current revision is missing")
        return revision

    @staticmethod
    def _validation_payload(response: WorkflowValidationResponse) -> dict[str, Any]:
        return response.model_dump(mode="json")

    def list_workflows(self, project_id: str) -> list[WorkflowResponse]:
        self._project(project_id)
        workflows = list(
            self.session.scalars(
                select(Workflow)
                .where(Workflow.project_id == project_id)
                .order_by(Workflow.updated_at.desc(), Workflow.id)
            )
        )
        return [WorkflowResponse.model_validate(item) for item in workflows]

    def create(
        self,
        project_id: str,
        request: WorkflowCreateRequest,
    ) -> WorkflowDetailResponse:
        self._project(project_id)
        validation = self.validator.validate(project_id, request.workflow)
        if not validation.valid:
            raise ValidationError("Only structurally valid workflows may be persisted")
        workflow = Workflow(
            project_id=project_id,
            name=request.name.strip(),
            description=request.description.strip() if request.description else None,
            status=request.status,
            current_revision_number=1,
            created_by=request.creator,
        )
        self.session.add(workflow)
        self.session.flush()
        revision = WorkflowRevision(
            workflow_id=workflow.id,
            revision_number=1,
            workflow_json=request.workflow.model_dump(mode="json"),
            workflow_checksum=validation.workflow_checksum,
            validation_json=self._validation_payload(validation),
            created_by=request.creator,
        )
        self.session.add(revision)
        self.session.commit()
        self.session.refresh(workflow)
        self.session.refresh(revision)
        return WorkflowDetailResponse(
            workflow=WorkflowResponse.model_validate(workflow),
            current_revision=WorkflowRevisionResponse.model_validate(revision),
            validation=validation,
        )

    def get(self, workflow_id: str) -> WorkflowDetailResponse:
        workflow = self._workflow(workflow_id)
        revision = self._current_revision(workflow)
        validation = WorkflowValidationResponse.model_validate(revision.validation_json)
        return WorkflowDetailResponse(
            workflow=WorkflowResponse.model_validate(workflow),
            current_revision=WorkflowRevisionResponse.model_validate(revision),
            validation=validation,
        )

    def create_revision(
        self,
        workflow_id: str,
        request: WorkflowRevisionCreateRequest,
    ) -> WorkflowDetailResponse:
        workflow = self._workflow(workflow_id)
        validation = self.validator.validate(workflow.project_id, request.workflow)
        if not validation.valid:
            raise ValidationError("Only structurally valid workflow revisions may be saved")
        next_number = int(
            self.session.scalar(
                select(func.coalesce(func.max(WorkflowRevision.revision_number), 0)).where(
                    WorkflowRevision.workflow_id == workflow.id
                )
            )
            or 0
        ) + 1
        revision = WorkflowRevision(
            workflow_id=workflow.id,
            revision_number=next_number,
            workflow_json=request.workflow.model_dump(mode="json"),
            workflow_checksum=validation.workflow_checksum,
            validation_json=self._validation_payload(validation),
            created_by=request.creator,
        )
        workflow.name = request.workflow.name
        workflow.current_revision_number = next_number
        self.session.add(revision)
        self.session.commit()
        self.session.refresh(workflow)
        self.session.refresh(revision)
        return WorkflowDetailResponse(
            workflow=WorkflowResponse.model_validate(workflow),
            current_revision=WorkflowRevisionResponse.model_validate(revision),
            validation=validation,
        )

    def list_revisions(self, workflow_id: str) -> list[WorkflowRevisionResponse]:
        self._workflow(workflow_id)
        revisions = list(
            self.session.scalars(
                select(WorkflowRevision)
                .where(WorkflowRevision.workflow_id == workflow_id)
                .order_by(WorkflowRevision.revision_number.desc())
            )
        )
        return [WorkflowRevisionResponse.model_validate(item) for item in revisions]

    def queue_run(
        self,
        workflow_id: str,
        request: WorkflowRunCreateRequest,
    ) -> WorkflowRunCreateResponse:
        workflow = self._workflow(workflow_id)
        revision = (
            self._revision(request.workflow_revision_id)
            if request.workflow_revision_id
            else self._current_revision(workflow)
        )
        if revision.workflow_id != workflow.id:
            raise ValidationError("Workflow revision does not belong to this workflow")
        validation = WorkflowValidationResponse.model_validate(revision.validation_json)
        if not validation.valid:
            raise ValidationError("Invalid workflow revisions cannot be executed")
        run = WorkflowRun(
            workflow_id=workflow.id,
            workflow_revision_id=revision.id,
            project_id=workflow.project_id,
            status="queued",
            stage="queued",
            input_json=request.inputs,
            result_json={"use_cache": request.use_cache},
            node_state_json={
                node_id: {"status": "queued"}
                for node_id in validation.topological_order
            },
        )
        self.session.add(run)
        self.session.flush()
        job = Job(
            project_id=workflow.project_id,
            job_type="workflow_run",
            status="queued",
            progress_total=max(len(validation.topological_order), 1),
            request_json={
                "workflow_run_id": run.id,
                "workflow_revision_id": revision.id,
                "use_cache": request.use_cache,
            },
        )
        self.session.add(job)
        self.session.flush()
        run.job_id = job.id
        self.session.commit()
        self.session.refresh(run)
        self.session.refresh(job)
        return WorkflowRunCreateResponse(
            run=WorkflowRunResponse.model_validate(run),
            job=JobResponse.model_validate(job),
        )

    def list_runs(self, workflow_id: str) -> list[WorkflowRunResponse]:
        self._workflow(workflow_id)
        runs = list(
            self.session.scalars(
                select(WorkflowRun)
                .where(WorkflowRun.workflow_id == workflow_id)
                .order_by(WorkflowRun.created_at.desc(), WorkflowRun.id)
            )
        )
        return [WorkflowRunResponse.model_validate(item) for item in runs]

    def get_run(self, run_id: str) -> WorkflowRunResponse:
        run = self.session.get(WorkflowRun, run_id)
        if run is None:
            raise NotFoundError("Workflow run not found")
        return WorkflowRunResponse.model_validate(run)

    def artifacts(self, run_id: str) -> list[WorkflowArtifactResponse]:
        if self.session.get(WorkflowRun, run_id) is None:
            raise NotFoundError("Workflow run not found")
        artifacts = list(
            self.session.scalars(
                select(WorkflowArtifact)
                .where(WorkflowArtifact.workflow_run_id == run_id)
                .order_by(
                    WorkflowArtifact.created_at,
                    WorkflowArtifact.node_id,
                    WorkflowArtifact.port_name,
                )
            )
        )
        return [WorkflowArtifactResponse.model_validate(item) for item in artifacts]
