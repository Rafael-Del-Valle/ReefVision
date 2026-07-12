"""Dataset-version snapshot, comparison, and export services."""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from math import floor
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from reefvision import __version__
from reefvision.config import Settings
from reefvision.db.models import (
    Annotation,
    DatasetVersion,
    DatasetVersionItem,
    ExportRecord,
    ImageAsset,
    Job,
    Project,
)
from reefvision.db.models.project import utc_now
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.repositories.dataset_versions import DatasetVersionRepository, ExportRepository
from reefvision.repositories.projects import ProjectRepository
from reefvision.schemas.dataset_versions import (
    DatasetExportCreateRequest,
    DatasetExportCreateResponse,
    DatasetVersionComparisonItem,
    DatasetVersionComparisonResponse,
    DatasetVersionCreateRequest,
    DatasetVersionItemResponse,
    DatasetVersionManifestResponse,
    DatasetVersionPreviewClassCount,
    DatasetVersionPreviewImage,
    DatasetVersionPreviewRequest,
    DatasetVersionPreviewResponse,
    DatasetVersionResponse,
    DatasetVersionSplitSummary,
    ExportResponse,
    SplitRatios,
)
from reefvision.schemas.jobs import JobResponse
from reefvision.storage.datasets import canonical_json_sha256, dataset_export_relative_paths
from reefvision.storage.projects import resolve_managed_project_path

if TYPE_CHECKING:
    from reefvision.schemas.dataset_versions import DatasetSplitMethod

CURRENT_SCHEMA_VERSION = "0006"
TRAINABLE_SPLITS = ("train", "validation", "test")
ALL_SPLITS = (*TRAINABLE_SPLITS, "unassigned")


@dataclass(slots=True)
class CandidateImage:
    image: ImageAsset
    annotations: list[Annotation]
    per_class_counts: dict[str, int]


@dataclass(slots=True)
class AssignmentUnit:
    key: str
    image_ids: list[str]
    size: int
    fixed_split: str | None = None


class ClassMapEntry(TypedDict):
    id: str
    class_index: int
    display_order: int
    name: str
    scientific_name: str | None
    state_name: str | None
    display_color: str
    is_active: bool


@dataclass(slots=True)
class SplitPlan:
    assignments: dict[str, str]
    warnings: list[str]
    requested_ratios: dict[str, float] | None
    achieved_ratios: dict[str, float] | None
    resolved_split_method: DatasetSplitMethod
    missing_group_key_count: int
    split_summary_map: dict[str, dict[str, int]]
    eligible_annotation_count: int


class DatasetVersionService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.projects = ProjectRepository(session)
        self.versions = DatasetVersionRepository(session)
        self.exports = ExportRepository(session)

    def _project(self, project_id: str) -> Project:
        project = self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _version(self, version_id: str) -> DatasetVersion:
        version = self.versions.get_version(version_id)
        if version is None:
            raise NotFoundError("Dataset version not found")
        return version

    def _export(self, export_id: str) -> ExportRecord:
        export = self.exports.get_export(export_id)
        if export is None:
            raise NotFoundError("Export not found")
        return export

    def list_versions(self, project_id: str) -> list[DatasetVersionResponse]:
        self._project(project_id)
        return [
            DatasetVersionResponse.model_validate(version)
            for version in self.versions.list_versions(project_id)
        ]

    def list_exports(
        self, project_id: str, *, dataset_version_id: str | None = None
    ) -> list[ExportResponse]:
        self._project(project_id)
        return [
            ExportResponse.model_validate(item)
            for item in self.exports.list_exports(project_id, dataset_version_id=dataset_version_id)
        ]

    def get_version(self, version_id: str) -> DatasetVersionResponse:
        return DatasetVersionResponse.model_validate(self._version(version_id))

    def get_version_items(self, version_id: str) -> list[DatasetVersionItemResponse]:
        self._version(version_id)
        return [
            DatasetVersionItemResponse.model_validate(item)
            for item in self.versions.items_for_version(version_id)
        ]

    def get_manifest(self, version_id: str) -> DatasetVersionManifestResponse:
        version = self._version(version_id)
        return DatasetVersionManifestResponse(
            dataset_version_id=version.id,
            manifest_sha256=version.manifest_sha256,
            manifest_json=version.manifest_json,
        )

    def _eligible_images(self, project_id: str, statuses: list[str]) -> list[CandidateImage]:
        image_statement = (
            select(ImageAsset)
            .where(
                ImageAsset.project_id == project_id,
                ImageAsset.annotation_status.in_(tuple(statuses)),
            )
            .order_by(ImageAsset.created_at.desc(), ImageAsset.id)
        )
        images = list(self.session.scalars(image_statement))
        if not images:
            return []

        annotations_statement = (
            select(Annotation)
            .options(selectinload(Annotation.label_class))
            .where(
                Annotation.image_id.in_([image.id for image in images]),
                Annotation.deleted_at.is_(None),
            )
            .order_by(Annotation.image_id, Annotation.created_at, Annotation.id)
        )
        annotations_by_image: dict[str, list[Annotation]] = defaultdict(list)
        for annotation in self.session.scalars(annotations_statement):
            annotations_by_image[annotation.image_id].append(annotation)

        candidates: list[CandidateImage] = []
        for image in images:
            annotations = annotations_by_image.get(image.id, [])
            counts: dict[str, int] = defaultdict(int)
            for annotation in annotations:
                counts[annotation.label_class_id] += 1
            candidates.append(
                CandidateImage(
                    image=image,
                    annotations=annotations,
                    per_class_counts={key: int(value) for key, value in counts.items()},
                )
            )
        return candidates

    def _class_map(self, project: Project) -> list[ClassMapEntry]:
        ordered_classes = sorted(
            project.label_classes,
            key=lambda item: (item.display_order, item.class_index, item.name.casefold()),
        )
        return [
            {
                "id": label_class.id,
                "class_index": label_class.class_index,
                "display_order": label_class.display_order,
                "name": label_class.name,
                "scientific_name": label_class.scientific_name,
                "state_name": label_class.state_name,
                "display_color": label_class.display_color,
                "is_active": label_class.is_active,
            }
            for label_class in ordered_classes
        ]

    def _annotation_snapshot(self, annotation: Annotation) -> dict[str, object | None]:
        label_class = annotation.label_class
        if label_class is None:
            raise ValidationError("Dataset snapshots require every annotation to resolve its class")
        return {
            "id": annotation.id,
            "label_class_id": label_class.id,
            "class_index": label_class.class_index,
            "class_name": label_class.name,
            "x_min": annotation.x_min,
            "y_min": annotation.y_min,
            "x_max": annotation.x_max,
            "y_max": annotation.y_max,
            "source_type": annotation.source_type,
            "source_model_id": annotation.source_model_id,
            "source_prediction_id": annotation.source_prediction_id,
            "provenance_json": annotation.provenance_json,
            "created_by": annotation.created_by,
            "created_at": annotation.created_at.isoformat(),
            "updated_at": annotation.updated_at.isoformat(),
            "revision": annotation.revision,
        }

    def _normalize_requested_ratios(self, requested: SplitRatios | None) -> dict[str, float] | None:
        if requested is None:
            return None
        ratios = {
            "train": float(requested.train),
            "validation": float(requested.validation),
            "test": float(requested.test),
        }
        total = sum(ratios.values())
        if total <= 0:
            raise ValidationError("At least one split ratio must be greater than zero")
        return {split: value / total for split, value in ratios.items()}

    def _target_split_counts(self, total_images: int, ratios: dict[str, float]) -> dict[str, int]:
        raw = {split: total_images * ratios[split] for split in TRAINABLE_SPLITS}
        counts = {split: floor(value) for split, value in raw.items()}
        remaining = total_images - sum(counts.values())
        order = sorted(
            TRAINABLE_SPLITS,
            key=lambda split: (raw[split] - counts[split], -TRAINABLE_SPLITS.index(split)),
            reverse=True,
        )
        for split in order[:remaining]:
            counts[split] += 1
        return counts

    def _resolved_split_method(
        self, requested_method: DatasetSplitMethod, candidates: list[CandidateImage]
    ) -> DatasetSplitMethod:
        has_any_group_key = any(candidate.image.group_key for candidate in candidates)
        if requested_method == "random" and has_any_group_key:
            return "group_random"
        return requested_method

    def _parent_version(
        self, project_id: str, parent_version_id: str | None
    ) -> DatasetVersion | None:
        if parent_version_id is None:
            return None
        parent = self._version(parent_version_id)
        if parent.project_id != project_id:
            raise ValidationError("Parent dataset version must belong to the same project")
        return parent

    def _parent_items(
        self, project_id: str, request: DatasetVersionPreviewRequest
    ) -> dict[str, DatasetVersionItem]:
        if not request.reuse_parent_assignments:
            return {}
        if request.parent_version_id is None:
            raise ValidationError("Choose a parent version before reusing parent split assignments")
        parent = self._parent_version(project_id, request.parent_version_id)
        assert parent is not None
        if parent.status != "complete":
            raise ValidationError("Only complete parent versions may contribute split assignments")
        return {item.image_id: item for item in self.versions.items_for_version(parent.id)}

    def _manual_assignment_map(self, request: DatasetVersionPreviewRequest) -> dict[str, str]:
        assignments: dict[str, str] = {}
        for item in request.manual_assignments:
            existing = assignments.get(item.image_id)
            if existing is not None and existing != item.split:
                raise ValidationError("Manual split assignments conflict for the same image")
            assignments[item.image_id] = item.split
        return assignments

    def _assignment_units(
        self,
        candidates: list[CandidateImage],
        *,
        fixed_assignments: dict[str, str],
    ) -> list[AssignmentUnit]:
        grouped_ids: dict[str, list[str]] = defaultdict(list)
        for candidate in candidates:
            group_key = candidate.image.group_key
            unit_key = group_key if group_key is not None else f"image:{candidate.image.id}"
            grouped_ids[unit_key].append(candidate.image.id)

        units: list[AssignmentUnit] = []
        for key in sorted(grouped_ids):
            image_ids = sorted(grouped_ids[key])
            fixed = {
                fixed_assignments[image_id]
                for image_id in image_ids
                if image_id in fixed_assignments
            }
            if len(fixed) > 1:
                raise ValidationError("A non-null group key would cross multiple dataset splits")
            units.append(
                AssignmentUnit(
                    key=key,
                    image_ids=image_ids,
                    size=len(image_ids),
                    fixed_split=next(iter(fixed)) if fixed else None,
                )
            )
        return units

    def _choose_split(
        self, current_counts: dict[str, int], target_counts: dict[str, int], unit_size: int
    ) -> str:
        best_split = "train"
        best_score: tuple[float, float, int] | None = None
        for index, split in enumerate(TRAINABLE_SPLITS):
            trial = {**current_counts, split: current_counts[split] + unit_size}
            total_error = sum(abs(trial[key] - target_counts[key]) for key in TRAINABLE_SPLITS)
            occupancy = (
                trial[split] / target_counts[split]
                if target_counts[split] > 0
                else float(trial[split])
            )
            score = (float(total_error), float(occupancy), index)
            if best_score is None or score < best_score:
                best_split = split
                best_score = score
        return best_split

    def _plan_splits(
        self,
        candidates: list[CandidateImage],
        request: DatasetVersionPreviewRequest,
    ) -> SplitPlan:
        manual_assignments = self._manual_assignment_map(request)
        parent_items = (
            self._parent_items(candidates[0].image.project_id, request) if candidates else {}
        )
        fixed_assignments = {image_id: item.split for image_id, item in parent_items.items()}
        for candidate in candidates:
            parent_item = parent_items.get(candidate.image.id)
            if parent_item is None:
                continue
            if parent_item.group_key != candidate.image.group_key:
                raise ValidationError(
                    "Parent split reuse requires matching group keys for reused images"
                )
        for image_id, split in manual_assignments.items():
            existing = fixed_assignments.get(image_id)
            if existing is not None and existing != split:
                raise ValidationError(
                    "Manual assignments conflict with the selected parent version"
                )
            fixed_assignments[image_id] = split

        resolved_method = self._resolved_split_method(request.split_method, candidates)
        assignments = {candidate.image.id: "unassigned" for candidate in candidates}
        current_counts = {split: 0 for split in TRAINABLE_SPLITS}
        units = self._assignment_units(candidates, fixed_assignments=fixed_assignments)

        warnings: list[str] = []
        missing_group_key_count = sum(
            1 for candidate in candidates if candidate.image.group_key is None
        )
        if request.split_method == "random" and resolved_method == "group_random":
            warnings.append(
                "Group-aware splitting was applied because at least one eligible image has "
                "a group key."
            )
        if missing_group_key_count and resolved_method == "group_random":
            warnings.append(
                "Eligible images without a group key were treated as singleton groups "
                "during group-aware splitting."
            )

        for unit in units:
            if unit.fixed_split is None:
                continue
            for image_id in unit.image_ids:
                assignments[image_id] = unit.fixed_split
            if unit.fixed_split in current_counts:
                current_counts[unit.fixed_split] += unit.size

        requested_ratios = self._normalize_requested_ratios(request.requested_ratios)
        if resolved_method in {"random", "group_random"}:
            target_counts = self._target_split_counts(
                len(candidates),
                requested_ratios or {"train": 0.7, "validation": 0.2, "test": 0.1},
            )
            remaining_units = [unit for unit in units if unit.fixed_split is None]
            generator = random.Random(request.split_seed if request.split_seed is not None else 0)
            remaining_units.sort(key=lambda unit: unit.key)
            generator.shuffle(remaining_units)
            for unit in remaining_units:
                chosen_split = self._choose_split(current_counts, target_counts, unit.size)
                for image_id in unit.image_ids:
                    assignments[image_id] = chosen_split
                current_counts[chosen_split] += unit.size
            if any(current_counts[split] != target_counts[split] for split in TRAINABLE_SPLITS):
                warnings.append(
                    "Requested split ratios could not be matched exactly because of group "
                    "sizes or reused assignments."
                )
        elif resolved_method == "manual":
            for unit in units:
                if unit.fixed_split is None:
                    continue
                if unit.fixed_split not in ALL_SPLITS:
                    raise ValidationError("Unknown manual dataset split")
        elif resolved_method == "none":
            pass
        else:
            raise ValidationError("Unknown dataset split method")

        split_summary_map: dict[str, dict[str, int]] = {
            split: {"image_count": 0, "annotation_count": 0} for split in ALL_SPLITS
        }
        total_annotation_count = 0
        for candidate in candidates:
            split = assignments[candidate.image.id]
            split_summary_map[split]["image_count"] += 1
            split_summary_map[split]["annotation_count"] += len(candidate.annotations)
            total_annotation_count += len(candidate.annotations)

        achieved_ratios = None
        if candidates:
            achieved_ratios = {
                split: split_summary_map[split]["image_count"] / len(candidates)
                for split in TRAINABLE_SPLITS
            }

        return SplitPlan(
            assignments=assignments,
            warnings=warnings,
            requested_ratios=requested_ratios,
            achieved_ratios=achieved_ratios,
            resolved_split_method=resolved_method,
            missing_group_key_count=missing_group_key_count,
            split_summary_map=split_summary_map,
            eligible_annotation_count=total_annotation_count,
        )

    def preview_version(
        self, project_id: str, request: DatasetVersionPreviewRequest
    ) -> DatasetVersionPreviewResponse:
        project = self._project(project_id)
        self._parent_version(project.id, request.parent_version_id)
        candidates = self._eligible_images(project.id, list(request.eligible_annotation_statuses))
        if not candidates:
            raise ValidationError("No images match the selected annotation statuses")

        split_plan = self._plan_splits(candidates, request)
        class_counts: dict[str, int] = defaultdict(int)
        for candidate in candidates:
            for label_class_id, count in candidate.per_class_counts.items():
                class_counts[label_class_id] += count

        class_map = self._class_map(project)
        return DatasetVersionPreviewResponse(
            requested_split_method=request.split_method,
            resolved_split_method=split_plan.resolved_split_method,
            eligible_image_count=len(candidates),
            eligible_annotation_count=split_plan.eligible_annotation_count,
            missing_group_key_count=split_plan.missing_group_key_count,
            warnings=list(split_plan.warnings),
            split_summary=[
                DatasetVersionSplitSummary(
                    split=split,
                    image_count=split_plan.split_summary_map[split]["image_count"],
                    annotation_count=split_plan.split_summary_map[split]["annotation_count"],
                )
                for split in ALL_SPLITS
            ],
            per_class_counts=[
                DatasetVersionPreviewClassCount(
                    label_class_id=str(item["id"]),
                    class_index=int(item["class_index"]),
                    class_name=str(item["name"]),
                    count=class_counts.get(str(item["id"]), 0),
                )
                for item in class_map
            ],
            images=[
                DatasetVersionPreviewImage(
                    image_id=candidate.image.id,
                    original_filename=candidate.image.original_filename,
                    annotation_status=candidate.image.annotation_status,
                    group_key=candidate.image.group_key,
                    annotation_count=len(candidate.annotations),
                    proposed_split=split_plan.assignments[candidate.image.id],
                )
                for candidate in candidates
            ],
        )

    def create_version(
        self, project_id: str, request: DatasetVersionCreateRequest
    ) -> DatasetVersionResponse:
        project = self._project(project_id)
        self._parent_version(project.id, request.parent_version_id)
        candidates = self._eligible_images(project.id, list(request.eligible_annotation_statuses))
        if not candidates:
            raise ValidationError("No images match the selected annotation statuses")

        split_plan = self._plan_splits(candidates, request)
        version = DatasetVersion(
            project_id=project.id,
            version_number=self.versions.next_version_number(project.id),
            name=request.name,
            notes=request.notes,
            parent_version_id=request.parent_version_id,
            status="creating",
            requested_split_method=request.split_method,
            resolved_split_method=split_plan.resolved_split_method,
            eligible_annotation_statuses_json=list(request.eligible_annotation_statuses),
            requested_ratios_json=split_plan.requested_ratios,
            achieved_ratios_json=split_plan.achieved_ratios,
            split_seed=request.split_seed,
            reuse_parent_assignments=request.reuse_parent_assignments,
            missing_group_key_count=split_plan.missing_group_key_count,
            warnings_json=list(split_plan.warnings),
            class_map_json=self._class_map(project),
            manifest_json={},
            manifest_sha256="",
            image_count=len(candidates),
            annotation_count=split_plan.eligible_annotation_count,
            created_by=request.creator or "local_user",
            reefvision_version=__version__,
            schema_version=CURRENT_SCHEMA_VERSION,
        )
        self.versions.add_version(version)
        self.session.flush()

        manifest_items: list[dict[str, object | None]] = []
        for candidate in sorted(candidates, key=lambda item: item.image.id):
            annotations = [
                self._annotation_snapshot(annotation) for annotation in candidate.annotations
            ]
            item_payload = {
                "image_id": candidate.image.id,
                "image_sha256": candidate.image.sha256,
                "original_filename": candidate.image.original_filename,
                "width_px": candidate.image.width_px,
                "height_px": candidate.image.height_px,
                "annotation_status": candidate.image.annotation_status,
                "split": split_plan.assignments[candidate.image.id],
                "group_key": candidate.image.group_key,
                "annotation_count": len(candidate.annotations),
                "per_class_counts": candidate.per_class_counts,
                "annotations": annotations,
            }
            snapshot_sha256 = canonical_json_sha256(item_payload)
            dataset_item = DatasetVersionItem(
                dataset_version_id=version.id,
                image_id=candidate.image.id,
                image_sha256=candidate.image.sha256,
                original_filename=candidate.image.original_filename,
                width_px=candidate.image.width_px,
                height_px=candidate.image.height_px,
                image_annotation_status=candidate.image.annotation_status,
                split=split_plan.assignments[candidate.image.id],
                group_key=candidate.image.group_key,
                annotation_snapshot_json=annotations,
                per_class_counts_json=candidate.per_class_counts,
                annotation_count=len(candidate.annotations),
                snapshot_sha256=snapshot_sha256,
            )
            self.versions.add_item(dataset_item)
            manifest_items.append({**item_payload, "snapshot_sha256": snapshot_sha256})

        manifest = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "reefvision_version": __version__,
            "project": {
                "id": project.id,
                "name": project.name,
                "slug": project.slug,
            },
            "dataset_version": {
                "id": version.id,
                "version_number": version.version_number,
                "name": version.name,
                "notes": version.notes,
                "parent_version_id": version.parent_version_id,
                "status": "complete",
                "created_by": version.created_by,
                "created_at": version.created_at.isoformat(),
            },
            "split_config": {
                "requested_split_method": version.requested_split_method,
                "resolved_split_method": version.resolved_split_method,
                "requested_ratios": version.requested_ratios_json,
                "achieved_ratios": version.achieved_ratios_json,
                "split_seed": version.split_seed,
                "reuse_parent_assignments": version.reuse_parent_assignments,
                "eligible_annotation_statuses": version.eligible_annotation_statuses_json,
                "warnings": version.warnings_json,
                "missing_group_key_count": version.missing_group_key_count,
            },
            "summary": {
                "image_count": version.image_count,
                "annotation_count": version.annotation_count,
            },
            "class_map": version.class_map_json,
            "items": manifest_items,
        }
        version.manifest_json = manifest
        version.manifest_sha256 = canonical_json_sha256(manifest)
        version.status = "complete"
        version.completed_at = utc_now()
        self.session.commit()
        self.session.refresh(version)
        return DatasetVersionResponse.model_validate(version)

    def compare_versions(
        self, version_id: str, other_version_id: str
    ) -> DatasetVersionComparisonResponse:
        base_version = self._version(version_id)
        compare_version = self._version(other_version_id)
        if base_version.project_id != compare_version.project_id:
            raise ValidationError("Only versions from the same project can be compared")

        base_items = {
            item.image_id: item for item in self.versions.items_for_version(base_version.id)
        }
        compare_items = {
            item.image_id: item for item in self.versions.items_for_version(compare_version.id)
        }
        all_image_ids = sorted(set(base_items) | set(compare_items))

        added_images: list[DatasetVersionComparisonItem] = []
        removed_images: list[DatasetVersionComparisonItem] = []
        changed_images: list[DatasetVersionComparisonItem] = []

        for image_id in all_image_ids:
            base_item = base_items.get(image_id)
            compare_item = compare_items.get(image_id)
            if base_item is None and compare_item is not None:
                added_images.append(
                    DatasetVersionComparisonItem(
                        image_id=compare_item.image_id,
                        original_filename=compare_item.original_filename,
                        from_split=None,
                        to_split=compare_item.split,
                        from_annotation_count=0,
                        to_annotation_count=compare_item.annotation_count,
                    )
                )
                continue
            if compare_item is None and base_item is not None:
                removed_images.append(
                    DatasetVersionComparisonItem(
                        image_id=base_item.image_id,
                        original_filename=base_item.original_filename,
                        from_split=base_item.split,
                        to_split=None,
                        from_annotation_count=base_item.annotation_count,
                        to_annotation_count=0,
                    )
                )
                continue
            if base_item is None or compare_item is None:
                continue
            if base_item.snapshot_sha256 != compare_item.snapshot_sha256:
                changed_images.append(
                    DatasetVersionComparisonItem(
                        image_id=image_id,
                        original_filename=compare_item.original_filename,
                        from_split=base_item.split,
                        to_split=compare_item.split,
                        from_annotation_count=base_item.annotation_count,
                        to_annotation_count=compare_item.annotation_count,
                    )
                )

        return DatasetVersionComparisonResponse(
            base_version_id=base_version.id,
            compare_version_id=compare_version.id,
            added_images=added_images,
            removed_images=removed_images,
            changed_images=changed_images,
            annotation_delta=compare_version.annotation_count - base_version.annotation_count,
        )

    def create_export(
        self, version_id: str, request: DatasetExportCreateRequest
    ) -> DatasetExportCreateResponse:
        version = self._version(version_id)
        if version.status != "complete":
            raise ValidationError("Only complete dataset versions may be exported")
        if request.format != "yolo_detection":
            raise ValidationError("Only yolo_detection export is currently supported")

        output_path, manifest_path, archive_path = dataset_export_relative_paths(
            project_storage_root=version.project.storage_root,
            version_number=version.version_number,
            export_id=version.id + "-" + str(len(version.exports) + 1),
        )
        export = ExportRecord(
            project_id=version.project_id,
            dataset_version_id=version.id,
            format=request.format,
            output_path=output_path,
            manifest_path=manifest_path,
            archive_path=archive_path,
            request_json={"format": request.format, "dataset_version_id": version.id},
            status="queued",
        )
        self.exports.add_export(export)
        self.session.flush()
        output_path, manifest_path, archive_path = dataset_export_relative_paths(
            project_storage_root=version.project.storage_root,
            version_number=version.version_number,
            export_id=export.id,
        )
        export.output_path = output_path
        export.manifest_path = manifest_path
        export.archive_path = archive_path

        job = Job(
            project_id=version.project_id,
            job_type="export",
            status="queued",
            progress_total=max(version.image_count, 1),
            request_json={"export_id": export.id, "format": request.format},
        )
        self.session.add(job)
        self.session.flush()
        export.job_id = job.id
        self.session.commit()
        self.session.refresh(export)
        self.session.refresh(job)
        return DatasetExportCreateResponse(
            export=ExportResponse.model_validate(export),
            job=JobResponse.model_validate(job),
        )

    def get_export(self, export_id: str) -> ExportResponse:
        return ExportResponse.model_validate(self._export(export_id))

    def export_archive_path(self, export_id: str) -> Path:
        export = self._export(export_id)
        if export.status != "succeeded":
            raise ValidationError("Export archive is not ready yet")
        path = resolve_managed_project_path(self.settings, export.archive_path)
        if not path.is_file():
            raise NotFoundError("Export archive is missing")
        return path

    def export_manifest_path(self, export_id: str) -> Path:
        export = self._export(export_id)
        path = resolve_managed_project_path(self.settings, export.manifest_path)
        if not path.is_file():
            raise NotFoundError("Export manifest is missing")
        return path
