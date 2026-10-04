"""ReefVision 1.0 project-exchange extensions.

The Phase 9 exporter predates executable workflow graphs. This subclass keeps the
stable archive builder while extending the record inventory with the provenance
objects required to reproduce 1.0 workflows.
"""

from __future__ import annotations

import json
import zipfile
from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path
from typing import Protocol, cast

from sqlalchemy import select

from reefvision.db.base import Base
from reefvision.db.models import (
    AnnotationEvent,
    ClassOperation,
    ClassVisibilityPreference,
    ExportRecord,
    GeoReferencedObservation,
    ImageAsset,
    Job,
    MaskAnnotationEvent,
    Project,
    ProjectClassVisibilityDefault,
    TrainingDraft,
    VideoAsset,
    WorkflowArtifact,
    WorkflowGraphRecord,
    WorkflowNodeRun,
    WorkflowRun,
)
from reefvision.db.models.pose_active_learning import (
    PoseActiveLearningCandidate,
    PoseActiveLearningRound,
)
from reefvision.db.models.pose_schema import (
    PoseLandmarkSchema,
    PoseLandmarkSchemaRevision,
)
from reefvision.db.models.pose_tracking import PoseLandmarkCorrection
from reefvision.db.models.pose_training_dataset import (
    PoseTrainingDataset,
    PoseTrainingDatasetItem,
)
from reefvision.schemas.project_exchange import ProjectExchangePackageResponse
from reefvision.services.project_exchange import MANIFEST_NAME, ProjectExchangeService
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path


class _IdentifiedRecord(Protocol):
    id: str


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parent_first_review_queues(records: Sequence[Base]) -> list[Base]:
    """Order regenerated review queues after the queue they reference."""

    by_id = {str(cast(_IdentifiedRecord, record).id): record for record in records}
    remaining = set(by_id)
    emitted: set[str] = set()
    ordered: list[Base] = []
    while remaining:
        ready = sorted(
            record_id
            for record_id in remaining
            if not isinstance(getattr(by_id[record_id], "regenerated_from_queue_id", None), str)
            or getattr(by_id[record_id], "regenerated_from_queue_id", None) not in remaining
        )
        if not ready:
            # A cycle would be invalid queue provenance. Preserve deterministic output
            # so inspection/import can surface the database problem rather than loop.
            ready = sorted(remaining)
        for record_id in ready:
            ordered.append(by_id[record_id])
            emitted.add(record_id)
            remaining.remove(record_id)
    return ordered


class ProjectExchangeV1Service(ProjectExchangeService):
    """Project exchange service with executable-workflow provenance included."""

    def _records(self, project: Project) -> dict[str, Sequence[Base]]:
        sections = super()._records(project)
        review_queues = sections.get("review_queues")
        if review_queues:
            sections["review_queues"] = _parent_first_review_queues(review_queues)
        image_ids = [item.id for item in cast(Sequence[ImageAsset], sections.get("images", []))]
        workflow_runs = list(
            self.session.scalars(select(WorkflowRun).where(WorkflowRun.project_id == project.id))
        )
        workflow_run_ids = [item.id for item in workflow_runs]
        workflow_node_runs = (
            list(
                self.session.scalars(
                    select(WorkflowNodeRun).where(
                        WorkflowNodeRun.workflow_run_id.in_(workflow_run_ids)
                    )
                )
            )
            if workflow_run_ids
            else []
        )
        annotation_events = (
            list(
                self.session.scalars(
                    select(AnnotationEvent).where(AnnotationEvent.image_id.in_(image_ids))
                )
            )
            if image_ids
            else []
        )
        mask_annotation_events = (
            list(
                self.session.scalars(
                    select(MaskAnnotationEvent).where(MaskAnnotationEvent.image_id.in_(image_ids))
                )
            )
            if image_ids
            else []
        )
        georeferenced_observations = list(
            self.session.scalars(
                select(GeoReferencedObservation).where(
                    GeoReferencedObservation.project_id == project.id
                )
            )
        )
        sections.update(
            {
                "jobs": list(
                    self.session.scalars(
                        select(Job).where(
                            Job.project_id == project.id,
                            Job.job_type != "project_exchange_export",
                        )
                    )
                ),
                "training_drafts": list(
                    self.session.scalars(
                        select(TrainingDraft).where(TrainingDraft.project_id == project.id)
                    )
                ),
                "annotation_events": annotation_events,
                "mask_annotation_events": mask_annotation_events,
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
                "class_operations": list(
                    self.session.scalars(
                        select(ClassOperation).where(ClassOperation.project_id == project.id)
                    )
                ),
                "exports": list(
                    self.session.scalars(
                        select(ExportRecord).where(ExportRecord.project_id == project.id)
                    )
                ),
                "georeferenced_observations": georeferenced_observations,
                "workflow_graphs": list(
                    self.session.scalars(
                        select(WorkflowGraphRecord).where(
                            WorkflowGraphRecord.project_id == project.id
                        )
                    )
                ),
                "workflow_runs": workflow_runs,
                "workflow_node_runs": workflow_node_runs,
                "workflow_artifacts": (
                    list(
                        self.session.scalars(
                            select(WorkflowArtifact).where(
                                WorkflowArtifact.workflow_run_id.in_(workflow_run_ids)
                            )
                        )
                    )
                    if workflow_run_ids
                    else []
                ),
            }
        )

        pose_schemas = list(
            self.session.scalars(
                select(PoseLandmarkSchema).where(PoseLandmarkSchema.project_id == project.id)
            )
        )
        pose_schema_ids = [item.id for item in pose_schemas]

        pose_schema_revisions = (
            list(
                self.session.scalars(
                    select(PoseLandmarkSchemaRevision).where(
                        PoseLandmarkSchemaRevision.schema_id.in_(pose_schema_ids)
                    )
                )
            )
            if pose_schema_ids
            else []
        )

        pose_active_learning_rounds = list(
            self.session.scalars(
                select(PoseActiveLearningRound).where(
                    PoseActiveLearningRound.project_id == project.id
                )
            )
        )
        pose_round_ids = [item.id for item in pose_active_learning_rounds]

        pose_active_learning_candidates = (
            list(
                self.session.scalars(
                    select(PoseActiveLearningCandidate).where(
                        PoseActiveLearningCandidate.round_id.in_(pose_round_ids)
                    )
                )
            )
            if pose_round_ids
            else []
        )

        correction_ids = [
            item.correction_id
            for item in pose_active_learning_candidates
            if item.correction_id is not None
        ]

        pose_landmark_corrections = (
            list(
                self.session.scalars(
                    select(PoseLandmarkCorrection).where(
                        PoseLandmarkCorrection.id.in_(correction_ids)
                    )
                )
            )
            if correction_ids
            else []
        )

        pose_training_datasets = list(
            self.session.scalars(
                select(PoseTrainingDataset).where(PoseTrainingDataset.project_id == project.id)
            )
        )

        pose_training_dataset_ids = [item.id for item in pose_training_datasets]

        pose_training_dataset_items = (
            list(
                self.session.scalars(
                    select(PoseTrainingDatasetItem).where(
                        PoseTrainingDatasetItem.dataset_id.in_(pose_training_dataset_ids)
                    )
                )
            )
            if pose_training_dataset_ids
            else []
        )

        sections.update(
            {
                "pose_landmark_schemas": pose_schemas,
                "pose_landmark_schema_revisions": pose_schema_revisions,
                "pose_active_learning_rounds": pose_active_learning_rounds,
                "pose_landmark_corrections": pose_landmark_corrections,
                "pose_active_learning_candidates": (pose_active_learning_candidates),
                "pose_training_datasets": pose_training_datasets,
                "pose_training_dataset_items": (pose_training_dataset_items),
            }
        )

        return sections

    def _telemetry_sidecars(
        self,
        project: Project,
        records: Mapping[str, Sequence[Base]],
    ) -> list[tuple[dict[str, object], Path]]:
        """Collect persisted SRT/AirData sources needed to reproduce georeferencing."""

        result: list[tuple[dict[str, object], Path]] = []

        for video in cast(
            Sequence[VideoAsset],
            records.get("videos", []),
        ):
            metadata = dict(video.metadata_json or {})

            for metadata_key, sidecar_kind in (
                ("telemetry", "dji_srt"),
                ("airdata_telemetry", "airdata_csv"),
            ):
                raw = metadata.get(metadata_key)

                if not isinstance(raw, dict):
                    continue

                if not bool(raw.get("available", False)):
                    continue

                source_value = raw.get("source_path")

                if not isinstance(source_value, str) or not source_value.strip():
                    continue

                source_path_value = source_value.strip()
                path_kind = str(raw.get("path_kind") or "managed")

                if path_kind == "external":
                    source_path = Path(source_path_value)
                else:
                    source_path = resolve_managed_project_path(
                        self.settings,
                        source_path_value,
                    )

                if not source_path.is_file():
                    raise FileNotFoundError(
                        f"Georeferencing telemetry sidecar is missing: {source_path_value}"
                    )

                suffix = source_path.suffix.lower()

                if not suffix:
                    suffix = ".srt" if metadata_key == "telemetry" else ".csv"

                restore_relative = f"videos/telemetry/{video.id}-{metadata_key}{suffix}"

                archive_member = f"telemetry/{video.id}/{metadata_key}{suffix}"

                descriptor: dict[str, object] = {
                    "kind": sidecar_kind,
                    "video_id": video.id,
                    "metadata_key": metadata_key,
                    "source_path": source_path_value,
                    "source_relative_path": restore_relative,
                    "path": archive_member,
                    "sha256": _file_sha256(source_path),
                    "size_bytes": source_path.stat().st_size,
                }

                result.append(
                    (
                        descriptor,
                        source_path,
                    )
                )

        return result

    def _generated_artifacts(
        self,
        project: Project,
        records: Mapping[str, Sequence[Base]],
    ) -> list[tuple[dict[str, object], Path]]:
        if not records:
            return []
        original_paths: set[str] = set()

        for video in cast(
            Sequence[VideoAsset],
            records.get("videos", []),
        ):
            metadata = dict(video.metadata_json or {})

            for metadata_key in (
                "telemetry",
                "airdata_telemetry",
            ):
                raw = metadata.get(metadata_key)

                if not isinstance(raw, dict):
                    continue

                if str(raw.get("path_kind") or "managed") != "managed":
                    continue

                source_path = raw.get("source_path")

                if isinstance(source_path, str) and source_path.strip():
                    original_paths.add(source_path.strip())

        for section_name in ("images", "videos", "models"):
            for record in records.get(section_name, []):
                managed_path = getattr(record, "managed_path", None)
                if isinstance(managed_path, str):
                    original_paths.add(managed_path)

        project_root = resolve_managed_project_path(self.settings, project.storage_root)
        exchange_prefix = project.storage_root.rstrip("/") + "/exchanges/"
        generated: list[tuple[dict[str, object], Path]] = []
        for path in sorted(
            (candidate for candidate in project_root.rglob("*") if candidate.is_file()),
            key=lambda item: item.as_posix(),
        ):
            relative_to_data = path.relative_to(self.settings.resolved_data_dir).as_posix()
            if relative_to_data in original_paths:
                continue
            if relative_to_data.startswith(exchange_prefix):
                continue
            relative_to_project = path.relative_to(project_root).as_posix()
            descriptor: dict[str, object] = {
                "kind": "generated",
                "source_relative_path": relative_to_project,
                "path": f"generated/{relative_to_project}",
                "sha256": _file_sha256(path),
                "size_bytes": path.stat().st_size,
            }
            generated.append((descriptor, path))
        return generated

    def build_export(self, package_id: str) -> ProjectExchangePackageResponse:
        """Build a complete 1.0 archive and advertise its safe round-trip policy."""

        super().build_export(package_id)
        package = self._package(package_id)
        project = self._project(package.project_id)
        manifest = dict(package.manifest_json)
        records = self._records(project)
        telemetry_sidecars = self._telemetry_sidecars(
            project,
            records,
        )
        generated = (
            self._generated_artifacts(project, records)
            if bool(package.options_json.get("include_generated_artifacts", False))
            else []
        )
        manifest["telemetry_sidecars"] = [descriptor for descriptor, _ in telemetry_sidecars]
        manifest["generated_artifacts"] = [descriptor for descriptor, _ in generated]
        manifest["import_policy"] = {
            "mode": "import_as_new_project",
            "id_remapping_required": True,
            "existing_projects_must_not_be_overwritten": True,
            "source_ids_are_preserved_in_import_provenance": True,
        }

        archive_path = resolve_managed_project_path(self.settings, package.archive_path)
        temporary = archive_path.with_suffix(archive_path.suffix + ".manifest.part")
        temporary.unlink(missing_ok=True)
        try:
            with (
                zipfile.ZipFile(archive_path, "r") as source_archive,
                zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as target_archive,
            ):
                for info in source_archive.infolist():
                    if info.filename == MANIFEST_NAME:
                        continue
                    target_archive.writestr(info, source_archive.read(info.filename))
                for descriptor, source_path in telemetry_sidecars:
                    target_archive.write(
                        source_path,
                        arcname=str(descriptor["path"]),
                    )

                for descriptor, source_path in generated:
                    target_archive.write(
                        source_path,
                        arcname=str(descriptor["path"]),
                    )
                target_archive.writestr(
                    MANIFEST_NAME,
                    json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"),
                )
            temporary.replace(archive_path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

        package.manifest_json = manifest
        package.manifest_sha256 = canonical_json_sha256(manifest)
        self.session.commit()
        self.session.refresh(package)
        return ProjectExchangePackageResponse.model_validate(package)
