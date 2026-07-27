"""Project-scoped inference jobs for bundled open-vocabulary catalog models."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, FiniteFloat, field_validator
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import Job, ModelRegistration
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.repositories.images import ImageRepository
from reefvision.repositories.models import ModelRepository
from reefvision.repositories.projects import ProjectRepository
from reefvision.schemas.jobs import JobResponse
from reefvision.services.bundled_transformers_models import bundled_transformers_model_record
from reefvision.services.model_catalog import ModelCatalogService
from reefvision.storage.projects import resolve_managed_project_path

TRANSFORMERS_CATALOG_IDS = frozenset(
    {
        "transformers/florence2/base",
        "transformers/florence2/large",
        "transformers/grounding_dino/tiny",
        "transformers/grounding_dino/base",
        "transformers/owlv2/base",
        "transformers/owlv2/large",
    }
)
_POINTER_FORMAT = "reefvision_transformers_model_pointer_v1"


class CatalogInferenceJobCreateRequest(BaseModel):
    catalog_id: str = Field(min_length=1, max_length=300)
    image_ids: list[str] = Field(min_length=1, max_length=10000)
    text_prompt: str = Field(min_length=1, max_length=2000)
    confidence_threshold: FiniteFloat | None = Field(default=None, ge=0, le=1)
    iou_threshold: FiniteFloat | None = Field(default=None, ge=0, le=1)
    device: str = Field(default="auto", min_length=1, max_length=20)

    @field_validator("catalog_id", "text_prompt", "device")
    @classmethod
    def strip_strings(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value must not be blank")
        return stripped

    @field_validator("image_ids")
    @classmethod
    def unique_image_ids(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("Image ids must not be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Image ids must be unique")
        return normalized


class CatalogInferenceService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.projects = ProjectRepository(session)
        self.images = ImageRepository(session)
        self.models = ModelRepository(session)
        self.catalog = ModelCatalogService(session, settings)

    def _pointer_relative_path(
        self,
        project_storage_root: str,
        catalog_id: str,
    ) -> str:
        safe_name = catalog_id.replace("/", "--").replace("_", "-")
        return f"{project_storage_root}/models/catalog/{safe_name}.transformers.json"

    def _write_pointer(
        self,
        *,
        relative_path: str,
        catalog_id: str,
        provider_id: str,
        record: dict[str, Any],
    ) -> Path:
        path = resolve_managed_project_path(self.settings, relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        model_path = Path(record["path"]).resolve()
        payload = {
            "format": _POINTER_FORMAT,
            "catalog_id": catalog_id,
            "provider_id": provider_id,
            "model_path": str(model_path),
            "repo_id": record.get("repo_id"),
            "resolved_revision": record.get("resolved_revision"),
            "snapshot_sha256": record.get("snapshot_sha256"),
            "file_count": record.get("file_count"),
            "total_size_bytes": record.get("total_size_bytes"),
        }
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
        return path

    def _catalog_registration(
        self,
        project_id: str,
        catalog_id: str,
    ) -> ModelRegistration | None:
        for model in self.models.list_for_project(project_id, purpose="detector"):
            metadata = dict(model.metadata_json or {})
            if (
                metadata.get("registered_from") == "bundled_catalog"
                and metadata.get("source_catalog_model_id") == catalog_id
            ):
                return model
        return None

    def _registered_model(
        self,
        *,
        project_id: str,
        catalog_id: str,
        provider_id: str,
        provider_version: str,
        display_name: str,
        project_storage_root: str,
        record: dict[str, Any],
    ) -> ModelRegistration:
        checksum = str(record.get("snapshot_sha256") or "")
        if len(checksum) != 64:
            raise ValidationError("Bundled catalog model is missing its verified snapshot checksum")
        existing = self.models.find_by_checksum(project_id, checksum)
        if existing is not None:
            if existing.provider_name != provider_id or existing.task != "detect":
                raise ValidationError(
                    "A different project model already uses this bundled snapshot checksum"
                )
            return existing

        relative_path = self._pointer_relative_path(project_storage_root, catalog_id)
        pointer = self._write_pointer(
            relative_path=relative_path,
            catalog_id=catalog_id,
            provider_id=provider_id,
            record=record,
        )
        catalog_registration = self._catalog_registration(project_id, catalog_id)
        metadata = {
            "registered_from": "bundled_catalog",
            "source_catalog_model_id": catalog_id,
            "provider_pack_id": "transformers-vision",
            "prompt_required": True,
            "proposal_geometry": "bounding_box",
            "snapshot_sha256": checksum,
            "resolved_revision": record.get("resolved_revision"),
            "repo_id": record.get("repo_id"),
            "pointer_format": _POINTER_FORMAT,
        }
        if catalog_registration is not None:
            catalog_registration.source_filename = pointer.name
            catalog_registration.managed_path = relative_path
            catalog_registration.sha256 = checksum
            catalog_registration.file_size_bytes = int(record.get("total_size_bytes") or 0)
            catalog_registration.framework = "transformers"
            catalog_registration.task = "detect"
            catalog_registration.provider_name = provider_id
            catalog_registration.provider_version = provider_version
            catalog_registration.class_map_json = {"labels": [], "mapping": {}}
            catalog_registration.input_size_json = None
            catalog_registration.metadata_json = metadata
            catalog_registration.notes = (
                "Automatically refreshed from ReefVision's verified bundled model pack."
            )
            return catalog_registration

        model = ModelRegistration(
            id=str(uuid4()),
            project_id=project_id,
            purpose="detector",
            display_name=f"{display_name} (Bundled)",
            source_filename=pointer.name,
            managed_path=relative_path,
            sha256=checksum,
            file_size_bytes=int(record.get("total_size_bytes") or 0),
            framework="transformers",
            task="detect",
            provider_name=provider_id,
            provider_version=provider_version,
            class_map_json={"labels": [], "mapping": {}},
            input_size_json=None,
            metadata_json=metadata,
            notes=("Automatically registered from ReefVision's verified bundled model pack."),
        )
        self.models.add(model)
        return model

    def create_job(
        self,
        project_id: str,
        payload: CatalogInferenceJobCreateRequest,
    ) -> JobResponse:
        project = self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project not found")
        if payload.catalog_id not in TRANSFORMERS_CATALOG_IDS:
            raise ValidationError(
                "The selected catalog model does not support text-prompt inference"
            )

        entry = self.catalog.get_project_catalog_item(project_id, payload.catalog_id)
        if entry.installation_state not in {"Ready", "Available"}:
            raise ValidationError(
                entry.installation_reason or "The selected catalog model is not ready"
            )
        provider_id = str(entry.provider_id or entry.provider).strip().casefold().replace("-", "_")
        if provider_id not in {"florence2", "grounding_dino", "owlv2"}:
            raise ValidationError("The selected catalog model has an unsupported provider")

        record = bundled_transformers_model_record(self.settings, payload.catalog_id)
        if record is None:
            raise ValidationError(
                "The bundled model snapshot is missing or failed startup verification; "
                "repair the installation"
            )

        images = self.images.list_by_ids(payload.image_ids)
        if len(images) != len(payload.image_ids):
            raise ValidationError("One or more requested images do not exist")
        if any(image.project_id != project_id for image in images):
            raise ValidationError("Inference images must belong to the selected project")

        model = self._registered_model(
            project_id=project_id,
            catalog_id=payload.catalog_id,
            provider_id=provider_id,
            provider_version=str(entry.provider_version or "1.0"),
            display_name=entry.display_name,
            project_storage_root=project.storage_root,
            record=record,
        )
        job = Job(
            project_id=project_id,
            job_type="inference",
            status="queued",
            progress_total=len(images),
            request_json={
                "model_id": model.id,
                "model_task": "detect",
                "catalog_id": payload.catalog_id,
                "image_ids": [image.id for image in images],
                "text_prompt": payload.text_prompt,
                "device": payload.device,
                "confidence_threshold": (
                    payload.confidence_threshold
                    if payload.confidence_threshold is not None
                    else self.settings.inference_default_confidence
                ),
                "iou_threshold": (
                    payload.iou_threshold
                    if payload.iou_threshold is not None
                    else self.settings.inference_default_iou
                ),
            },
            resource_requirements_json={
                "provider_id": provider_id,
                "device": payload.device,
                "gpu_optional": payload.device == "auto",
            },
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return JobResponse.model_validate(job)
