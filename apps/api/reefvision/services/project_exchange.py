"""Versioned, checksummed ReefVision project exchange packages."""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections.abc import BinaryIO, Iterable
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision import __version__
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
    Job,
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
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.project_exchange import (
    ProjectExchangeCreateRequest,
    ProjectExchangeCreateResponse,
    ProjectExchangeInspectionResponse,
    ProjectExchangePackageResponse,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path

FORMAT_NAME = "reefvision-project-exchange"
FORMAT_VERSION = "1.0"
MANIFEST_NAME = "reefvision-exchange-manifest.json"


def _json_value(value: object) -> object:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    return value


def _row(instance: object) -> dict[str, object]:
    table = getattr(instance, "__table__")
    return {
        column.name: _json_value(getattr(instance, column.name))
        for column in table.columns
    }


def _jsonl_bytes(rows: Iterable[dict[str, object]]) -> bytes:
    return b"".join(
        (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        for row in rows
    )


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name.replace("\\", "/"))
    return bool(name) and not path.is_absolute() and ".." not in path.parts


class ProjectExchangeService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _package(self, package_id: str) -> ProjectExchangePackage:
        package = self.session.get(ProjectExchangePackage, package_id)
        if package is None:
            raise NotFoundError("Project exchange package not found")
        return package

    def list_packages(self, project_id: str) -> list[ProjectExchangePackageResponse]:
        self._project(project_id)
        statement = (
            select(ProjectExchangePackage)
            .where(ProjectExchangePackage.project_id == project_id)
            .order_by(ProjectExchangePackage.created_at.desc(), ProjectExchangePackage.id)
        )
        return [
            ProjectExchangePackageResponse.model_validate(item)
            for item in self.session.scalars(statement)
        ]

    def get_package(self, package_id: str) -> ProjectExchangePackageResponse:
        return ProjectExchangePackageResponse.model_validate(self._package(package_id))

    def queue_export(
        self,
        project_id: str,
        request: ProjectExchangeCreateRequest,
    ) -> ProjectExchangeCreateResponse:
        project = self._project(project_id)
        package_id = str(uuid4())
        archive_relative = f"{project.storage_root}/exchanges/{package_id}.reefvision.zip"
        package = ProjectExchangePackage(
            id=package_id,
            project_id=project.id,
            direction="export",
            status="queued",
            format_version=FORMAT_VERSION,
            manifest_json={},
            manifest_sha256="",
            archive_path=archive_relative,
            options_json=request.model_dump(mode="json"),
        )
        self.session.add(package)
        job = Job(
            project_id=project.id,
            job_type="project_exchange_export",
            status="queued",
            progress_total=1,
            request_json={"package_id": package.id},
        )
        self.session.add(job)
        self.session.flush()
        package.job_id = job.id
        self.session.commit()
        self.session.refresh(package)
        return ProjectExchangeCreateResponse(
            package=ProjectExchangePackageResponse.model_validate(package),
            job_id=job.id,
        )

    def archive_path(self, package_id: str) -> Path:
        package = self._package(package_id)
        if package.status != "complete":
            raise ValidationError("Only completed exchange packages can be downloaded")
        path = resolve_managed_project_path(self.settings, package.archive_path)
        if not path.is_file():
            raise NotFoundError("Project exchange archive is missing")
        return path

    def _records(self, project: Project) -> dict[str, list[object]]:
        image_ids = list(
            self.session.scalars(select(ImageAsset.id).where(ImageAsset.project_id == project.id))
        )
        annotation_ids = (
            list(
                self.session.scalars(
                    select(Annotation.id).where(Annotation.image_id.in_(image_ids))
                )
            )
            if image_ids
            else []
        )
        mask_annotation_ids = (
            list(
                self.session.scalars(
                    select(MaskAnnotation.id).where(MaskAnnotation.image_id.in_(image_ids))
                )
            )
            if image_ids
            else []
        )
        video_ids = list(
            self.session.scalars(select(VideoAsset.id).where(VideoAsset.project_id == project.id))
        )
        version_ids = list(
            self.session.scalars(
                select(DatasetVersion.id).where(DatasetVersion.project_id == project.id)
            )
        )
        sections: dict[str, list[object]] = {
            "project": [project],
            "label_classes": list(
                self.session.scalars(
                    select(LabelClass).where(LabelClass.project_id == project.id)
                )
            ),
            "class_operations": list(
                self.session.scalars(
                    select(ClassOperation).where(ClassOperation.project_id == project.id)
                )
            ),
            "project_class_visibility_defaults": list(
                self.session.scalars(
                    select(ProjectClassVisibilityDefault).where(
                        ProjectClassVisibilityDefault.project_id == project.id
                    )
                )
            ),
            "class_visibility_preferences": list(
                self.session.scalars(
                    select(ClassVisibilityPreference).where(
                        ClassVisibilityPreference.project_id == project.id
                    )
                )
            ),
            "images": list(
                self.session.scalars(
                    select(ImageAsset).where(ImageAsset.project_id == project.id)
                )
            ),
            "annotations": (
                list(
                    self.session.scalars(
                        select(Annotation).where(Annotation.image_id.in_(image_ids))
                    )
                )
                if image_ids
                else []
            ),
            "annotation_events": (
                list(
                    self.session.scalars(
                        select(AnnotationEvent).where(
                            AnnotationEvent.annotation_id.in_(annotation_ids)
                        )
                    )
                )
                if annotation_ids
                else []
            ),
            "mask_annotations": (
                list(
                    self.session.scalars(
                        select(MaskAnnotation).where(MaskAnnotation.image_id.in_(image_ids))
                    )
                )
                if image_ids
                else []
            ),
            "mask_annotation_events": (
                list(
                    self.session.scalars(
                        select(MaskAnnotationEvent).where(
                            MaskAnnotationEvent.mask_annotation_id.in_(mask_annotation_ids)
                        )
                    )
                )
                if mask_annotation_ids
                else []
            ),
            "image_labels": (
                list(
                    self.session.scalars(
                        select(ImageLabel).where(ImageLabel.image_id.in_(image_ids))
                    )
                )
                if image_ids
                else []
            ),
            "prediction_proposals": list(
                self.session.scalars(
                    select(PredictionProposal).where(PredictionProposal.project_id == project.id)
                )
            ),
            "classification_predictions": list(
                self.session.scalars(
                    select(ClassificationPrediction).where(
                        ClassificationPrediction.project_id == project.id
                    )
                )
            ),
            "classification_datasets": list(
                self.session.scalars(
                    select(ClassificationDataset).where(
                        ClassificationDataset.project_id == project.id
                    )
                )
            ),
            "videos": list(
                self.session.scalars(
                    select(VideoAsset).where(VideoAsset.project_id == project.id)
                )
            ),
            "video_tracks": (
                list(
                    self.session.scalars(
                        select(VideoTrack).where(VideoTrack.video_id.in_(video_ids))
                    )
                )
                if video_ids
                else []
            ),
            "dataset_versions": list(
                self.session.scalars(
                    select(DatasetVersion).where(DatasetVersion.project_id == project.id)
                )
            ),
            "dataset_version_items": (
                list(
                    self.session.scalars(
                        select(DatasetVersionItem).where(
                            DatasetVersionItem.dataset_version_id.in_(version_ids)
                        )
                    )
                )
                if version_ids
                else []
            ),
            "models": list(
                self.session.scalars(
                    select(ModelRegistration).where(ModelRegistration.project_id == project.id)
                )
            ),
            "training_drafts": list(
                self.session.scalars(
                    select(TrainingDraft).where(TrainingDraft.project_id == project.id)
                )
            ),
            "training_runs": list(
                self.session.scalars(
                    select(TrainingRun).where(TrainingRun.project_id == project.id)
                )
            ),
            "experiments": list(
                self.session.scalars(
                    select(ExperimentRecord).where(ExperimentRecord.project_id == project.id)
                )
            ),
            "quality_control_runs": list(
                self.session.scalars(
                    select(QualityControlRun).where(QualityControlRun.project_id == project.id)
                )
            ),
            "quality_control_issues": list(
                self.session.scalars(
                    select(QualityControlIssue).where(QualityControlIssue.project_id == project.id)
                )
            ),
            "review_queues": list(
                self.session.scalars(
                    select(ReviewQueue).where(ReviewQueue.project_id == project.id)
                )
            ),
            "review_queue_items": list(
                self.session.scalars(
                    select(ReviewQueueItem).where(ReviewQueueItem.project_id == project.id)
                )
            ),
            "active_learning_rounds": list(
                self.session.scalars(
                    select(ActiveLearningRound).where(
                        ActiveLearningRound.project_id == project.id
                    )
                )
            ),
        }
        return sections

    def _archive_file(
        self,
        archive: zipfile.ZipFile,
        *,
        source: Path,
        member: str,
        kind: str,
        record_id: str,
        known_sha256: str | None = None,
    ) -> dict[str, object]:
        if not source.is_file():
            raise ValidationError(f"Managed exchange artifact is missing: {source.name}")
        sha256, size = _sha256_file(source)
        if known_sha256 is not None and sha256 != known_sha256:
            raise ValidationError(f"Managed exchange artifact checksum changed: {source.name}")
        archive.write(source, member)
        return {
            "kind": kind,
            "record_id": record_id,
            "path": member,
            "sha256": sha256,
            "size_bytes": size,
        }

    def build_export(self, package_id: str) -> ProjectExchangePackageResponse:
        package = self._package(package_id)
        project = self._project(package.project_id)
        options = dict(package.options_json)
        include_media = bool(options.get("include_media", False))
        include_model_weights = bool(options.get("include_model_weights", False))
        include_generated_artifacts = bool(options.get("include_generated_artifacts", False))
        archive_path = resolve_managed_project_path(self.settings, package.archive_path)
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = archive_path.with_suffix(archive_path.suffix + ".part")
        temporary.unlink(missing_ok=True)
        archive_path.unlink(missing_ok=True)

        sections = self._records(project)
        section_manifest: dict[str, dict[str, object]] = {}
        media_manifest: list[dict[str, object]] = []
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for section_name, records in sections.items():
                    ordered = sorted(records, key=lambda item: str(getattr(item, "id", "")))
                    payload = _jsonl_bytes(_row(item) for item in ordered)
                    member = f"records/{section_name}.jsonl"
                    archive.writestr(member, payload)
                    section_manifest[section_name] = {
                        "path": member,
                        "count": len(ordered),
                        "sha256": _sha256_bytes(payload),
                    }

                if include_media:
                    for image in sections["images"]:
                        source = resolve_managed_project_path(self.settings, image.managed_path)
                        member = f"media/images/{image.id}{source.suffix.lower()}"
                        media_manifest.append(
                            self._archive_file(
                                archive,
                                source=source,
                                member=member,
                                kind="image",
                                record_id=image.id,
                                known_sha256=image.sha256,
                            )
                        )
                    for video in sections["videos"]:
                        source = resolve_managed_project_path(self.settings, video.managed_path)
                        member = f"media/videos/{video.id}{source.suffix.lower()}"
                        media_manifest.append(
                            self._archive_file(
                                archive,
                                source=source,
                                member=member,
                                kind="video",
                                record_id=video.id,
                                known_sha256=video.sha256,
                            )
                        )

                if include_model_weights:
                    for model in sections["models"]:
                        source = resolve_managed_project_path(self.settings, model.managed_path)
                        member = f"models/{model.id}{source.suffix.lower()}"
                        media_manifest.append(
                            self._archive_file(
                                archive,
                                source=source,
                                member=member,
                                kind="model",
                                record_id=model.id,
                                known_sha256=model.sha256,
                            )
                        )

                if include_generated_artifacts:
                    for mask in sections["mask_annotations"]:
                        if not mask.mask_path:
                            continue
                        source = resolve_managed_project_path(self.settings, mask.mask_path)
                        member = f"artifacts/masks/{mask.id}{source.suffix.lower()}"
                        media_manifest.append(
                            self._archive_file(
                                archive,
                                source=source,
                                member=member,
                                kind="mask",
                                record_id=mask.id,
                            )
                        )
                    for dataset in sections["classification_datasets"]:
                        source = resolve_managed_project_path(self.settings, dataset.archive_path)
                        member = f"artifacts/classification/{dataset.id}.zip"
                        media_manifest.append(
                            self._archive_file(
                                archive,
                                source=source,
                                member=member,
                                kind="classification_dataset_archive",
                                record_id=dataset.id,
                            )
                        )
                    for training_run in sections["training_runs"]:
                        if training_run.logs_path:
                            source = resolve_managed_project_path(
                                self.settings, training_run.logs_path
                            )
                            member = f"artifacts/training/{training_run.id}/logs{source.suffix.lower()}"
                            media_manifest.append(
                                self._archive_file(
                                    archive,
                                    source=source,
                                    member=member,
                                    kind="training_log",
                                    record_id=training_run.id,
                                )
                            )
                        if training_run.result_checkpoint_path:
                            source = resolve_managed_project_path(
                                self.settings, training_run.result_checkpoint_path
                            )
                            member = (
                                f"artifacts/training/{training_run.id}/checkpoint"
                                f"{source.suffix.lower()}"
                            )
                            media_manifest.append(
                                self._archive_file(
                                    archive,
                                    source=source,
                                    member=member,
                                    kind="training_checkpoint",
                                    record_id=training_run.id,
                                )
                            )

                manifest = {
                    "format_name": FORMAT_NAME,
                    "format_version": FORMAT_VERSION,
                    "application_version": __version__,
                    "project": {
                        "id": project.id,
                        "name": project.name,
                        "slug": project.slug,
                    },
                    "options": options,
                    "sections": section_manifest,
                    "media": media_manifest,
                    "import_policy": {
                        "mode": "create_new_project",
                        "id_remapping_required": True,
                        "existing_projects_must_not_be_overwritten": True,
                    },
                }
                manifest_bytes = json.dumps(
                    manifest,
                    indent=2,
                    sort_keys=True,
                ).encode("utf-8")
                archive.writestr(MANIFEST_NAME, manifest_bytes)
            temporary.replace(archive_path)
            package.status = "complete"
            package.manifest_json = manifest
            package.manifest_sha256 = canonical_json_sha256(manifest)
            package.completed_at = datetime.now().astimezone()
            package.error_message = None
            self.session.commit()
            self.session.refresh(package)
            return ProjectExchangePackageResponse.model_validate(package)
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            archive_path.unlink(missing_ok=True)
            package.status = "failed"
            package.error_message = str(exc)
            self.session.commit()
            raise

    def inspect_upload(self, source: BinaryIO) -> ProjectExchangeInspectionResponse:
        warnings: list[str] = []
        errors: list[str] = []
        section_counts: dict[str, int] = {}
        manifest: dict[str, Any] | None = None
        try:
            with zipfile.ZipFile(source, "r") as archive:
                infos = archive.infolist()
                if len(infos) > 100_000:
                    errors.append("Archive contains too many files")
                if sum(item.file_size for item in infos) > 100 * 1024**3:
                    errors.append("Archive expands beyond the 100 GB inspection limit")
                unsafe = [item.filename for item in infos if not _safe_member(item.filename)]
                if unsafe:
                    errors.append("Archive contains unsafe paths")
                names = {item.filename for item in infos}
                if MANIFEST_NAME not in names:
                    errors.append("ReefVision exchange manifest is missing")
                if errors:
                    return ProjectExchangeInspectionResponse(
                        compatible=False,
                        format_name=None,
                        format_version=None,
                        application_version=None,
                        manifest_sha256=None,
                        project_name=None,
                        section_counts={},
                        included_media_count=0,
                        warnings=warnings,
                        errors=errors,
                    )
                manifest = json.loads(archive.read(MANIFEST_NAME))
                if manifest.get("format_name") != FORMAT_NAME:
                    errors.append("Archive is not a ReefVision project exchange package")
                version = str(manifest.get("format_version", ""))
                if version.split(".", 1)[0] != FORMAT_VERSION.split(".", 1)[0]:
                    errors.append("Exchange format major version is incompatible")
                sections = manifest.get("sections", {})
                if not isinstance(sections, dict):
                    errors.append("Manifest sections are invalid")
                    sections = {}
                for name, descriptor in sections.items():
                    if not isinstance(descriptor, dict):
                        errors.append(f"Section descriptor is invalid: {name}")
                        continue
                    member = str(descriptor.get("path", ""))
                    if member not in names:
                        errors.append(f"Section file is missing: {name}")
                        continue
                    payload = archive.read(member)
                    if _sha256_bytes(payload) != descriptor.get("sha256"):
                        errors.append(f"Section checksum failed: {name}")
                    lines = [line for line in payload.splitlines() if line.strip()]
                    section_counts[str(name)] = len(lines)
                    if len(lines) != int(descriptor.get("count", -1)):
                        errors.append(f"Section row count failed: {name}")
                media = manifest.get("media", [])
                if not isinstance(media, list):
                    errors.append("Manifest media list is invalid")
                    media = []
                for descriptor in media:
                    if not isinstance(descriptor, dict):
                        errors.append("Media descriptor is invalid")
                        continue
                    member = str(descriptor.get("path", ""))
                    if not _safe_member(member) or member not in names:
                        errors.append(f"Media file is missing or unsafe: {member}")
                        continue
                    digest = hashlib.sha256()
                    size = 0
                    with archive.open(member) as input_stream:
                        while True:
                            chunk = input_stream.read(1024 * 1024)
                            if not chunk:
                                break
                            digest.update(chunk)
                            size += len(chunk)
                    if digest.hexdigest() != str(descriptor.get("sha256") or ""):
                        errors.append(f"Media checksum failed: {member}")
                    if size != int(descriptor.get("size_bytes", -1)):
                        errors.append(f"Media size failed: {member}")
                if not media:
                    warnings.append(
                        "Package does not include original media; a reopenable import requires relinking or a media-inclusive export"
                    )
        except (zipfile.BadZipFile, json.JSONDecodeError, OSError) as exc:
            errors.append(f"Archive could not be inspected: {exc}")

        return ProjectExchangeInspectionResponse(
            compatible=not errors,
            format_name=str(manifest.get("format_name")) if manifest else None,
            format_version=str(manifest.get("format_version")) if manifest else None,
            application_version=str(manifest.get("application_version")) if manifest else None,
            manifest_sha256=canonical_json_sha256(manifest) if manifest else None,
            project_name=(
                str(manifest.get("project", {}).get("name"))
                if manifest and isinstance(manifest.get("project"), dict)
                else None
            ),
            section_counts=section_counts,
            included_media_count=(
                len(manifest.get("media", []))
                if manifest and isinstance(manifest.get("media"), list)
                else 0
            ),
            warnings=warnings,
            errors=errors,
        )
