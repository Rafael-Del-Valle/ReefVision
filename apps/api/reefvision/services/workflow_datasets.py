"""Workflow-native creation of immutable post-review dataset versions."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import DatasetVersion, DatasetVersionItem
from reefvision.domain.errors import ValidationError
from reefvision.schemas.dataset_versions import DatasetVersionCreateRequest, SplitRatios
from reefvision.services.measurement_aware_dataset_versions import (
    MeasurementAwareDatasetVersionService,
)


def _workflow_creator(run_id: str, node_run_id: str) -> str:
    return f"workflow:{run_id}:{node_run_id}"[:100]


def _result_payload(
    session: Session,
    version: DatasetVersion,
) -> dict[str, Any]:
    items = list(
        session.scalars(
            select(DatasetVersionItem)
            .where(DatasetVersionItem.dataset_version_id == version.id)
            .order_by(DatasetVersionItem.id)
        )
    )
    split_counts: dict[str, int] = {}
    for item in items:
        split = str(item.split)
        split_counts[split] = split_counts.get(split, 0) + 1
    return {
        "schema_version": "workflow-dataset-version-0001",
        "project_id": version.project_id,
        "dataset_version_id": version.id,
        "version_number": version.version_number,
        "name": version.name,
        "parent_version_id": version.parent_version_id,
        "manifest_sha256": version.manifest_sha256,
        "schema_version_snapshot": version.schema_version,
        "split_method": version.resolved_split_method,
        "split_counts": dict(sorted(split_counts.items())),
        "image_count": version.image_count,
        "annotation_count": version.annotation_count,
        "mask_annotation_count": version.mask_annotation_count,
        "image_ids": [item.image_id for item in items],
        "created_by": version.created_by,
        "created_by_workflow": True,
    }


def create_workflow_dataset_version(
    session: Session,
    settings: Settings,
    *,
    project_id: str,
    run_id: str,
    node_run_id: str,
    parameters: dict[str, Any],
    project_payload: dict[str, Any],
    parent_dataset_payload: dict[str, Any] | None = None,
    reviewed_payloads: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Freeze current reviewed project state into an idempotent immutable dataset version."""

    if project_payload.get("project_id") != project_id:
        raise ValidationError("Create Dataset Version received a foreign project reference")
    for reviewed in reviewed_payloads or []:
        if reviewed.get("project_id") != project_id:
            raise ValidationError("Create Dataset Version received reviewed data from another project")

    parent_version_id: str | None = None
    if parent_dataset_payload is not None:
        if parent_dataset_payload.get("project_id") != project_id:
            raise ValidationError("Parent dataset version belongs to another project")
        parent_version_id = str(parent_dataset_payload.get("dataset_version_id") or "") or None
        if parent_version_id is None:
            raise ValidationError("Parent dataset artifact is missing its version identifier")
        parent = session.get(DatasetVersion, parent_version_id)
        if parent is None or parent.project_id != project_id or parent.status != "complete":
            raise ValidationError("Parent dataset version must be complete and belong to this project")

    creator = _workflow_creator(run_id, node_run_id)
    existing = session.scalar(
        select(DatasetVersion)
        .where(
            DatasetVersion.project_id == project_id,
            DatasetVersion.created_by == creator,
            DatasetVersion.status == "complete",
        )
        .order_by(DatasetVersion.version_number.desc())
        .limit(1)
    )
    if existing is not None:
        return _result_payload(session, existing)

    requested_ratios_value = parameters.get("requested_ratios")
    requested_ratios = (
        SplitRatios.model_validate(requested_ratios_value)
        if requested_ratios_value is not None
        else SplitRatios()
    )
    statuses_value = parameters.get("eligible_annotation_statuses", ["reviewed"])
    if not isinstance(statuses_value, list) or not statuses_value:
        raise ValidationError("Create Dataset Version requires eligible_annotation_statuses")
    statuses = [str(value) for value in statuses_value]

    reuse_parent = bool(
        parameters.get(
            "reuse_parent_assignments",
            parent_version_id is not None,
        )
    )
    if reuse_parent and parent_version_id is None:
        raise ValidationError("Split reuse requires a parent dataset version")

    request = DatasetVersionCreateRequest(
        name=str(parameters.get("name") or f"Workflow dataset {run_id[:8]}").strip(),
        notes=str(parameters.get("notes") or "").strip() or None,
        parent_version_id=parent_version_id,
        eligible_annotation_statuses=statuses,
        split_method=str(parameters.get("split_method") or "random"),
        requested_ratios=requested_ratios,
        split_seed=(
            int(parameters["split_seed"])
            if parameters.get("split_seed") is not None
            else 42
        ),
        reuse_parent_assignments=reuse_parent,
        manual_assignments=[],
        creator=creator,
    )
    created = MeasurementAwareDatasetVersionService(session, settings).create_version(
        project_id,
        request,
    )
    version = session.get(DatasetVersion, created.id)
    if version is None or version.status != "complete":
        raise ValidationError("Workflow dataset version did not complete")
    return _result_payload(session, version)
