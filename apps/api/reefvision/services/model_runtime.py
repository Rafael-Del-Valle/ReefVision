"""Preview, freeze and verify explicit model/runtime selections for local inference."""

import re
from datetime import UTC
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ModelRegistration, ModelRuntimeSelection, Project
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.ml.reviewed_runtime import resolve_reviewed_runtime
from reefvision.schemas.model_runtime import (
    ExecutionSettings,
    RuntimeConfirmation,
    RuntimeDraft,
    RuntimePreview,
    RuntimeReceipt,
    RuntimeSelectionResponse,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.models import hash_model_file
from reefvision.storage.projects import resolve_managed_project_path


def reviewed_settings(
    settings: Settings, draft: RuntimeDraft, applied: set[str]
) -> ExecutionSettings:
    if any(
        key in draft.model_fields_set and getattr(draft, key) is not None and key not in applied
        for key in ("confidence_threshold", "iou_threshold")
    ):
        raise ValidationError(
            "This model does not apply the requested threshold to image inference"
        )
    values = {
        "confidence_threshold": draft.confidence_threshold
        if draft.confidence_threshold is not None
        else settings.inference_default_confidence,
        "iou_threshold": draft.iou_threshold
        if draft.iou_threshold is not None
        else settings.inference_default_iou,
    }
    device = draft.device
    seen: set[str] = set()
    for phrase in re.split(r"[,;\n]", draft.prompt.casefold()) if draft.prompt.strip() else []:
        parts = re.fullmatch(r"\s*(confidence|iou|device)\s*(?:=|:|\s)\s*([\w.+-]+)\s*", phrase)
        if not parts or parts[1] in seen:
            raise ValidationError(
                "Use each setting once, for example confidence 0.4, iou 0.5, device cpu"
            )
        name, value = parts.groups()
        seen.add(name)
        if name == "device":
            if value not in ("cpu", "cuda"):
                raise ValidationError("Choose CPU or CUDA explicitly")
            device = "cpu" if value == "cpu" else "cuda"
        else:
            if name + "_threshold" not in applied:
                raise ValidationError(f"This model does not apply {name} to image inference")
            try:
                number = float(value)
            except ValueError as exc:
                raise ValidationError(
                    "Confidence and IoU must be probabilities between zero and one"
                ) from exc
            if not 0 <= number <= 1:
                raise ValidationError(
                    "Confidence and IoU must be probabilities between zero and one"
                )
            values[name + "_threshold"] = number
    return ExecutionSettings(
        device=device,
        confidence_threshold=values["confidence_threshold"],
        iou_threshold=values["iou_threshold"],
    )


def verify_checkpoint(
    settings: Settings, model: ModelRegistration, digest: str, length: int
) -> None:
    path = resolve_managed_project_path(settings, model.managed_path)
    try:
        actual = hash_model_file(path)
    except OSError as exc:
        raise ConflictError("The reviewed local checkpoint is missing or unreadable") from exc
    if actual != (digest, length) or actual != (model.sha256, model.file_size_bytes):
        raise ConflictError("The checkpoint bytes differ from the reviewed registration")


def _response(row: ModelRuntimeSelection) -> RuntimeSelectionResponse:
    if canonical_json_sha256(row.snapshot_json) != row.content_sha256:
        raise ConflictError("The stored model selection digest is invalid")
    return RuntimeSelectionResponse.model_validate(
        {
            "id": row.id,
            "model_id": row.model_id,
            "project_id": row.project_id,
            "snapshot": row.snapshot_json,
            "content_sha256": row.content_sha256,
            "created_at": row.created_at.replace(tzinfo=UTC)
            if row.created_at.tzinfo is None
            else row.created_at,
        }
    )


class ModelRuntimeService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def list(self, project_id: str) -> list[RuntimeSelectionResponse]:
        if self.session.get(Project, project_id) is None:
            raise NotFoundError("Project not found")
        rows = self.session.scalars(
            select(ModelRuntimeSelection)
            .where(ModelRuntimeSelection.project_id == project_id)
            .order_by(ModelRuntimeSelection.created_at.desc(), ModelRuntimeSelection.id)
        )
        return [_response(row) for row in rows]

    def get(self, project_id: str, selection_id: str) -> RuntimeSelectionResponse:
        row = self.session.get(ModelRuntimeSelection, selection_id)
        if row is None or row.project_id != project_id:
            raise NotFoundError("Reviewed model selection not found in this project")
        return _response(row)

    def preview(self, project_id: str, draft: RuntimeDraft) -> RuntimePreview:
        model = self.session.get(ModelRegistration, str(draft.model_id))
        if model is None or model.project_id != project_id:
            raise NotFoundError("Registered model not found in this project")
        applied = {"device"}
        if model.provider_name in {"reefpose", "ultralytics"}:
            applied.add("confidence_threshold")
        if model.provider_name == "ultralytics":
            applied.add("iou_threshold")
        options = reviewed_settings(self.settings, draft, applied)
        provider, runtime = resolve_reviewed_runtime(
            self.settings,
            provider_id=model.provider_name,
            task=model.task,
            runtime_id=draft.runtime_id,
            device=options.device,
        )
        verify_checkpoint(self.settings, model, model.sha256, model.file_size_bytes)
        receipt = RuntimeReceipt.model_validate(
            {
                "source_project_id": project_id,
                "source_model_id": model.id,
                "display_name": model.display_name,
                "catalog_id": f"registered-model/{model.id}",
                "checkpoint_sha256": model.sha256,
                "file_size_bytes": model.file_size_bytes,
                "task": model.task,
                "purpose": model.purpose,
                "labels": list(model.class_map_json.get("labels", [])),
                "class_mapping": dict(model.class_map_json.get("mapping", {})),
                "applied_image_settings": sorted(applied),
                "framework": model.framework,
                "provider_id": model.provider_name,
                "registered_provider_version": model.provider_version,
                "provider_version": provider,
                "runtime_id": draft.runtime_id,
                "runtime_version": runtime,
                "settings": options,
                "prompt": draft.prompt.strip(),
            }
        )
        return RuntimePreview(
            snapshot=receipt, content_sha256=canonical_json_sha256(receipt.model_dump(mode="json"))
        )

    def confirm(self, project_id: str, payload: RuntimeConfirmation) -> RuntimeSelectionResponse:
        preview = self.preview(project_id, payload.draft)
        if preview.content_sha256 != payload.reviewed_sha256:
            raise ConflictError(
                "Model, settings or runtime changed. Preview this configuration again."
            )
        lookup = select(ModelRuntimeSelection).where(
            ModelRuntimeSelection.project_id == project_id,
            ModelRuntimeSelection.content_sha256 == preview.content_sha256,
        )
        existing = self.session.scalar(lookup)
        if existing:
            return _response(existing)
        row = ModelRuntimeSelection(
            project_id=project_id,
            model_id=str(payload.draft.model_id),
            snapshot_json=preview.snapshot.model_dump(mode="json"),
            content_sha256=preview.content_sha256,
        )
        self.session.add(row)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = self.session.scalar(lookup)
            if existing is None:
                raise
            return _response(existing)
        return _response(row)

    def verify(
        self, project_id: str, selection_id: str, *, model_id: str, digest: str | None = None
    ) -> RuntimeSelectionResponse:
        pinned = self.get(project_id, selection_id)
        if str(pinned.model_id) != model_id or (
            digest is not None and digest != pinned.content_sha256
        ):
            raise ConflictError(
                "The model or selection digest differs from the reviewed configuration"
            )
        model = self.session.get(ModelRegistration, model_id)
        receipt = pinned.snapshot
        if model is None or model.project_id != project_id:
            raise ConflictError("The reviewed registration is unavailable in this project")
        row = self.session.get(ModelRuntimeSelection, selection_id)
        assert row is not None
        mapping = row.source_id_map_json
        expected_classes = {
            label: mapping.get(str(identifier), str(identifier)) if identifier is not None else None
            for label, identifier in receipt.class_mapping.items()
        }
        if model.class_map_json.get("mapping", {}) != expected_classes:
            raise ConflictError("The registered class mapping changed after model review")
        if (
            model.provider_name,
            model.provider_version,
            model.framework,
            model.task,
            model.purpose,
            model.class_map_json.get("labels", []),
        ) != (
            receipt.provider_id,
            receipt.registered_provider_version,
            receipt.framework,
            receipt.task,
            receipt.purpose,
            receipt.labels,
        ):
            raise ConflictError(
                "The registered model's compatibility information changed after review"
            )
        provider, runtime = resolve_reviewed_runtime(
            self.settings,
            provider_id=model.provider_name,
            task=model.task,
            runtime_id=receipt.runtime_id,
            device=receipt.settings.device,
        )
        if (provider, runtime) != (receipt.provider_version, receipt.runtime_version):
            raise ConflictError(
                "The installed provider or runtime version changed. Review a new configuration."
            )
        verify_checkpoint(self.settings, model, receipt.checkpoint_sha256, receipt.file_size_bytes)
        return pinned


def pinned_job_settings(pinned: RuntimeSelectionResponse) -> dict[str, Any]:
    return {
        **pinned.snapshot.settings.model_dump(),
        "runtime_selection_id": str(pinned.id),
        "runtime_selection_sha256": pinned.content_sha256,
    }


def workflow_runtime_settings(
    model_payload: dict[str, Any], *, video: bool = False
) -> dict[str, Any]:
    if "runtime_selection_id" not in model_payload:
        return {}
    result = {
        key: model_payload[key]
        for key in (
            "runtime_selection_id",
            "runtime_selection_sha256",
            "device",
            "confidence_threshold",
            "iou_threshold",
        )
    }
    if video:
        result["confidence"] = result.pop("confidence_threshold")
        result["iou"] = result.pop("iou_threshold")
    return result


def verify_queued_selection(
    session: Session, settings: Settings, project_id: str, request: dict[str, Any]
) -> None:
    if "runtime_selection_id" not in request:
        return
    pinned = ModelRuntimeService(session, settings).verify(
        project_id,
        str(request["runtime_selection_id"]),
        model_id=str(request["model_id"]),
        digest=str(request.get("runtime_selection_sha256", "")),
    )
    effective = pinned_job_settings(pinned)
    for key in ("device", "confidence_threshold", "iou_threshold"):
        request_key = key.removesuffix("_threshold") if "video_id" in request else key
        if request.get(request_key) != effective[key]:
            raise ConflictError("Queued inference settings differ from the reviewed configuration")
