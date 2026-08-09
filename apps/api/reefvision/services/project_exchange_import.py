"""Transactional import of versioned ReefVision project exchange packages."""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from collections.abc import BinaryIO
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from sqlalchemy import Date, DateTime, select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    ActiveLearningRound,
    Annotation,
    AnnotationEvent,
    ClassOperation,
    ClassVisibilityPreference,
    ClassificationDataset,
    ClassificationPrediction,
    DatasetVersion,
    DatasetVersionItem,
    ExperimentRecord,
    ImageAsset,
    ImageLabel,
    LabelClass,
    MaskAnnotation,
    MaskAnnotationEvent,
    ModelRegistration,
    PredictionProposal,
    Project,
    ProjectClassVisibilityDefault,
    ProjectExchangePackage,
    QualityControlIssue,
    QualityControlRun,
    ReviewQueue,
    ReviewQueueItem,
    TrainingDraft,
    TrainingRun,
    VideoAsset,
    VideoTrack,
)
from reefvision.domain.errors import ValidationError
from reefvision.services.project_exchange_classification import (
    restore_classification_dataset_materialization,
)
from reefvision.services.projects import slugify
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import create_managed_project_directory, resolve_managed_project_path

FORMAT_NAME = "reefvision-project-exchange"
FORMAT_MAJOR = "1"
MANIFEST_NAME = "reefvision-exchange-manifest.json"
MAX_ARCHIVE_MEMBERS = 100_000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 100 * 1024**3

SECTION_MODELS: dict[str, type[Any]] = {
    "project": Project,
    "label_classes": LabelClass,
    "class_operations": ClassOperation,
    "project_class_visibility_defaults": ProjectClassVisibilityDefault,
    "class_visibility_preferences": ClassVisibilityPreference,
    "images": ImageAsset,
    "annotations": Annotation,
    "annotation_events": AnnotationEvent,
    "mask_annotations": MaskAnnotation,
    "mask_annotation_events": MaskAnnotationEvent,
    "image_labels": ImageLabel,
    "prediction_proposals": PredictionProposal,
    "classification_predictions": ClassificationPrediction,
    "classification_datasets": ClassificationDataset,
    "videos": VideoAsset,
    "video_tracks": VideoTrack,
    "dataset_versions": DatasetVersion,
    "dataset_version_items": DatasetVersionItem,
    "models": ModelRegistration,
    "training_drafts": TrainingDraft,
    "training_runs": TrainingRun,
    "experiments": ExperimentRecord,
    "quality_control_runs": QualityControlRun,
    "quality_control_issues": QualityControlIssue,
    "review_queues": ReviewQueue,
    "review_queue_items": ReviewQueueItem,
    "active_learning_rounds": ActiveLearningRound,
}


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name.replace("\\", "/"))
    return bool(name) and not path.is_absolute() and ".." not in path.parts


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_stream(source: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = source.read(1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
        total += len(chunk)
    return digest.hexdigest(), total


def _read_jsonl(payload: bytes, section_name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(payload.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError(
                f"Section {section_name} contains invalid JSON on line {line_number}"
            ) from exc
        if not isinstance(value, dict):
            raise ValidationError(f"Section {section_name} must contain JSON objects")
        rows.append(value)
    return rows


def _remap_value(value: object, id_map: dict[str, str], old_root: str, new_root: str) -> object:
    if isinstance(value, str):
        if value in id_map:
            return id_map[value]
        if value == old_root:
            return new_root
        prefix = f"{old_root}/"
        if value.startswith(prefix):
            return f"{new_root}/{value[len(prefix):]}"
        return value
    if isinstance(value, list):
        return [_remap_value(item, id_map, old_root, new_root) for item in value]
    if isinstance(value, dict):
        return {
            id_map.get(str(key), str(key)): _remap_value(item, id_map, old_root, new_root)
            for key, item in value.items()
        }
    return value


def _coerce_datetime(value: object) -> object:
    if not isinstance(value, str):
        return value
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return value


def _coerce_date(value: object) -> object:
    if not isinstance(value, str):
        return value
    try:
        return date.fromisoformat(value)
    except ValueError:
        return value


def _section_order(section_names: set[str]) -> list[str]:
    table_to_section = {
        model.__table__.name: section
        for section, model in SECTION_MODELS.items()
        if section in section_names
    }
    dependencies: dict[str, set[str]] = {}
    for section in section_names:
        if section == "project":
            continue
        model = SECTION_MODELS[section]
        deps: set[str] = set()
        for column in model.__table__.columns:
            for foreign_key in column.foreign_keys:
                target_section = table_to_section.get(foreign_key.column.table.name)
                if target_section and target_section not in {section, "project"}:
                    deps.add(target_section)
        dependencies[section] = deps

    ordered: list[str] = []
    remaining = set(dependencies)
    while remaining:
        ready = sorted(
            section for section in remaining if not (dependencies[section] & remaining)
        )
        if not ready:
            raise ValidationError(
                "Exchange sections contain a dependency cycle that cannot be imported safely"
            )
        ordered.extend(ready)
        remaining.difference_update(ready)
    return ordered


class ProjectExchangeImportService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _unique_slug(self, name: str) -> str:
        base = slugify(name)
        candidate = base
        suffix = 2
        while self.session.scalar(select(Project.id).where(Project.slug == candidate)) is not None:
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    def _load_archive(
        self,
        source: BinaryIO,
    ) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], list[str]]:
        source.seek(0)
        try:
            with zipfile.ZipFile(source, "r") as archive:
                infos = archive.infolist()
                if len(infos) > MAX_ARCHIVE_MEMBERS:
                    raise ValidationError("Archive contains too many files")
                if sum(item.file_size for item in infos) > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                    raise ValidationError("Archive expands beyond the 100 GB import limit")
                if any(not _safe_member(item.filename) for item in infos):
                    raise ValidationError("Archive contains unsafe paths")
                names = {item.filename for item in infos}
                if MANIFEST_NAME not in names:
                    raise ValidationError("ReefVision exchange manifest is missing")
                try:
                    manifest = json.loads(archive.read(MANIFEST_NAME))
                except json.JSONDecodeError as exc:
                    raise ValidationError("ReefVision exchange manifest is invalid JSON") from exc
                if not isinstance(manifest, dict) or manifest.get("format_name") != FORMAT_NAME:
                    raise ValidationError("Archive is not a ReefVision project exchange package")
                version = str(manifest.get("format_version", ""))
                if version.split(".", 1)[0] != FORMAT_MAJOR:
                    raise ValidationError("Exchange format major version is incompatible")
                sections = manifest.get("sections")
                if not isinstance(sections, dict):
                    raise ValidationError("Exchange manifest sections are invalid")

                unknown = sorted(set(sections) - set(SECTION_MODELS))
                if unknown:
                    raise ValidationError(
                        "Exchange contains unsupported persisted sections: " + ", ".join(unknown)
                    )
                rows: dict[str, list[dict[str, Any]]] = {}
                warnings: list[str] = []
                for section_name, descriptor in sections.items():
                    if not isinstance(descriptor, dict):
                        raise ValidationError(
                            f"Section descriptor is invalid: {section_name}"
                        )
                    member = str(descriptor.get("path") or "")
                    if not _safe_member(member) or member not in names:
                        raise ValidationError(f"Section file is missing: {section_name}")
                    payload = archive.read(member)
                    if _sha256_bytes(payload) != str(descriptor.get("sha256") or ""):
                        raise ValidationError(f"Section checksum failed: {section_name}")
                    section_rows = _read_jsonl(payload, section_name)
                    if len(section_rows) != int(descriptor.get("count", -1)):
                        raise ValidationError(f"Section row count failed: {section_name}")
                    rows[section_name] = section_rows

                if len(rows.get("project", [])) != 1:
                    raise ValidationError("Exchange package must contain exactly one project row")
                for optional_section in sorted(set(SECTION_MODELS) - set(rows)):
                    if optional_section != "project":
                        warnings.append(
                            f"Optional section not present in this package: {optional_section}"
                        )
                return manifest, rows, warnings
        except zipfile.BadZipFile as exc:
            raise ValidationError("Archive is not a valid ZIP file") from exc

    def _build_id_map(
        self,
        rows: dict[str, list[dict[str, Any]]],
        new_project_id: str,
    ) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
        project_row = rows["project"][0]
        old_project_id = str(project_row.get("id") or "")
        if not old_project_id:
            raise ValidationError("Exchange project row is missing its identifier")
        global_map = {old_project_id: new_project_id}
        section_maps: dict[str, dict[str, str]] = {
            "project": {old_project_id: new_project_id}
        }
        for section_name, section_rows in rows.items():
            if section_name == "project":
                continue
            mapping: dict[str, str] = {}
            model = SECTION_MODELS[section_name]
            id_column = model.__table__.columns.get("id")
            if id_column is not None and id_column.primary_key:
                for row in section_rows:
                    old_id = row.get("id")
                    if isinstance(old_id, str) and old_id:
                        new_id = str(uuid4())
                        mapping[old_id] = new_id
                        global_map[old_id] = new_id
            section_maps[section_name] = mapping
        return global_map, section_maps

    def _prepare_row(
        self,
        section_name: str,
        raw_row: dict[str, Any],
        *,
        global_map: dict[str, str],
        included_tables: set[str],
        old_root: str,
        new_root: str,
    ) -> tuple[dict[str, Any], dict[str, object]]:
        model = SECTION_MODELS[section_name]
        remapped = _remap_value(raw_row, global_map, old_root, new_root)
        assert isinstance(remapped, dict)
        values: dict[str, Any] = {}
        deferred_self_refs: dict[str, object] = {}
        for column in model.__table__.columns:
            if column.name not in remapped:
                continue
            value = remapped[column.name]
            if isinstance(column.type, DateTime):
                value = _coerce_datetime(value)
            elif isinstance(column.type, Date):
                value = _coerce_date(value)

            for foreign_key in column.foreign_keys:
                target_table = foreign_key.column.table.name
                if value is None:
                    continue
                if target_table == model.__table__.name:
                    deferred_self_refs[column.name] = value
                    value = None
                elif target_table not in included_tables:
                    if column.nullable:
                        value = None
                    else:
                        raise ValidationError(
                            f"Section {section_name} requires omitted table {target_table}"
                        )
            values[column.name] = value

        if section_name == "images":
            values["thumbnail_path"] = None
        elif section_name == "videos":
            values["frame_directory_path"] = None
            if "extraction_job_id" in values:
                values["extraction_job_id"] = None
        elif section_name == "training_runs":
            if "job_id" in values:
                values["job_id"] = None
        elif section_name == "classification_datasets":
            manifest_json = values.get("manifest_json")
            if not isinstance(manifest_json, dict):
                raise ValidationError("Classification dataset manifest is invalid")
            values["manifest_sha256"] = canonical_json_sha256(manifest_json)
        return values, deferred_self_refs

    def _copy_media(
        self,
        archive: zipfile.ZipFile,
        manifest: dict[str, Any],
        transformed_rows: dict[str, dict[str, dict[str, Any]]],
    ) -> tuple[int, set[tuple[str, str]]]:
        restored = 0
        restored_keys: set[tuple[str, str]] = set()
        media = manifest.get("media", [])
        if not isinstance(media, list):
            raise ValidationError("Exchange media manifest is invalid")
        names = {item.filename for item in archive.infolist()}
        kind_to_section_path = {
            "image": ("images", "managed_path"),
            "video": ("videos", "managed_path"),
            "model": ("models", "managed_path"),
            "mask": ("mask_annotations", "mask_path"),
            "classification_dataset_archive": (
                "classification_datasets",
                "archive_path",
            ),
            "training_log": ("training_runs", "logs_path"),
            "training_checkpoint": ("training_runs", "result_checkpoint_path"),
        }
        for descriptor in media:
            if not isinstance(descriptor, dict):
                raise ValidationError("Exchange media descriptor is invalid")
            kind = str(descriptor.get("kind") or "")
            mapping = kind_to_section_path.get(kind)
            if mapping is None:
                raise ValidationError(f"Unsupported exchange media kind: {kind}")
            section_name, path_field = mapping
            old_record_id = str(descriptor.get("record_id") or "")
            row = transformed_rows.get(section_name, {}).get(old_record_id)
            if row is None:
                raise ValidationError(
                    f"Media references a missing {section_name} record: {old_record_id}"
                )
            managed_path = row.get(path_field)
            if not isinstance(managed_path, str) or not managed_path:
                raise ValidationError(
                    f"Media record {old_record_id} does not declare {path_field}"
                )
            member = str(descriptor.get("path") or "")
            if not _safe_member(member) or member not in names:
                raise ValidationError(f"Exchange media file is missing: {member}")
            destination = resolve_managed_project_path(self.settings, managed_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(destination.suffix + ".part")
            temporary.unlink(missing_ok=True)
            try:
                with archive.open(member) as input_stream, temporary.open("wb") as output:
                    digest = hashlib.sha256()
                    size = 0
                    while True:
                        chunk = input_stream.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                expected_sha = str(descriptor.get("sha256") or "")
                expected_size = int(descriptor.get("size_bytes", -1))
                if digest.hexdigest() != expected_sha:
                    raise ValidationError(f"Exchange media checksum failed: {member}")
                if size != expected_size:
                    raise ValidationError(f"Exchange media size failed: {member}")
                temporary.replace(destination)
            except Exception:
                temporary.unlink(missing_ok=True)
                destination.unlink(missing_ok=True)
                raise
            restored += 1
            restored_keys.add((kind, old_record_id))
        return restored, restored_keys

    def import_upload(
        self,
        source: BinaryIO,
        *,
        project_name: str | None = None,
    ) -> dict[str, object]:
        manifest, rows, warnings = self._load_archive(source)
        project_row = rows["project"][0]
        old_root = str(project_row.get("storage_root") or "")
        if not old_root:
            raise ValidationError("Exchange project row is missing its storage root")

        imported_name = (project_name or str(project_row.get("name") or "Imported project")).strip()
        if not imported_name:
            imported_name = "Imported project"
        new_project_id = str(uuid4())
        new_root = create_managed_project_directory(self.settings, new_project_id)
        project_directory = resolve_managed_project_path(self.settings, new_root)
        global_map, section_maps = self._build_id_map(rows, new_project_id)
        included_tables = {
            SECTION_MODELS[section].__table__.name for section in rows if section in SECTION_MODELS
        }
        transformed_rows: dict[str, dict[str, dict[str, Any]]] = {}
        deferred_refs: list[tuple[object, str, object]] = []
        restored_files = 0
        package_id = str(uuid4())
        archive_relative = f"{new_root}/exchanges/{package_id}.reefvision.zip"

        try:
            project = Project(
                id=new_project_id,
                name=imported_name,
                slug=self._unique_slug(imported_name),
                description=project_row.get("description"),
                storage_root=new_root,
                default_annotation_type=str(
                    project_row.get("default_annotation_type") or "bbox"
                ),
                created_at=(
                    _coerce_datetime(project_row.get("created_at"))
                    if project_row.get("created_at")
                    else datetime.now(UTC)
                ),
                updated_at=datetime.now(UTC),
                archived_at=None,
            )
            self.session.add(project)
            self.session.flush()

            order = _section_order(set(rows))
            for section_name in order:
                model = SECTION_MODELS[section_name]
                transformed_rows[section_name] = {}
                for raw_row in rows[section_name]:
                    values, self_refs = self._prepare_row(
                        section_name,
                        raw_row,
                        global_map=global_map,
                        included_tables=included_tables,
                        old_root=old_root,
                        new_root=new_root,
                    )
                    instance = model(**values)
                    self.session.add(instance)
                    old_id = raw_row.get("id")
                    if isinstance(old_id, str):
                        transformed_rows[section_name][old_id] = values
                    for column_name, value in self_refs.items():
                        deferred_refs.append((instance, column_name, value))
                self.session.flush()

            for instance, column_name, value in deferred_refs:
                setattr(instance, column_name, value)
            self.session.flush()

            source.seek(0)
            with zipfile.ZipFile(source, "r") as archive:
                restored_files, restored_keys = self._copy_media(
                    archive,
                    manifest,
                    transformed_rows,
                )

                for old_id in transformed_rows.get("images", {}):
                    if ("image", old_id) not in restored_keys:
                        raise ValidationError(
                            "A reopenable import requires original image media; "
                            f"missing image record {old_id}"
                        )
                for old_id in transformed_rows.get("videos", {}):
                    if ("video", old_id) not in restored_keys:
                        raise ValidationError(
                            "A reopenable import requires original video media; "
                            f"missing video record {old_id}"
                        )
                for old_id, row in transformed_rows.get("mask_annotations", {}).items():
                    if row.get("mask_path") and ("mask", old_id) not in restored_keys:
                        raise ValidationError(
                            "A raster-mask annotation is missing its packaged mask artifact"
                        )
                for old_id, row in transformed_rows.get(
                    "classification_datasets", {}
                ).items():
                    if ("classification_dataset_archive", old_id) not in restored_keys:
                        raise ValidationError(
                            "A classification dataset is missing its packaged materialization archive"
                        )
                    archive_path_value = row.get("archive_path")
                    output_path_value = row.get("output_path")
                    manifest_json = row.get("manifest_json")
                    manifest_sha256 = row.get("manifest_sha256")
                    if (
                        not isinstance(archive_path_value, str)
                        or not isinstance(output_path_value, str)
                        or not isinstance(manifest_json, dict)
                        or not isinstance(manifest_sha256, str)
                    ):
                        raise ValidationError(
                            "Classification dataset paths or manifest are invalid after remapping"
                        )
                    restore_classification_dataset_materialization(
                        archive_path=resolve_managed_project_path(
                            self.settings,
                            archive_path_value,
                        ),
                        output_path=resolve_managed_project_path(
                            self.settings,
                            output_path_value,
                        ),
                        manifest_json=manifest_json,
                        manifest_sha256=manifest_sha256,
                        sample_count=int(row.get("sample_count", 0)),
                    )
                for old_id, row in transformed_rows.get("models", {}).items():
                    if ("model", old_id) not in restored_keys:
                        metadata = dict(row.get("metadata_json") or {})
                        metadata["exchange_weight_missing"] = True
                        metadata["exchange_weight_missing_reason"] = (
                            "Source package did not include model weights"
                        )
                        row["metadata_json"] = metadata
                        instance_id = section_maps.get("models", {}).get(old_id)
                        if instance_id:
                            model_record = self.session.get(ModelRegistration, instance_id)
                            if model_record is not None:
                                model_record.metadata_json = metadata
                        warnings.append(
                            f"Model metadata restored without checkpoint weights: {old_id}"
                        )

            archive_path = resolve_managed_project_path(self.settings, archive_relative)
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_archive = archive_path.with_suffix(archive_path.suffix + ".part")
            source.seek(0)
            with temporary_archive.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            temporary_archive.replace(archive_path)

            package = ProjectExchangePackage(
                id=package_id,
                project_id=new_project_id,
                job_id=None,
                direction="import",
                status="complete",
                format_version=str(manifest.get("format_version") or ""),
                manifest_json=manifest,
                manifest_sha256=canonical_json_sha256(manifest),
                archive_path=archive_relative,
                options_json={
                    "source_project_id": project_row.get("id"),
                    "source_project_name": project_row.get("name"),
                    "id_remapping": True,
                    "warnings": warnings,
                },
                error_message=None,
                completed_at=datetime.now(UTC),
            )
            self.session.add(package)
            self.session.commit()
            return {
                "project_id": new_project_id,
                "project_name": imported_name,
                "package_id": package_id,
                "format_version": package.format_version,
                "manifest_sha256": package.manifest_sha256,
                "remapped_id_count": len(global_map),
                "restored_file_count": restored_files,
                "warnings": warnings,
            }
        except Exception:
            self.session.rollback()
            shutil.rmtree(project_directory, ignore_errors=True)
            raise
