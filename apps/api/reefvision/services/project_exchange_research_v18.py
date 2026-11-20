"""Select the multimodal archive format only for projects carrying its records."""

from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models.image_adjustment import ImageAdjustmentRecipe
from reefvision.db.models.taxonomy import DetectabilityAssessment, TaxonProposal
from reefvision.domain.errors import ValidationError
from reefvision.services.project_exchange_taxonomy_v18 import (
    TAXONOMY_SECTIONS,
    restore_taxonomy_row,
    validate_taxonomy_exchange,
)
from reefvision.storage.datasets import canonical_json_sha256

FORMAT = "1.8"
SECTIONS = ("image_adjustment_recipes", *TAXONOMY_SECTIONS)


def has_research_records(session: Session, project_id: str) -> bool:
    return any(
        session.scalar(select(model.id).where(model.project_id == project_id).limit(1)) is not None
        for model in (ImageAdjustmentRecipe, TaxonProposal, DetectabilityAssessment)
    )


def validate_research_format(
    version: str, project_id: str, rows: dict[str, list[dict[str, Any]]], origin: Any
) -> None:
    sections = [name for name in SECTIONS if name in rows]
    if version != FORMAT:
        if sections:
            raise ValidationError("Multimodal research records require Project Exchange 1.8")
        return
    if not any(rows[name] for name in sections):
        raise ValidationError("The 1.8 archive is missing its multimodal research records")
    if any(rows.get(name) for name in TAXONOMY_SECTIONS):
        if not all(name in rows for name in TAXONOMY_SECTIONS):
            raise ValidationError(
                "Taxonomy history requires the full proposal, review, visit and assessment inventory"
            )
        validate_taxonomy_exchange(project_id, rows, origin)
    for name in sections:
        field = "receipt_json" if name == "image_adjustment_recipes" else "snapshot_json"
        for record in rows[name]:
            snapshot = record.get(field)
            if (
                record.get("project_id") != project_id
                or not isinstance(snapshot, dict)
                or canonical_json_sha256(snapshot) != record.get("content_sha256")
            ):
                raise ValidationError(
                    f"The {name} record is missing its original project or research receipt"
                )


def preserve_research_snapshot(
    name: str, row: dict[str, Any], values: dict[str, Any], id_map: dict[str, str]
) -> None:
    if name in TAXONOMY_SECTIONS:
        restore_taxonomy_row(name, row, values, id_map)
        return
    if name not in SECTIONS:
        return
    # All embedded IDs identify original evidence; only the outer relational
    # bindings point to the project receiving this copy.
    field = "receipt_json" if name == "image_adjustment_recipes" else "snapshot_json"
    values[field] = deepcopy(row[field])
    values["content_sha256"] = row["content_sha256"]
    for literal in ("protocol", "organism_key"):
        if literal in row:
            values[literal] = row[literal]
