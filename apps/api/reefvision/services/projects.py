"""Project and class domain services."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    Annotation,
    AnnotationEvent,
    DatasetVersion,
    ImageAsset,
    LabelClass,
    ModelRegistration,
    PredictionProposal,
    Project,
    QualityControlIssue,
    ReviewQueueItem,
)
from reefvision.domain.errors import ConflictError, NotFoundError
from reefvision.repositories.projects import LabelClassRepository, ProjectRepository
from reefvision.schemas.projects import (
    LabelClassCreate,
    LabelClassMergeCountResponse,
    LabelClassMergeRequest,
    LabelClassMergeResponse,
    LabelClassResponse,
    LabelClassUpdate,
    LabelClassUsageCountResponse,
    LabelClassUsageResponse,
    ProjectCreate,
    ProjectSummaryResponse,
    ProjectUpdate,
)
from reefvision.services.annotations import annotation_snapshot
from reefvision.services.georeferencing_invalidation import (
    STALE_REASON_PROJECT_SURFACE_REFERENCE_CHANGED,
    GeoreferencingInvalidationService,
)
from reefvision.storage.projects import (
    create_managed_project_directory,
    remove_empty_project_directory,
)


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    return slug or "project"


USAGE_CATEGORY_ORDER = [
    "annotations_active",
    "annotations_deleted",
    "annotation_history",
    "prediction_proposals",
    "quality_control_issues",
    "review_queue_items",
    "dataset_versions",
    "model_registrations",
]

USAGE_CATEGORY_META: dict[str, tuple[str, bool, bool]] = {
    "annotations_active": ("Active annotations", True, False),
    "annotations_deleted": ("Deleted annotations", False, True),
    "annotation_history": ("Annotation history events", False, True),
    "prediction_proposals": ("Prediction proposals", True, False),
    "quality_control_issues": ("Quality-control issues", True, False),
    "review_queue_items": ("Review-queue items", True, False),
    "dataset_versions": ("Immutable dataset versions", False, True),
    "model_registrations": ("Registered model class maps", False, True),
}


@dataclass(slots=True)
class LabelClassUsageSnapshot:
    counts: dict[str, int]
    delete_blockers: list[str]
    compatibility_warnings: list[str]

    @property
    def total_references(self) -> int:
        return sum(self.counts.values())

    @property
    def mutable_reference_count(self) -> int:
        return sum(
            count for key, count in self.counts.items() if count > 0 and USAGE_CATEGORY_META[key][1]
        )

    @property
    def immutable_reference_count(self) -> int:
        return sum(
            count for key, count in self.counts.items() if count > 0 and USAGE_CATEGORY_META[key][2]
        )

    @property
    def can_delete(self) -> bool:
        return self.total_references == 0


def _contains_label_class_reference(payload: object, class_id: str) -> bool:
    if not isinstance(payload, dict):
        return False
    return payload.get("label_class_id") == class_id


def _replace_class_id_list(
    values: list[str], source_class_id: str, target_class_id: str
) -> list[str]:
    replaced: list[str] = []
    seen: set[str] = set()
    for value in values:
        next_value = target_class_id if value == source_class_id else value
        if next_value in seen:
            continue
        replaced.append(next_value)
        seen.add(next_value)
    return replaced


class ProjectService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.projects = ProjectRepository(session)
        self.classes = LabelClassRepository(session)

    def list_projects(self, *, include_archived: bool = False) -> list[Project]:
        return self.projects.list(include_archived=include_archived)

    def list_project_summaries(
        self, *, include_archived: bool = False
    ) -> list[ProjectSummaryResponse]:
        return [
            ProjectSummaryResponse(
                id=row.project.id,
                name=row.project.name,
                slug=row.project.slug,
                description=row.project.description,
                storage_root=row.project.storage_root,
                default_annotation_type=row.project.default_annotation_type,
                georeference_height_offset_m=row.project.georeference_height_offset_m,
                georeference_height_evidence=row.project.georeference_height_evidence,
                created_at=row.project.created_at,
                updated_at=row.project.updated_at,
                archived_at=row.project.archived_at,
                label_class_count=row.label_class_count,
                active_label_class_count=row.active_label_class_count,
            )
            for row in self.projects.list_summaries(include_archived=include_archived)
        ]

    def get_project(self, project_id: str) -> Project:
        project = self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _unique_generated_slug(self, name: str) -> str:
        base = slugify(name)
        candidate = base
        suffix = 2
        while self.projects.slug_exists(candidate):
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    def create_project(self, payload: ProjectCreate, *, commit: bool = True) -> Project:
        project_id = str(uuid4())
        if payload.slug is not None:
            slug = slugify(payload.slug)
            if self.projects.slug_exists(slug):
                raise ConflictError("Project slug already exists")
        else:
            slug = self._unique_generated_slug(payload.name)

        storage_root = create_managed_project_directory(self.settings, project_id)
        project = Project(
            id=project_id,
            name=payload.name,
            slug=slug,
            description=payload.description,
            storage_root=storage_root,
            georeference_height_offset_m=payload.georeference_height_offset_m,
            georeference_height_evidence=payload.georeference_height_evidence,
        )
        self.projects.add(project)

        try:
            if commit:
                self.session.commit()
            else:
                self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            remove_empty_project_directory(self.settings, storage_root)
            raise ConflictError("Project or class values conflict with existing data") from exc
        self.session.refresh(project)
        return self.get_project(project.id)

    def update_project(self, project_id: str, payload: ProjectUpdate) -> Project:
        project = self.get_project(project_id)
        changes = payload.model_dump(exclude_unset=True)
        georeferencing_changed = any(
            field in changes and changes[field] != getattr(project, field)
            for field in (
                "georeference_height_offset_m",
                "georeference_height_evidence",
            )
        )
        if "slug" in changes:
            requested_slug = slugify(changes["slug"])
            if self.projects.slug_exists(requested_slug, exclude_project_id=project_id):
                raise ConflictError("Project slug already exists")
            changes["slug"] = requested_slug
        for key, value in changes.items():
            setattr(project, key, value)
        if georeferencing_changed:
            GeoreferencingInvalidationService(self.session).mark_project_stale(
                project_id,
                reason=(STALE_REASON_PROJECT_SURFACE_REFERENCE_CHANGED),
            )

        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("Project update conflicts with existing data") from exc
        return self.get_project(project_id)

    def archive_project(self, project_id: str) -> Project:
        project = self.get_project(project_id)
        if project.archived_at is None:
            project.archived_at = datetime.now(UTC)
            self.session.commit()
        return self.get_project(project_id)

    def _class(self, class_id: str) -> LabelClass:
        label_class = self.classes.get(class_id)
        if label_class is None:
            raise NotFoundError("Label class not found")
        return label_class

    def _usage_snapshot(self, label_class: LabelClass) -> LabelClassUsageSnapshot:
        counts = {key: 0 for key in USAGE_CATEGORY_ORDER}

        annotations = list(
            self.session.scalars(
                select(Annotation).where(Annotation.label_class_id == label_class.id)
            )
        )
        counts["annotations_active"] = sum(1 for item in annotations if item.deleted_at is None)
        counts["annotations_deleted"] = sum(
            1 for item in annotations if item.deleted_at is not None
        )

        annotation_events = list(
            self.session.scalars(
                select(AnnotationEvent)
                .join(ImageAsset, ImageAsset.id == AnnotationEvent.image_id)
                .where(ImageAsset.project_id == label_class.project_id)
            )
        )
        counts["annotation_history"] = sum(
            1
            for item in annotation_events
            if _contains_label_class_reference(item.before_json, label_class.id)
            or _contains_label_class_reference(item.after_json, label_class.id)
        )

        counts["prediction_proposals"] = len(
            list(
                self.session.scalars(
                    select(PredictionProposal).where(
                        PredictionProposal.project_id == label_class.project_id,
                        PredictionProposal.label_class_id == label_class.id,
                    )
                )
            )
        )

        counts["quality_control_issues"] = sum(
            1
            for item in self.session.scalars(
                select(QualityControlIssue).where(
                    QualityControlIssue.project_id == label_class.project_id
                )
            )
            if label_class.id in item.class_ids_json
        )

        counts["review_queue_items"] = sum(
            1
            for item in self.session.scalars(
                select(ReviewQueueItem).where(ReviewQueueItem.project_id == label_class.project_id)
            )
            if label_class.id in item.label_class_ids_json
        )

        counts["dataset_versions"] = sum(
            1
            for item in self.session.scalars(
                select(DatasetVersion).where(DatasetVersion.project_id == label_class.project_id)
            )
            if any(entry.get("id") == label_class.id for entry in item.class_map_json)
        )

        counts["model_registrations"] = sum(
            1
            for item in self.session.scalars(
                select(ModelRegistration).where(
                    ModelRegistration.project_id == label_class.project_id
                )
            )
            if label_class.id
            in {
                value
                for value in (item.class_map_json.get("mapping") or {}).values()
                if isinstance(value, str)
            }
        )

        delete_blockers: list[str] = []
        if counts["annotations_active"] > 0:
            delete_blockers.append(
                "Active annotations still use this class. Reassign or merge them first."
            )
        if counts["annotations_deleted"] > 0 or counts["annotation_history"] > 0:
            delete_blockers.append("Historical annotation records still reference this class.")
        if counts["prediction_proposals"] > 0:
            delete_blockers.append("Prediction proposals still reference this class.")
        if counts["quality_control_issues"] > 0:
            delete_blockers.append("Quality-control issues still reference this class.")
        if counts["review_queue_items"] > 0:
            delete_blockers.append("Review-queue items still reference this class.")
        if counts["dataset_versions"] > 0:
            delete_blockers.append("Immutable dataset versions still include this class.")
        if counts["model_registrations"] > 0:
            delete_blockers.append("Registered model class maps still reference this class.")

        compatibility_warnings: list[str] = []
        if counts["dataset_versions"] > 0:
            compatibility_warnings.append(
                "Historical dataset versions keep their original class map for reproducibility."
            )
        if counts["model_registrations"] > 0:
            compatibility_warnings.append(
                "Registered model class maps keep their original source-to-class mapping."
            )
        if counts["annotations_deleted"] > 0 or counts["annotation_history"] > 0:
            compatibility_warnings.append(
                "Historical annotation events remain unchanged for auditability."
            )

        return LabelClassUsageSnapshot(
            counts=counts,
            delete_blockers=delete_blockers,
            compatibility_warnings=compatibility_warnings,
        )

    def _usage_response(
        self,
        label_class: LabelClass,
        snapshot: LabelClassUsageSnapshot,
    ) -> LabelClassUsageResponse:
        return LabelClassUsageResponse(
            class_id=label_class.id,
            project_id=label_class.project_id,
            class_name=label_class.name,
            is_active=label_class.is_active,
            archived_at=label_class.archived_at,
            total_references=snapshot.total_references,
            mutable_reference_count=snapshot.mutable_reference_count,
            immutable_reference_count=snapshot.immutable_reference_count,
            can_delete=snapshot.can_delete,
            delete_blockers=snapshot.delete_blockers,
            compatibility_warnings=snapshot.compatibility_warnings,
            counts=[
                LabelClassUsageCountResponse(
                    key=key,
                    label=USAGE_CATEGORY_META[key][0],
                    count=snapshot.counts[key],
                    mutable=USAGE_CATEGORY_META[key][1],
                    immutable=USAGE_CATEGORY_META[key][2],
                )
                for key in USAGE_CATEGORY_ORDER
            ],
        )

    def list_classes(self, project_id: str) -> list[LabelClass]:
        self.get_project(project_id)
        return self.classes.list_for_project(project_id)

    def create_class(self, project_id: str, payload: LabelClassCreate) -> LabelClass:
        self.get_project(project_id)
        if self.classes.name_exists(project_id, payload.name):
            raise ConflictError("Class name already exists in this project")
        if self.classes.index_exists(project_id, payload.class_index):
            raise ConflictError("Class index already exists in this project")
        display_order = (
            payload.display_order
            if payload.display_order is not None
            else self.classes.next_display_order(project_id)
        )
        label_class = LabelClass(
            project_id=project_id,
            class_index=payload.class_index,
            display_order=display_order,
            name=payload.name,
            scientific_name=payload.scientific_name,
            state_name=payload.state_name,
            description=payload.description,
            display_color=payload.display_color.upper(),
        )
        self.classes.add(label_class)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("Class values conflict with existing data") from exc
        self.session.refresh(label_class)
        return label_class

    def update_class(self, class_id: str, payload: LabelClassUpdate) -> LabelClass:
        label_class = self._class(class_id)
        changes = payload.model_dump(exclude_unset=True)
        new_name = changes.get("name")
        if new_name is not None and self.classes.name_exists(
            label_class.project_id, new_name, exclude_class_id=class_id
        ):
            raise ConflictError("Class name already exists in this project")
        for key, value in changes.items():
            if key == "display_color" and value is not None:
                value = value.upper()
            setattr(label_class, key, value)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("Class update conflicts with existing data") from exc
        self.session.refresh(label_class)
        return label_class

    def usage_for_class(self, class_id: str) -> LabelClassUsageResponse:
        label_class = self._class(class_id)
        return self._usage_response(label_class, self._usage_snapshot(label_class))

    def archive_class(self, class_id: str) -> LabelClass:
        label_class = self._class(class_id)
        label_class.is_active = False
        if label_class.archived_at is None:
            label_class.archived_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(label_class)
        return label_class

    def restore_class(self, class_id: str) -> LabelClass:
        label_class = self._class(class_id)
        label_class.is_active = True
        label_class.archived_at = None
        self.session.commit()
        self.session.refresh(label_class)
        return label_class

    def deactivate_class(self, class_id: str) -> LabelClass:
        return self.archive_class(class_id)

    def delete_class(self, class_id: str) -> None:
        label_class = self._class(class_id)
        usage = self._usage_snapshot(label_class)
        if not usage.can_delete:
            raise ConflictError(
                "This class still has references. Review its usage report before deleting it."
            )
        self.session.delete(label_class)
        self.session.commit()

    def merge_class(
        self, class_id: str, payload: LabelClassMergeRequest
    ) -> LabelClassMergeResponse:
        source_class = self._class(class_id)
        target_class = self._class(payload.target_class_id)
        if source_class.id == target_class.id:
            raise ConflictError("Choose a different target class for merging")
        if source_class.project_id != target_class.project_id:
            raise ConflictError("Classes can only be merged within the same project")
        if not target_class.is_active:
            raise ConflictError("Restore the target class before merging into it")

        source_usage = self._usage_snapshot(source_class)
        affected_counts: dict[str, int] = defaultdict(int)

        annotations = list(
            self.session.scalars(
                select(Annotation)
                .where(
                    Annotation.label_class_id == source_class.id,
                    Annotation.deleted_at.is_(None),
                )
                .order_by(Annotation.created_at, Annotation.id)
            )
        )
        for annotation in annotations:
            before = annotation_snapshot(annotation)
            annotation.label_class_id = target_class.id
            annotation.revision += 1
            self.session.add(
                AnnotationEvent(
                    annotation_id=annotation.id,
                    image_id=annotation.image_id,
                    event_type="class_merged",
                    before_json=before,
                    after_json=annotation_snapshot(annotation),
                    actor="local_user",
                )
            )
            affected_counts["annotations_active"] += 1

        predictions = list(
            self.session.scalars(
                select(PredictionProposal).where(
                    PredictionProposal.project_id == source_class.project_id,
                    PredictionProposal.label_class_id == source_class.id,
                )
            )
        )
        for prediction in predictions:
            prediction.label_class_id = target_class.id
            prediction.was_edited = True
            affected_counts["prediction_proposals"] += 1

        quality_control_issues = list(
            self.session.scalars(
                select(QualityControlIssue).where(
                    QualityControlIssue.project_id == source_class.project_id
                )
            )
        )
        for issue in quality_control_issues:
            if source_class.id not in issue.class_ids_json:
                continue
            issue.class_ids_json = _replace_class_id_list(
                issue.class_ids_json, source_class.id, target_class.id
            )
            affected_counts["quality_control_issues"] += 1

        review_queue_items = list(
            self.session.scalars(
                select(ReviewQueueItem).where(ReviewQueueItem.project_id == source_class.project_id)
            )
        )
        for item in review_queue_items:
            if source_class.id not in item.label_class_ids_json:
                continue
            item.label_class_ids_json = _replace_class_id_list(
                item.label_class_ids_json, source_class.id, target_class.id
            )
            affected_counts["review_queue_items"] += 1

        source_class.is_active = False
        source_class.archived_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(source_class)
        self.session.refresh(target_class)

        immutable_reference_counts = [
            LabelClassMergeCountResponse(
                key=key,
                label=USAGE_CATEGORY_META[key][0],
                count=source_usage.counts[key],
            )
            for key in USAGE_CATEGORY_ORDER
            if source_usage.counts[key] > 0 and USAGE_CATEGORY_META[key][2]
        ]

        return LabelClassMergeResponse(
            source_class=LabelClassResponse.model_validate(source_class),
            target_class=LabelClassResponse.model_validate(target_class),
            affected_counts=[
                LabelClassMergeCountResponse(
                    key=key,
                    label=USAGE_CATEGORY_META[key][0],
                    count=count,
                )
                for key, count in affected_counts.items()
                if count > 0
            ],
            immutable_reference_counts=immutable_reference_counts,
            warnings=source_usage.compatibility_warnings,
        )
