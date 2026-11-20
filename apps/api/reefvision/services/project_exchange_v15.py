"""Validate and preserve original 1.5 research receipts across project copies."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import ModelRuntimeSelection, StudyDesignRevision
from reefvision.db.models.reviewer_lab_v15 import ReviewerLabMember
from reefvision.domain.errors import ValidationError
from reefvision.schemas.model_runtime import read_runtime_receipt, runtime_source_links_match
from reefvision.services.project_exchange_reviewer_lab_v15 import (
    REVIEWER_LAB_SECTIONS,
    restore_reviewer_lab_row,
    validate_reviewer_lab_exchange,
)
from reefvision.services.project_exchange_study_v15 import (
    restore_study_row,
    validate_study_exchange,
)

FORMAT_VERSION = "1.5"
INTEGRATED_FORMATS = {"1.2", FORMAT_VERSION, "1.6", "1.7", "1.7.1", "1.8"}
SECTIONS = ("model_runtime_selections", "study_design_revisions", *REVIEWER_LAB_SECTIONS)


def has_v15_records(session: Session, project_id: str) -> bool:
    return any(
        session.scalar(select(model.id).where(model.project_id == project_id).limit(1)) is not None
        for model in (ModelRuntimeSelection, StudyDesignRevision, ReviewerLabMember)
    )


def validate_v15_exchange(
    version: str, project_id: str, sections: dict[str, list[dict[str, Any]]], origin: Any
) -> None:
    original_to_local = (origin or {}).get("id_map", {}) if isinstance(origin, dict) else {}
    validate_study_exchange(project_id, sections, original_to_local)
    validate_reviewer_lab_exchange(sections, project_id=project_id, origin_ids=original_to_local)
    present = any(sections.get(name) for name in (*SECTIONS, "field_capture_batches"))
    if (present and version not in {FORMAT_VERSION, "1.6", "1.7", "1.7.1", "1.8"}) or (
        version == FORMAT_VERSION and not present
    ):
        raise ValidationError(
            "The exchange format does not match the included 1.5 research records"
        )
    if not present:
        return
    registrations = {row["id"]: row for row in sections.get("models", [])}
    classes = {row["id"] for row in sections.get("label_classes", [])}
    for row in sections.get("model_runtime_selections", []):
        try:
            receipt = read_runtime_receipt(row["snapshot_json"], row["content_sha256"])
            local = row["source_id_map_json"]
            registration = registrations[row["model_id"]]
            if (
                not runtime_source_links_match(
                    receipt,
                    local,
                    original_to_local,
                    project_id=project_id,
                    model_id=registration["id"],
                )
                or registration["sha256"] != receipt.checkpoint_sha256
                or registration["file_size_bytes"] != receipt.file_size_bytes
                or any(
                    local.get(str(key), str(key)) not in classes
                    for key in receipt.class_mapping.values()
                    if key
                )
            ):
                raise ValueError("Invalid source linkage or digest")
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ValidationError(
                "Reviewed model selection has an invalid receipt or source reference"
            ) from exc


def restore_v15_row(
    name: str, row: dict[str, Any], values: dict[str, Any], mapping: dict[str, str]
) -> None:
    restore_study_row(name, row, values, mapping)
    restore_reviewer_lab_row(name, row, values, mapping)
    if name == "model_runtime_selections":
        receipt = read_runtime_receipt(row["snapshot_json"], row["content_sha256"])
        previous = row["source_id_map_json"]
        values["source_id_map_json"] = {
            key: mapping[previous.get(key, key)] for key in receipt.source_ids()
        }
        values["snapshot_json"] = row["snapshot_json"]
