"""Project-scoped registration for isolated SAM 3 sidecar segmenters."""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import LabelClass, ModelRegistration, Project
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.ml.sam3_sidecar import _validated_endpoint
from reefvision.schemas.models import ModelRegistrationResponse
from reefvision.schemas.sam3_sidecar import Sam3SidecarRegistrationRequest
from reefvision.storage.datasets import canonical_json_bytes
from reefvision.storage.projects import resolve_managed_project_path


class Sam3SidecarModelService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def register(
        self,
        project_id: str,
        payload: Sam3SidecarRegistrationRequest,
    ) -> ModelRegistrationResponse:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        label_class = self.session.get(LabelClass, payload.label_class_id)
        if label_class is None or label_class.project_id != project_id:
            raise ValidationError("SAM 3 output class must belong to the selected project")
        if label_class.archived_at is not None or not label_class.is_active:
            raise ValidationError("SAM 3 output class must be active")
        endpoint = _validated_endpoint(payload.endpoint)
        descriptor = {
            "schema": "reefvision-sam3-sidecar-v1",
            "endpoint": endpoint,
            "concept_prompt": payload.concept_prompt,
            "output_label": payload.concept_prompt,
            "score_threshold": payload.score_threshold,
            "timeout_seconds": 120.0,
            "token_env": payload.token_env,
            "sam3_version": "sam3.1",
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
                ModelRegistration.display_name == payload.display_name,
            )
        )
        if name_conflict is not None:
            raise ConflictError("A model with this display name already exists")

        model_id = str(uuid4())
        relative_path = (
            f"{project.storage_root}/models/sam3-sidecar/{model_id}.sam3.json"
        )
        destination = resolve_managed_project_path(self.settings, relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex[:8]}.tmp")
        model = ModelRegistration(
            id=model_id,
            project_id=project_id,
            purpose="segmenter",
            display_name=payload.display_name,
            source_filename=Path(relative_path).name,
            managed_path=relative_path,
            sha256=checksum,
            file_size_bytes=len(descriptor_bytes),
            framework="sam3-sidecar",
            task="segment",
            provider_name="sam3_sidecar",
            provider_version="sam3.1",
            class_map_json={
                "labels": [payload.concept_prompt],
                "mapping": {payload.concept_prompt: label_class.id},
            },
            input_size_json=None,
            metadata_json={
                "registration_kind": "localhost_sidecar",
                "concept_prompt": payload.concept_prompt,
                "label_class_id": label_class.id,
                "sidecar_endpoint": endpoint,
                "sidecar_token_env": payload.token_env,
                "isolated_runtime": True,
                "proposal_geometry": "managed_raster_mask",
                "checkpoint_access_managed_by_sidecar": True,
            },
            notes=payload.notes,
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
                "SAM 3 sidecar registration conflicts with an existing model"
            ) from exc
        except Exception:
            self.session.rollback()
            destination.unlink(missing_ok=True)
            raise
        finally:
            temporary.unlink(missing_ok=True)
        return ModelRegistrationResponse.model_validate(model)
