"""ReefVision 1.0 import extensions for complete portable project state."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import PurePosixPath
from typing import Any, BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    ActiveLearningRound,
    AnnotationEvent,
    ClassOperation,
    ClassVisibilityPreference,
    DatasetVersion,
    ExportRecord,
    MaskAnnotationEvent,
    Project,
    ProjectClassVisibilityDefault,
    ProjectExchangePackage,
    ReviewQueue,
    ReviewQueueItem,
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
            source_relative_path = str(descriptor_value.get("source_relative_path", ""))
            if not _safe_relative_path(member) or not _safe_relative_path(source_relative_path):
                raise ValueError(f"Generated artifact path {index} is unsafe")
            destination_relative = f"{project.storage_root.rstrip('/')}/{source_relative_path}"
            destination = resolve_managed_project_path(settings, destination_relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with (
                archive.open(member, "r") as archive_stream,
                destination.open("wb") as output_stream,
            ):
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
    impacts = (
        [
            {
                "key": str(item.get("key", "")),
                "status": str(item.get("status", "")),
                "record_ids": list(item.get("record_ids", [])),
            }
            for item in raw_impacts
            if isinstance(item, dict)
        ]
        if isinstance(raw_impacts, list)
        else []
    )
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
        session.scalars(select(ClassOperation).where(ClassOperation.project_id == project_id))
    )
    for operation in operations:
        operation.preview_checksum = _operation_checksum(operation)
    session.flush()


def _refresh_review_queue_checksums(session: Session, project_id: str) -> None:
    queues = list(session.scalars(select(ReviewQueue).where(ReviewQueue.project_id == project_id)))
    items = list(
        session.scalars(select(ReviewQueueItem).where(ReviewQueueItem.project_id == project_id))
    )
    items_by_queue: dict[str, list[ReviewQueueItem]] = {}
    for item in items:
        items_by_queue.setdefault(item.review_queue_id, []).append(item)

    for queue in queues:
        queue_items = sorted(
            items_by_queue.get(queue.id, []),
            key=lambda item: (item.rank_position, item.image_id, item.id),
        )
        source_item_checksums = {item.id: item.input_checksum for item in queue_items}
        source_queue_checksums = dict(queue.input_checksums_json or {})
        configuration = dict(queue.configuration_json or {})
        configuration["exchange_import"] = {
            "checksum_schema": "review-queue-item-exchange-import-0001",
            "source_queue_input_checksums": source_queue_checksums,
            "source_item_checksums_by_imported_item_id": source_item_checksums,
        }
        queue.configuration_json = configuration

        for item in queue_items:
            item.input_checksum = canonical_json_sha256(
                {
                    "schema_version": "review-queue-item-exchange-import-0001",
                    "review_queue_id": item.review_queue_id,
                    "project_id": item.project_id,
                    "dataset_version_id": item.dataset_version_id,
                    "image_id": item.image_id,
                    "split": item.split,
                    "score": item.score,
                    "rank_position": item.rank_position,
                    "highest_qc_severity": item.highest_qc_severity,
                    "label_class_ids": item.label_class_ids_json,
                    "model_ids": item.model_ids_json,
                    "related_issue_ids": item.related_issue_ids_json,
                    "signal_values": item.signal_values_json,
                    "normalized_signals": item.normalized_signals_json,
                    "weights": item.weights_json,
                    "score_breakdown": item.score_breakdown_json,
                }
            )

        queue.input_checksums_json = {
            "queue_scope_sha256": canonical_json_sha256(
                {
                    "image_ids": sorted(item.image_id for item in queue_items),
                    "scores": {item.image_id: item.score for item in queue_items},
                    "source_quality_control_run_id": queue.source_quality_control_run_id,
                }
            ),
            "item_count": len(queue_items),
        }
    session.flush()


def _refresh_active_learning_checksums(session: Session, project_id: str) -> None:
    rounds = list(
        session.scalars(
            select(ActiveLearningRound).where(ActiveLearningRound.project_id == project_id)
        )
    )
    queue_items = list(
        session.scalars(select(ReviewQueueItem).where(ReviewQueueItem.project_id == project_id))
    )
    items_by_id = {item.id: item for item in queue_items}

    for round_record in rounds:
        source_selection_sha256 = round_record.selection_sha256
        manifest = dict(round_record.selection_manifest_json or {})
        raw_items = manifest.get("items", [])
        refreshed_items: list[dict[str, Any]] = []
        if isinstance(raw_items, list):
            for raw_item in raw_items:
                if not isinstance(raw_item, dict):
                    continue
                item = dict(raw_item)
                queue_item_id = item.get("queue_item_id")
                queue_item = (
                    items_by_id.get(queue_item_id) if isinstance(queue_item_id, str) else None
                )
                if queue_item is not None:
                    item["input_checksum"] = queue_item.input_checksum
                refreshed_items.append(item)
        manifest["items"] = refreshed_items
        round_record.selection_manifest_json = manifest

        stable_items = [
            {
                "image_id": item.get("image_id"),
                "rank_position": item.get("rank_position"),
                "score": item.get("score"),
                "input_checksum": item.get("input_checksum"),
            }
            for item in refreshed_items
        ]
        weights = manifest.get("weights")
        if not isinstance(weights, dict):
            strategy_config = dict(round_record.strategy_config_json or {})
            raw_weights = strategy_config.get("weights", {})
            weights = raw_weights if isinstance(raw_weights, dict) else {}
        identity_payload = {
            "schema_version": "active-learning-identity-0001",
            "project_id": round_record.project_id,
            "dataset_version_id": round_record.dataset_version_id,
            "strategy": round_record.strategy,
            "model_ids": round_record.model_ids_json,
            "requested_size": round_record.requested_size,
            "queue_formula_id": manifest.get("queue_formula_id"),
            "queue_formula_version": manifest.get("queue_formula_version"),
            "weights": weights,
            "items": stable_items,
        }
        round_record.selection_sha256 = canonical_json_sha256(identity_payload)

        strategy_config = dict(round_record.strategy_config_json or {})
        strategy_config["exchange_import"] = {
            "source_selection_sha256": source_selection_sha256,
            "selection_checksum_schema": "active-learning-identity-0001",
        }
        round_record.strategy_config_json = strategy_config

        feedback_summary = dict(round_record.feedback_summary_json or {})
        feedback_dataset_id = feedback_summary.get("feedback_dataset_version_id")
        if isinstance(feedback_dataset_id, str):
            feedback_dataset = session.get(DatasetVersion, feedback_dataset_id)
            if feedback_dataset is not None:
                feedback_summary["feedback_manifest_sha256"] = feedback_dataset.manifest_sha256
        round_record.feedback_summary_json = feedback_summary
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
        _refresh_review_queue_checksums(session, project.id)
        _refresh_active_learning_checksums(session, project.id)
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
