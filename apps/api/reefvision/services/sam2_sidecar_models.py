"""Register and inspect localhost SAM 2 sidecars."""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ModelRegistration, Project
from reefvision.domain.errors import ConflictError, NotFoundError
from reefvision.ml.sam2_sidecar import _validated_endpoint, check_sam2_sidecar_health
from reefvision.schemas.models import ModelRegistrationResponse
from reefvision.schemas.sam2_sidecar import (
    Sam2SidecarHealthRequest,
    Sam2SidecarHealthResponse,
    Sam2SidecarRegistrationRequest,
)
from reefvision.storage.datasets import canonical_json_bytes
from reefvision.storage.projects import resolve_managed_project_path


class Sam2SidecarModelService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def health(
        self,
        request: Sam2SidecarHealthRequest,
    ) -> Sam2SidecarHealthResponse:
        return Sam2SidecarHealthResponse.model_validate(
            check_sam2_sidecar_health(
                request.endpoint,
                token_env=request.token_env,
                timeout_seconds=request.timeout_seconds,
            )
        )

    def register(
        self,
        project_id: str,
        request: Sam2SidecarRegistrationRequest,
    ) -> ModelRegistrationResponse:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        endpoint = _validated_endpoint(request.endpoint)
        descriptor = {
            "schema": "reefvision-sam2-sidecar-v1",
            "endpoint": endpoint,
            "token_env": request.token_env,
            "timeout_seconds": request.timeout_seconds,
            "sam2_version": "sam2-sidecar",
        }
        descriptor_bytes = canonical_json_bytes(descriptor)
        checksum = hashlib.sha256(descriptor_bytes).hexdigest()
        existing = self.session.scalar(
            select(ModelRegistration).where(
                ModelRegistration.project_id == project_id,
                ModelRegistration.sha256 == checksum,
            )
        )
        if existing is not None:
            return ModelRegistrationResponse.model_validate(existing)
        name_conflict = self.session.scalar(
            select(ModelRegistration.id).where(
                ModelRegistration.project_id == project_id,
                ModelRegistration.display_name == request.display_name,
            )
        )
        if name_conflict is not None:
            raise ConflictError("A model with this display name already exists")

        model_id = str(uuid4())
        relative_path = f"{project.storage_root}/models/sam2-sidecar/{model_id}.sam2.json"
        destination = resolve_managed_project_path(self.settings, relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex[:8]}.tmp")
        model = ModelRegistration(
            id=model_id,
            project_id=project_id,
            purpose="assist",
            display_name=request.display_name,
            source_filename=Path(relative_path).name,
            managed_path=relative_path,
            sha256=checksum,
            file_size_bytes=len(descriptor_bytes),
            framework="sam2-sidecar",
            task="assist_segmentation",
            provider_name="sam2_sidecar",
            provider_version="1",
            class_map_json={},
            input_size_json=None,
            metadata_json={
                "registration_kind": "sam2_sidecar",
                "endpoint": endpoint,
                "token_env": request.token_env,
                "timeout_seconds": request.timeout_seconds,
                "remote_host_policy": "localhost_only",
                "checkpoint_location": "sidecar_process",
                "isolated_runtime": True,
                "checkpoint_access_managed_by_sidecar": True,
                "proposal_geometry": "managed_raster_mask",
            },
            notes=request.notes,
        )
        try:
            temporary.write_bytes(descriptor_bytes)
            temporary.replace(destination)
            self.session.add(model)
            self.session.commit()
            self.session.refresh(model)
        except IntegrityError as exc:
            self.session.rollback()
            destination.unlink(missing_ok=True)
            raise ConflictError(
                "SAM 2 sidecar registration conflicts with an existing model"
            ) from exc
        except Exception:
            self.session.rollback()
            destination.unlink(missing_ok=True)
            raise
        finally:
            temporary.unlink(missing_ok=True)
        return ModelRegistrationResponse.model_validate(model)
