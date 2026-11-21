"""Select the multimodal archive format only for projects carrying its records."""

from copy import deepcopy
from hashlib import sha256
from typing import Any
from zipfile import ZipFile

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import Job
from reefvision.db.models.image_adjustment import ImageAdjustmentRecipe
from reefvision.db.models.multispectral import SpectralAcquisition
from reefvision.db.models.taxonomy import DetectabilityAssessment, TaxonProposal
from reefvision.domain.errors import ValidationError
from reefvision.services.domain_shift_v18 import JOB_TYPE as DOMAIN_SHIFT_JOB
from reefvision.services.project_exchange_adjustment_v18 import (
    restore_adjustment_row,
    validate_adjustment_exchange,
)
from reefvision.services.project_exchange_bioacoustics_v18 import (
    AUDIO_SECTION_MODELS,
    contains_audio_exchange_records,
    has_audio_assets,
)
from reefvision.services.project_exchange_domain_shift_v18 import restore_domain_shift_row
from reefvision.services.project_exchange_spectral_v18 import BINDINGS, validate_spectral_archive
from reefvision.services.project_exchange_spectral_v18 import SECTIONS as SPECTRAL_SECTIONS
from reefvision.services.project_exchange_taxonomy_v18 import (
    TAXONOMY_SECTIONS,
    restore_taxonomy_row,
    validate_taxonomy_exchange,
)
from reefvision.storage.datasets import canonical_json_sha256

FORMAT = "1.8"
RESEARCH_FORMATS = {FORMAT, "2.0"}
SECTIONS = ("image_adjustment_recipes", *TAXONOMY_SECTIONS, *SPECTRAL_SECTIONS)


def has_research_records(session: Session, project_id: str) -> bool:
    domain_job = (
        select(Job.id)
        .where(Job.project_id == project_id, Job.job_type == DOMAIN_SHIFT_JOB)
        .limit(1)
    )
    return (
        session.scalar(domain_job) is not None
        or has_audio_assets(session, project_id)
        or any(
            session.scalar(select(model.id).where(model.project_id == project_id).limit(1))
            is not None
            for model in (
                ImageAdjustmentRecipe,
                TaxonProposal,
                DetectabilityAssessment,
                SpectralAcquisition,
            )
        )
    )


def validate_research_format(
    version: str, project_id: str, rows: dict[str, list[dict[str, Any]]], origin: Any
) -> None:
    sections = [name for name in SECTIONS if name in rows]
    has_domain = any(row.get("job_type") == DOMAIN_SHIFT_JOB for row in rows.get("jobs", []))
    has_domain_output = any(
        row.get("data_type") == "domain_shift_report" for row in rows.get("workflow_artifacts", [])
    )
    if version not in RESEARCH_FORMATS:
        if (
            sections
            or has_domain
            or has_domain_output
            or set(rows) & AUDIO_SECTION_MODELS.keys()
            or contains_audio_exchange_records(rows)
        ):
            raise ValidationError("Multimodal research records require Project Exchange 1.8")
        return
    if (
        version == FORMAT
        and not has_domain
        and not any(rows.get(name) for name in (*sections, *AUDIO_SECTION_MODELS))
    ):
        raise ValidationError("The 1.8 archive is missing its multimodal research records")
    if any(rows.get(name) for name in TAXONOMY_SECTIONS):
        if not all(name in rows for name in TAXONOMY_SECTIONS):
            raise ValidationError(
                "Taxonomy history requires all proposal, review, visit and assessment records"
            )
        validate_taxonomy_exchange(project_id, rows, origin)
    for name in sections:
        if name == BINDINGS:
            continue
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
    restore_adjustment_row(name, row, values, id_map)
    restore_domain_shift_row(name, row, values, id_map)
    if name in TAXONOMY_SECTIONS:
        restore_taxonomy_row(name, row, values, id_map)
        return
    if name not in SPECTRAL_SECTIONS or name == BINDINGS:
        return
    # All embedded IDs identify original evidence; only the outer relational
    # bindings point to the project receiving this copy.
    values["snapshot_json"] = deepcopy(row["snapshot_json"])
    values["content_sha256"] = row["content_sha256"]


def validate_research_images(
    project_id: str,
    rows: dict[str, list[dict[str, Any]]],
    manifest: dict[str, Any],
    archive: ZipFile,
) -> None:
    raw_origin = manifest.get("origin") or {}
    if not isinstance(raw_origin, dict) or not isinstance(raw_origin.get("id_map", {}), dict):
        raise ValidationError("The research archive has invalid source ID mappings")
    origins = raw_origin.get("id_map", {})
    images = {r["record_id"]: r for r in manifest.get("media", []) if r["kind"] == "image"}
    options = manifest.get("options", {})
    if not isinstance(options, dict):
        raise ValidationError("The research archive has invalid media options")

    def original(identifier: str) -> bytes | None:
        member = images.get(identifier)
        if member is None:
            if options.get("include_media"):
                raise ValidationError(
                    "A required original image is missing from the research archive"
                )
            return None
        # Both supported workflows cap each expanded original at or below 100 MiB.
        if archive.getinfo(member["path"]).file_size > 100 * 1024 * 1024:
            raise ValidationError(
                "A research image exceeds the supported single-band or adjustment size"
            )
        raw = archive.read(member["path"])
        if len(raw) != member["size_bytes"] or sha256(raw).hexdigest() != member["sha256"]:
            raise ValidationError(
                "The bundled original research image differs from its source checksum"
            )
        return raw

    validate_adjustment_exchange(project_id, rows, origin_ids=origins, read_image=original)
    validate_spectral_archive(project_id, rows, origins, original)
