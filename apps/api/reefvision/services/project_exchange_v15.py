"""Validate and preserve original 1.5 research receipts across project copies."""

from typing import Any

from pydantic import ValidationError as SchemaError
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import ModelRuntimeSelection, StudyDesignRevision
from reefvision.db.models.reviewer_lab_v15 import ReviewerLabMember
from reefvision.domain.errors import ValidationError
from reefvision.schemas.model_runtime import RuntimeReceipt
from reefvision.services.project_exchange_reviewer_lab_v15 import (
    REVIEWER_LAB_SECTIONS,
    restore_reviewer_lab_row,
    validate_reviewer_lab_exchange,
)
from reefvision.services.project_exchange_study_v15 import (
    restore_study_row,
    validate_study_exchange,
)
from reefvision.storage.datasets import canonical_json_sha256

FORMAT_VERSION = "1.5"
INTEGRATED_FORMATS = {"1.2", FORMAT_VERSION}
SECTIONS = ("model_runtime_selections", "study_design_revisions", *REVIEWER_LAB_SECTIONS)


def has_v15_records(session: Session, project_id: str) -> bool:
    return any(
        session.scalar(select(model.id).where(model.project_id == project_id).limit(1)) is not None
        for model in (ModelRuntimeSelection, StudyDesignRevision, ReviewerLabMember)
    )


def model_source_ids(receipt: RuntimeReceipt) -> set[str]:
    return {
        str(receipt.source_project_id),
        str(receipt.source_model_id),
        *(str(identifier) for identifier in receipt.class_mapping.values() if identifier),
    }


def validate_v15_exchange(
    version: str, project_id: str, sections: dict[str, list[dict[str, Any]]], origin: Any
) -> None:
    original_to_local = (origin or {}).get("id_map", {}) if isinstance(origin, dict) else {}
    validate_study_exchange(project_id, sections, original_to_local)
    validate_reviewer_lab_exchange(sections, project_id=project_id, origin_ids=original_to_local)
    present = any(sections.get(name) for name in (*SECTIONS, "field_capture_batches"))
    if (version == FORMAT_VERSION) != present:
        raise ValidationError(
            "The exchange format does not match the included 1.5 research records"
        )
    if not present:
        return
    registrations = {row["id"]: row for row in sections.get("models", [])}
    classes = {row["id"] for row in sections.get("label_classes", [])}
    for row in sections.get("model_runtime_selections", []):
        try:
            receipt = RuntimeReceipt.model_validate(row["snapshot_json"])
            local = row["source_id_map_json"]
            identifiers = model_source_ids(receipt)
            registration = registrations[row["model_id"]]
            if (
                canonical_json_sha256(row["snapshot_json"]) != row["content_sha256"]
                or receipt.catalog_id != f"registered-model/{receipt.source_model_id}"
                or local.keys() - identifiers
                or any(
                    local.get(key, key) != original_to_local.get(key, key) for key in identifiers
                )
                or local.get(str(receipt.source_project_id), str(receipt.source_project_id))
                != project_id
                or local.get(str(receipt.source_model_id), str(receipt.source_model_id))
                != registration["id"]
                or registration["sha256"] != receipt.checkpoint_sha256
                or registration["file_size_bytes"] != receipt.file_size_bytes
                or any(
                    local.get(str(key), str(key)) not in classes
                    for key in receipt.class_mapping.values()
                    if key
                )
            ):
                raise ValueError("Invalid source linkage or digest")
        except (SchemaError, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ValidationError(
                "Reviewed model selection has an invalid receipt or source reference"
            ) from exc


def restore_v15_row(
    name: str, row: dict[str, Any], values: dict[str, Any], mapping: dict[str, str]
) -> None:
    restore_study_row(name, row, values, mapping)
    restore_reviewer_lab_row(name, row, values, mapping)
    if name == "model_runtime_selections":
        receipt = RuntimeReceipt.model_validate(row["snapshot_json"])
        previous = row["source_id_map_json"]
        values["source_id_map_json"] = {
            key: mapping[previous.get(key, key)] for key in model_source_ids(receipt)
        }
        values["snapshot_json"] = row["snapshot_json"]
