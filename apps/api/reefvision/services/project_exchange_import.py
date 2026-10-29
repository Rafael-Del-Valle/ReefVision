"""Safe import-as-new-project for ReefVision 1.0 exchange packages."""

from __future__ import annotations

import json
import shutil
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any, BinaryIO
from uuid import uuid4

from sqlalchemy import DateTime
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    ActiveLearningRound,
    Annotation,
    ClassificationDataset,
    ClassificationPrediction,
    DatasetVersion,
    DatasetVersionItem,
    EnvironmentalCacheEntry,
    ExperimentRecord,
    ImageAsset,
    ImageLabel,
    Job,
    LabelClass,
    MaskAnnotation,
    ModelRegistration,
    PredictionProposal,
    Project,
    ProjectExchangePackage,
    QualityControlIssue,
    QualityControlRun,
    ReviewQueue,
    ReviewQueueItem,
    ScientificRecord,
    TrainingRun,
    VideoAsset,
    VideoTrack,
    WorkflowArtifact,
    WorkflowGraphRecord,
    WorkflowNodeRun,
    WorkflowRun,
)
from reefvision.domain.errors import ValidationError
from reefvision.schemas.project_exchange import (
    ProjectExchangeImportResponse,
    ProjectExchangePackageResponse,
)
from reefvision.schemas.projects import ProjectCreate
from reefvision.services.project_exchange_inspection import (
    MANIFEST_NAME,
    inspect_project_exchange,
)
from reefvision.services.project_exchange_scientific import (
    SCIENCE_SECTIONS,
    remap_scientific_sections,
    validate_exchange_records,
)
from reefvision.services.projects import ProjectService
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path

SECTION_MODELS: dict[str, type[Any]] = {
    "scientific_records": ScientificRecord,
    "environmental_cache_entries": EnvironmentalCacheEntry,
    "label_classes": LabelClass,
    "images": ImageAsset,
    "videos": VideoAsset,
    "jobs": Job,
    "dataset_versions": DatasetVersion,
    "dataset_version_items": DatasetVersionItem,
    "models": ModelRegistration,
    "classification_datasets": ClassificationDataset,
    "training_runs": TrainingRun,
    "annotations": Annotation,
    "mask_annotations": MaskAnnotation,
    "image_labels": ImageLabel,
    "prediction_proposals": PredictionProposal,
    "classification_predictions": ClassificationPrediction,
    "experiments": ExperimentRecord,
    "quality_control_runs": QualityControlRun,
    "quality_control_issues": QualityControlIssue,
    "review_queues": ReviewQueue,
    "review_queue_items": ReviewQueueItem,
    "active_learning_rounds": ActiveLearningRound,
    "video_tracks": VideoTrack,
    "workflow_graphs": WorkflowGraphRecord,
    "workflow_runs": WorkflowRun,
    "workflow_node_runs": WorkflowNodeRun,
    "workflow_artifacts": WorkflowArtifact,
}

# Parent objects appear before dependants. DatasetVersion's self-parent reference is
# restored in a second pass after every version row exists.
SECTION_ORDER = [
    "label_classes",
    "images",
    "videos",
    "jobs",
    "dataset_versions",
    "models",
    "classification_datasets",
    "dataset_version_items",
    "training_runs",
    "annotations",
    "mask_annotations",
    "image_labels",
    "prediction_proposals",
    "classification_predictions",
    "experiments",
    "quality_control_runs",
    "quality_control_issues",
    "review_queues",
    "review_queue_items",
    "active_learning_rounds",
    "video_tracks",
    "workflow_graphs",
    "workflow_runs",
    "workflow_node_runs",
    "workflow_artifacts",
    "scientific_records",
    "environmental_cache_entries",
]

MEDIA_KIND_BY_SECTION = {
    "images": "image",
    "videos": "video",
    "models": "model",
}

JSON_HASH_FIELDS: dict[type[Any], tuple[str, str]] = {
    DatasetVersion: ("manifest_json", "manifest_sha256"),
    ClassificationDataset: ("manifest_json", "manifest_sha256"),
    WorkflowGraphRecord: ("graph_json", "graph_sha256"),
    WorkflowArtifact: ("payload_json", "payload_sha256"),
}


def _read_jsonl(archive: zipfile.ZipFile, member: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(archive.read(member).splitlines(), start=1):
        if not raw.strip():
            continue
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValidationError(
                f"Exchange record {member} line {line_number} must be a JSON object"
            )
        rows.append(value)
    return rows


def _remap_json(value: Any, id_map: dict[str, str]) -> Any:
    if isinstance(value, str):
        return id_map.get(value, value)
    if isinstance(value, list):
        return [_remap_json(item, id_map) for item in value]
    if isinstance(value, dict):
        return {key: _remap_json(item, id_map) for key, item in value.items()}
    return value


def _coerce_row(
    model: type[Any],
    row: dict[str, Any],
    id_map: dict[str, str],
) -> dict[str, Any]:
    table = model.__table__
    values = _remap_json(row, id_map)
    converted: dict[str, Any] = {}
    for column in table.columns:
        if column.name not in values:
            continue
        value = values[column.name]
        if value is not None and isinstance(column.type, DateTime) and isinstance(value, str):
            value = datetime.fromisoformat(value)
        converted[column.name] = value
    return converted


def _rewrite_project_paths(
    values: dict[str, Any],
    model: type[Any],
    source_storage_root: str,
    target_storage_root: str,
) -> None:
    prefix = source_storage_root.rstrip("/") + "/"
    for column in model.__table__.columns:
        if not column.name.endswith("_path"):
            continue
        value = values.get(column.name)
        if isinstance(value, str) and value.startswith(prefix):
            values[column.name] = target_storage_root.rstrip("/") + "/" + value[len(prefix) :]


def _refresh_json_checksum(model: type[Any], values: dict[str, Any]) -> None:
    fields = JSON_HASH_FIELDS.get(model)
    if fields is None:
        return
    json_field, hash_field = fields
    payload = values.get(json_field)
    if isinstance(payload, (dict, list)):
        values[hash_field] = canonical_json_sha256(payload)


def _media_inventory(manifest: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    raw = manifest.get("media", [])
    if not isinstance(raw, list):
        return result
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        record_id = item.get("record_id")
        member = item.get("path")
        if isinstance(kind, str) and isinstance(record_id, str) and isinstance(member, str):
            result[(kind, record_id)] = item
    return result


def _copy_packaged_media(
    *,
    archive: zipfile.ZipFile,
    descriptor: dict[str, Any],
    settings: Settings,
    storage_root: str,
    kind: str,
    new_id: str,
) -> str:
    member = str(descriptor["path"])
    suffix = PurePosixPath(member).suffix.lower()
    plural = {"image": "images", "video": "videos", "model": "models"}[kind]
    relative = f"{storage_root}/exchange-import/{plural}/{new_id}{suffix}"
    destination = resolve_managed_project_path(settings, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(member, "r") as source, destination.open("wb") as target:
        shutil.copyfileobj(source, target)
    return relative


def import_project_exchange(
    source: BinaryIO,
    session: Session,
    settings: Settings,
    *,
    project_name: str | None = None,
    finalize: Callable[[Project, ProjectExchangePackage], None] | None = None,
) -> ProjectExchangeImportResponse:
    """Import a compatible archive into a newly created project.

    Source primary keys are never reused. Direct foreign keys and exact UUID values
    embedded in JSON payloads are remapped to the corresponding imported records.
    """

    source.seek(0)
    inspection = inspect_project_exchange(source)
    if not inspection.compatible:
        raise ValidationError("Exchange package failed inspection: " + "; ".join(inspection.errors))

    source.seek(0)
    with zipfile.ZipFile(source, "r") as archive:
        manifest_value = json.loads(archive.read(MANIFEST_NAME))
        if not isinstance(manifest_value, dict):
            raise ValidationError("Exchange manifest must be a JSON object")
        manifest: dict[str, Any] = manifest_value
        sections_descriptor = manifest.get("sections", {})
        if not isinstance(sections_descriptor, dict):
            raise ValidationError("Exchange manifest sections are invalid")

        source_project_rows: list[dict[str, Any]] = []
        project_descriptor = sections_descriptor.get("project")
        if isinstance(project_descriptor, dict):
            member = project_descriptor.get("path")
            if isinstance(member, str):
                source_project_rows = _read_jsonl(archive, member)
        if len(source_project_rows) != 1:
            raise ValidationError("Exchange package must contain exactly one source project row")
        source_project = source_project_rows[0]
        old_project_id = str(source_project.get("id", ""))
        if not old_project_id:
            raise ValidationError("Exchange source project ID is missing")
        source_storage_root = str(source_project.get("storage_root") or "")

        requested_name = (
            project_name.strip()
            if project_name is not None and project_name.strip()
            else str(source_project.get("name") or inspection.project_name or "Imported project")
        )
        raw_height_offset = source_project.get("georeference_height_offset_m")
        try:
            georeference_height_offset_m = (
                0.0 if raw_height_offset is None else float(raw_height_offset)
            )
        except (TypeError, ValueError) as exc:
            raise ValidationError("Exchange project georeference height offset is invalid") from exc
        raw_height_evidence = source_project.get("georeference_height_evidence")
        georeference_height_evidence = (
            str(raw_height_evidence).strip() if raw_height_evidence is not None else None
        ) or None

        section_rows: dict[str, list[dict[str, Any]]] = {}
        for section_name, descriptor_value in sections_descriptor.items():
            if section_name == "project" or not isinstance(descriptor_value, dict):
                continue
            member = descriptor_value.get("path")
            if isinstance(member, str):
                section_rows[section_name] = _read_jsonl(archive, member)

        validate_exchange_records(old_project_id, section_rows, SECTION_MODELS)

        project: Project | None = None
        try:
            project = ProjectService(session, settings).create_project(
                ProjectCreate(
                    name=requested_name,
                    description=(
                        str(source_project["description"])
                        if source_project.get("description") is not None
                        else None
                    ),
                    template="blank",
                ),
                commit=False,
            )
            # Preserve legacy numeric offsets even when older packages have no datum evidence.
            # Such projects remain intentionally unavailable for production georeferencing
            # until evidence is supplied.
            project.georeference_height_offset_m = georeference_height_offset_m
            project.georeference_height_evidence = georeference_height_evidence
            project.default_annotation_type = str(
                source_project.get("default_annotation_type") or project.default_annotation_type
            )
            session.flush()
            session.refresh(project)

            id_map: dict[str, str] = {old_project_id: project.id}
            for section_name, rows in section_rows.items():
                if section_name not in SECTION_MODELS:
                    continue
                for row in rows:
                    old_id = row.get("id")
                    if isinstance(old_id, str) and old_id:
                        id_map[old_id] = str(uuid4())

            # Immutable revision-series identifiers are not primary keys, but they
            # still must be remapped when a package is imported more than once.
            # This keeps every imported project scientifically independent.
            for rows in section_rows.values():
                for row in rows:
                    for field in (
                        "ethogram_series_id",
                        "bout_series_id",
                        "observation_series_id",
                        "analysis_series_id",
                    ):
                        value = row.get(field)
                        if isinstance(value, str) and value:
                            id_map.setdefault(value, str(uuid4()))

            scientific_rows = remap_scientific_sections(section_rows, id_map)
            media = _media_inventory(manifest)
            warnings = list(inspection.warnings)
            imported_counts: dict[str, int] = {}
            copied_media_count = 0
            dataset_parent_links: list[tuple[DatasetVersion, str]] = []
            imported_graphs: dict[str, WorkflowGraphRecord] = {}

            for section_name in SECTION_ORDER:
                model = SECTION_MODELS[section_name]
                rows = section_rows.get(section_name, [])
                if not rows:
                    imported_counts[section_name] = 0
                    continue
                created: list[Any] = []
                for row_index, source_row in enumerate(rows):
                    row = dict(source_row)
                    old_id = row.get("id")
                    if section_name in SCIENCE_SECTIONS:
                        mapped = scientific_rows[section_name][row_index]
                        # Preserve JSON evidence; only scalar foreign keys use the shared mapper.
                        values = _coerce_row(model, {**mapped, "payload_json": {}}, id_map)
                        values["payload_json"] = mapped["payload_json"]
                    else:
                        values = _coerce_row(model, row, id_map)
                    _rewrite_project_paths(
                        values,
                        model,
                        source_storage_root,
                        project.storage_root,
                    )
                    if "project_id" in model.__table__.columns:
                        values["project_id"] = project.id
                    if isinstance(old_id, str) and "id" in model.__table__.columns:
                        values["id"] = id_map[old_id]

                    if section_name == "images":
                        # Thumbnails are generated artifacts, not original media. Never
                        # leave an imported image pointing into the source project tree.
                        values["thumbnail_path"] = None

                    if section_name == "dataset_versions":
                        old_parent = row.get("parent_version_id")
                        if isinstance(old_parent, str) and old_parent:
                            values["parent_version_id"] = None

                    if section_name == "workflow_runs":
                        graph_id = values.get("workflow_graph_record_id")
                        if isinstance(graph_id, str):
                            graph = imported_graphs.get(graph_id)
                            if graph is not None:
                                values["graph_sha256"] = graph.graph_sha256

                    media_kind = MEDIA_KIND_BY_SECTION.get(section_name)
                    if media_kind is not None and isinstance(old_id, str):
                        descriptor = media.get((media_kind, old_id))
                        if descriptor is not None:
                            values["managed_path"] = _copy_packaged_media(
                                archive=archive,
                                descriptor=descriptor,
                                settings=settings,
                                storage_root=project.storage_root,
                                kind=media_kind,
                                new_id=id_map[old_id],
                            )
                            copied_media_count += 1
                        elif "managed_path" in model.__table__.columns:
                            source_name = str(
                                row.get("original_filename") or row.get("source_filename") or old_id
                            )
                            suffix = PurePosixPath(source_name).suffix.lower()
                            values["managed_path"] = (
                                f"{project.storage_root}/exchange-import/missing/"
                                f"{media_kind}s/{id_map[old_id]}{suffix}"
                            )
                            metadata = values.get("metadata_json")
                            if isinstance(metadata, dict):
                                values["metadata_json"] = {
                                    **metadata,
                                    "exchange_media_missing": True,
                                    "exchange_source_record_id": old_id,
                                }
                            warnings.append(
                                f"{media_kind.title()} media was not packaged for "
                                f"{source_name}; the imported record requires relinking "
                                "before file-backed operations."
                            )

                    _refresh_json_checksum(model, values)
                    instance = model(**values)
                    session.add(instance)
                    created.append(instance)
                    if section_name == "dataset_versions":
                        old_parent = row.get("parent_version_id")
                        if isinstance(old_parent, str) and old_parent:
                            dataset_parent_links.append((instance, old_parent))
                    if section_name == "workflow_graphs" and isinstance(old_id, str):
                        imported_graphs[id_map[old_id]] = instance
                session.flush()
                imported_counts[section_name] = len(created)

            for version, old_parent_id in dataset_parent_links:
                new_parent_id = id_map.get(old_parent_id)
                if new_parent_id is not None:
                    version.parent_version_id = new_parent_id
            session.flush()

            # Persist the source archive as import provenance inside the new project.
            package_id = str(uuid4())
            archive_relative = (
                f"{project.storage_root}/exchanges/{package_id}.imported.reefvision.zip"
            )
            archive_destination = resolve_managed_project_path(settings, archive_relative)
            archive_destination.parent.mkdir(parents=True, exist_ok=True)
            source.seek(0)
            with archive_destination.open("wb") as target:
                shutil.copyfileobj(source, target)

            manifest_sha256 = canonical_json_sha256(manifest)
            package = ProjectExchangePackage(
                id=package_id,
                project_id=project.id,
                direction="import",
                status="complete",
                format_version=str(manifest.get("format_version", "1.0")),
                manifest_json=manifest,
                manifest_sha256=manifest_sha256,
                archive_path=archive_relative,
                options_json={
                    "source_project_id": old_project_id,
                    "source_project_name": source_project.get("name"),
                    "id_remapped": True,
                    "id_map": id_map,
                    "copied_media_count": copied_media_count,
                },
                completed_at=datetime.now(UTC),
            )
            session.add(package)
            session.flush()
            if finalize is not None:
                finalize(project, package)
            session.commit()
            session.refresh(project)
            session.refresh(package)
        except Exception:
            session.rollback()
            if project is not None:
                project_root = resolve_managed_project_path(settings, project.storage_root)
                shutil.rmtree(project_root, ignore_errors=True)
            raise

    return ProjectExchangeImportResponse(
        project_id=project.id,
        project_name=project.name,
        project_slug=project.slug,
        source_manifest_sha256=manifest_sha256,
        imported_counts=imported_counts,
        copied_media_count=copied_media_count,
        warnings=list(dict.fromkeys(warnings)),
        package=ProjectExchangePackageResponse.model_validate(package),
    )
