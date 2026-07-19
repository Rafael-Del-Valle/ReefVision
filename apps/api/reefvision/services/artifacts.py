"""Create, inspect, and trace unified ReefVision artifact provenance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from reefvision import __version__
from reefvision.config import Settings
from reefvision.db.models import (
    ArtifactRecord,
    DatasetVersion,
    ModelRegistration,
    Project,
)
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.artifacts import (
    ArtifactCreateRequest,
    ArtifactLineageResponse,
    ArtifactResponse,
)
from reefvision.storage.projects import resolve_managed_project_path


def _canonical_checksum(payload: dict[str, Any]) -> str:
    content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _file_checksum(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(block)
            digest.update(block)
    return digest.hexdigest(), size


class ArtifactService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def get(self, artifact_id: str) -> ArtifactRecord:
        artifact = self.session.get(ArtifactRecord, artifact_id)
        if artifact is None:
            raise NotFoundError("Artifact not found")
        return artifact

    def list_for_project(
        self,
        project_id: str,
        *,
        artifact_type: str | None = None,
        review_status: str | None = None,
        limit: int = 200,
    ) -> list[ArtifactResponse]:
        if self.session.get(Project, project_id) is None:
            raise NotFoundError("Project not found")
        statement = select(ArtifactRecord).where(ArtifactRecord.project_id == project_id)
        if artifact_type:
            statement = statement.where(ArtifactRecord.artifact_type == artifact_type)
        if review_status:
            statement = statement.where(ArtifactRecord.review_status == review_status)
        statement = statement.order_by(ArtifactRecord.created_at.desc(), ArtifactRecord.id).limit(
            min(max(limit, 1), 1000)
        )
        return [ArtifactResponse.model_validate(item) for item in self.session.scalars(statement)]

    def create(self, project_id: str, request: ArtifactCreateRequest) -> ArtifactResponse:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        self._validate_references(project_id, request)
        managed_path = request.managed_path
        checksum = request.checksum
        size_bytes: int | None = None
        if managed_path is not None:
            path = resolve_managed_project_path(self.settings, managed_path)
            if not path.is_file():
                raise ValidationError("Artifact managed_path must reference an existing file")
            observed_checksum, size_bytes = _file_checksum(path)
            if checksum is not None and checksum != observed_checksum:
                raise ValidationError("Artifact checksum does not match managed content")
            checksum = observed_checksum
        else:
            checksum = checksum or _canonical_checksum(request.payload)
        metadata = dict(request.metadata)
        if request.payload:
            metadata["payload"] = request.payload
        artifact = ArtifactRecord(
            project_id=project_id,
            artifact_type=request.artifact_type,
            created_by=request.created_by,
            reefvision_version=__version__,
            source_kind=request.source_kind,
            source_id=request.source_id,
            source_checksum=request.source_checksum,
            source_annotation_revision=request.source_annotation_revision,
            dataset_version_id=request.dataset_version_id,
            dataset_version_checksum=request.dataset_version_checksum,
            model_id=request.model_id,
            model_checksum=request.model_checksum,
            provider_id=request.provider_id,
            provider_version=request.provider_version,
            parameters_json=request.parameters,
            postprocessing_json=request.postprocessing,
            review_status=request.review_status,
            parent_artifact_id=request.parent_artifact_id,
            supersedes_artifact_id=request.supersedes_artifact_id,
            managed_path=managed_path,
            checksum=checksum,
            size_bytes=size_bytes,
            metadata_json=metadata,
        )
        self.session.add(artifact)
        self.session.commit()
        self.session.refresh(artifact)
        return ArtifactResponse.model_validate(artifact)

    def update_review_status(
        self,
        artifact_id: str,
        review_status: str,
    ) -> ArtifactResponse:
        normalized = review_status.strip().casefold()
        if normalized not in {"unreviewed", "accepted", "rejected", "superseded"}:
            raise ValidationError("Unknown artifact review status")
        artifact = self.get(artifact_id)
        artifact.review_status = normalized
        self.session.commit()
        self.session.refresh(artifact)
        return ArtifactResponse.model_validate(artifact)

    def lineage(self, artifact_id: str) -> ArtifactLineageResponse:
        artifact = self.get(artifact_id)
        ancestors: list[ArtifactRecord] = []
        seen: set[str] = {artifact.id}
        current = artifact
        while current.parent_artifact_id is not None:
            parent = self.session.get(ArtifactRecord, current.parent_artifact_id)
            if parent is None or parent.id in seen:
                break
            ancestors.append(parent)
            seen.add(parent.id)
            current = parent

        project_artifacts = list(
            self.session.scalars(
                select(ArtifactRecord).where(ArtifactRecord.project_id == artifact.project_id)
            )
        )
        descendants: list[ArtifactRecord] = []
        frontier = {artifact.id}
        while frontier:
            next_frontier = {
                item.id
                for item in project_artifacts
                if item.parent_artifact_id in frontier and item.id not in seen
            }
            descendants.extend(item for item in project_artifacts if item.id in next_frontier)
            seen.update(next_frontier)
            frontier = next_frontier
        superseded_by = list(
            self.session.scalars(
                select(ArtifactRecord)
                .where(
                    ArtifactRecord.project_id == artifact.project_id,
                    or_(
                        ArtifactRecord.supersedes_artifact_id == artifact.id,
                        ArtifactRecord.parent_artifact_id == artifact.id,
                    ),
                )
                .order_by(ArtifactRecord.created_at, ArtifactRecord.id)
            )
        )
        return ArtifactLineageResponse(
            artifact=ArtifactResponse.model_validate(artifact),
            ancestors=[ArtifactResponse.model_validate(item) for item in ancestors],
            descendants=[ArtifactResponse.model_validate(item) for item in descendants],
            superseded_by=[ArtifactResponse.model_validate(item) for item in superseded_by],
        )

    def _validate_references(self, project_id: str, request: ArtifactCreateRequest) -> None:
        if request.dataset_version_id is not None:
            version = self.session.get(DatasetVersion, request.dataset_version_id)
            if version is None or version.project_id != project_id:
                raise ValidationError("Dataset version does not belong to the artifact project")
        if request.model_id is not None:
            model = self.session.get(ModelRegistration, request.model_id)
            if model is None or model.project_id != project_id:
                raise ValidationError("Model does not belong to the artifact project")
        for reference_name, reference_id in (
            ("parent", request.parent_artifact_id),
            ("superseded", request.supersedes_artifact_id),
        ):
            if reference_id is None:
                continue
            artifact = self.session.get(ArtifactRecord, reference_id)
            if artifact is None or artifact.project_id != project_id:
                raise ValidationError(
                    f"{reference_name.title()} artifact does not belong to this project"
                )
