"""CoralVision 1.0 import extensions for complete portable project state."""

from __future__ import annotations

import shutil
import zipfile
from collections.abc import BinaryIO
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    AnnotationEvent,
    ClassOperation,
    ClassVisibilityPreference,
    ExportRecord,
    MaskAnnotationEvent,
    Project,
    ProjectClassVisibilityDefault,
    ProjectExchangePackage,
    TrainingDraft,
)
from reefvision.schemas.project_exchange import ProjectExchangeImportResponse
from reefvision.services import project_exchange_import as base_import
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path


def _insert_after(section_name: str, after: str) -> None:
    if section_name in base_import.SECTION_ORDER:
        return
    index = base_import.SECTION_ORDER.index(after)
    base_import.SECTION_ORDER.insert(index + 1, section_name)


def _register_v1_sections() -> None:
    base_import.SECTION_MODELS.update(
        {
            "training_drafts": TrainingDraft,
            "annotation_events": AnnotationEvent,
            "mask_annotation_events": MaskAnnotationEvent,
            "project_class_visibility_defaults": ProjectClassVisibilityDefault,
            "class_visibility_preferences": ClassVisibilityPreference,
            "class_operations": ClassOperation,
            "exports": ExportRecord,
        }
    )
    _insert_after("project_class_visibility_defaults", "label_classes")
    _insert_after("class_visibility_preferences", "project_class_visibility_defaults")
    _insert_after("class_operations", "class_visibility_preferences")
    _insert_after("training_drafts", "models")
    _insert_after("exports", "dataset_version_items")
    _insert_after("annotation_events", "annotations")
    _insert_after("mask_annotation_events", "mask_annotations")


def _safe_relative_path(value: str) -> bool:
    path = PurePosixPath(value.replace("\\", "/"))
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def _restore_generated_artifacts(
    source: BinaryIO,
    *,
    project: Project,
    settings: Settings,
    manifest: dict[str, object],
) -> int:
    raw_descriptors = manifest.get("generated_artifacts", [])
    if not isinstance(raw_descriptors, list):
        raise ValueError("Generated artifact inventory must be a list")

    copied = 0
    source.seek(0)
    with zipfile.ZipFile(source, "r") as archive:
        for index, descriptor_value in enumerate(raw_descriptors):
            if not isinstance(descriptor_value, dict):
                raise ValueError(f"Generated artifact descriptor {index} is invalid")
            member = str(descriptor_value.get("path", ""))
            source_relative_path = str(
                descriptor_value.get("source_relative_path", "")
            )
            if not _safe_relative_path(member) or not _safe_relative_path(
                source_relative_path
            ):
                raise ValueError(f"Generated artifact path {index} is unsafe")
            destination_relative = (
                f"{project.storage_root.rstrip('/')}/{source_relative_path}"
            )
            destination = resolve_managed_project_path(settings, destination_relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member, "r") as archive_stream, destination.open(
                "wb"
            ) as output_stream:
                shutil.copyfileobj(archive_stream, output_stream)
            copied += 1
    return copied


def _operation_checksum(operation: ClassOperation) -> str:
    plan: dict[str, Any] = dict(operation.plan_json or {})

    def records(key: str) -> list[dict[str, object]]:
        raw = plan.get(key, [])
        if not isinstance(raw, list):
            return []
        return [
            {
                "key": str(item.get("key", "")),
                "record_ids": list(item.get("record_ids", [])),
            }
            for item in raw
            if isinstance(item, dict)
        ]

    raw_impacts = plan.get("compatibility_impacts", [])
    impacts = [
        {
            "key": str(item.get("key", "")),
            "status": str(item.get("status", "")),
            "record_ids": list(item.get("record_ids", [])),
        }
        for item in raw_impacts
        if isinstance(item, dict)
    ] if isinstance(raw_impacts, list) else []
    payload = {
        "operation_type": operation.operation_type,
        "project_id": operation.project_id,
        "source_class_id": operation.source_class_id,
        "target_class_id": operation.target_class_id,
        "mutable_records": records("mutable_records"),
        "protected_records": records("protected_records"),
        "blocking_records": records("blocking_records"),
        "compatibility_impacts": impacts,
        "warnings": list(plan.get("warnings", [])),
        "blockers": list(plan.get("blockers", [])),
    }
    return canonical_json_sha256(payload)


def _refresh_class_operation_checksums(session: Session, project_id: str) -> None:
    operations = list(
        session.scalars(
            select(ClassOperation).where(ClassOperation.project_id == project_id)
        )
    )
    for operation in operations:
        operation.preview_checksum = _operation_checksum(operation)
    session.flush()


def import_project_exchange_v1(
    source: BinaryIO,
    session: Session,
    settings: Settings,
    *,
    project_name: str | None = None,
) -> ProjectExchangeImportResponse:
    """Import the complete 1.0 portable record inventory into a new project."""

    _register_v1_sections()
    result = base_import.import_project_exchange(
        source,
        session,
        settings,
        project_name=project_name,
    )
    project = session.get(Project, result.project_id)
    if project is None:
        raise RuntimeError("Imported project disappeared before artifact restoration")

    try:
        _refresh_class_operation_checksums(session, project.id)
        copied_generated = _restore_generated_artifacts(
            source,
            project=project,
            settings=settings,
            manifest=dict(result.package.manifest_json),
        )
        package = session.get(ProjectExchangePackage, result.package.id)
        if package is None:
            raise RuntimeError("Imported exchange provenance record disappeared")
        package.options_json = {
            **dict(package.options_json or {}),
            "copied_generated_artifact_count": copied_generated,
        }
        session.commit()
        session.refresh(package)
        result.copied_generated_artifact_count = copied_generated
        result.package = type(result.package).model_validate(package)
        return result
    except Exception:
        session.rollback()
        project_root = resolve_managed_project_path(settings, project.storage_root)
        doomed = session.get(Project, result.project_id)
        if doomed is not None:
            session.delete(doomed)
            session.commit()
        shutil.rmtree(project_root, ignore_errors=True)
        raise
