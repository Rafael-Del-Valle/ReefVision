"""CoralVision 1.0 import extensions for portable training and generated state."""

from __future__ import annotations

import shutil
import zipfile
from collections.abc import BinaryIO
from pathlib import PurePosixPath

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import Project, ProjectExchangePackage, TrainingDraft
from reefvision.schemas.project_exchange import ProjectExchangeImportResponse
from reefvision.services import project_exchange_import as base_import
from reefvision.storage.projects import resolve_managed_project_path


def _register_v1_sections() -> None:
    base_import.SECTION_MODELS["training_drafts"] = TrainingDraft
    if "training_drafts" not in base_import.SECTION_ORDER:
        model_index = base_import.SECTION_ORDER.index("models")
        base_import.SECTION_ORDER.insert(model_index + 1, "training_drafts")


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
