"""Bind an imported pose training run to its authenticated local frozen datasets."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.base import Base
from reefvision.db.models import (
    ExperimentRecord,
    PoseTrainingDataset,
    Project,
    ProjectExchangePackage,
    TrainingRun,
)
from reefvision.domain.errors import ValidationError
from reefvision.services.project_exchange_pose_history import (
    local_pose_manifest_paths,
    restore_pose_training_history,
)
from reefvision.storage.datasets import canonical_json_sha256


def imported_pose_package(session: Session, run: TrainingRun) -> ProjectExchangePackage | None:
    package = session.scalar(
        select(ProjectExchangePackage).where(
            ProjectExchangePackage.project_id == run.project_id,
            ProjectExchangePackage.direction == "import",
            ProjectExchangePackage.status == "complete",
        )
    )
    if package is None or run.id not in package.options_json.get("id_map", {}).values():
        return None
    return package


def _local_manifest(
    manifest: dict[str, Any], original: dict[str, Any], local: dict[str, Any], split_key: str
) -> dict[str, Any]:
    result = dict(manifest)
    if split_key in result:
        if result[split_key] != original:
            raise ValidationError(
                "The archived pose training split disagrees with its recorded snapshot"
            )
        result[split_key] = local
    for role in ("training", "validation"):
        for suffix in ("id", "manifest_sha256"):
            name = f"{role}_dataset_{suffix}"
            field = f"pose_{name}"
            if field in result:
                if result[field] != original.get(name):
                    raise ValidationError(
                        "The archived pose training dataset disagrees with its split manifest"
                    )
                result[field] = local.get(name)
    if "pose_split_manifest_sha256" in result:
        result["pose_split_manifest_sha256"] = canonical_json_sha256(local)
    return result


def rebind_pose_training_run(
    session: Session,
    run: TrainingRun,
    source_ids: dict[str, str],
    digests: dict[str, str],
    source_dataset_pins: dict[str, str] | None = None,
    *,
    experiment: ExperimentRecord | None,
) -> None:
    """Verify the pre-import split before replacing references in the local copy."""
    manifest = run.artifact_manifest_json or {}
    split = manifest.get("pose_split_manifest")
    if not isinstance(split, dict) or split.get("schema_version") != "pose-training-split-0001":
        return
    original_hash = run.split_manifest_sha256
    if canonical_json_sha256(split) == original_hash:
        return
    original = dict(split)
    local = dict(split)
    for field in ("training_dataset_id", "validation_dataset_id", "pose_schema_id"):
        if split.get(field) is not None:
            if not isinstance(split[field], str):
                raise ValidationError(
                    "The archived pose training split contains an invalid record ID"
                )
            original[field] = source_ids.get(split[field])
    if (
        canonical_json_sha256(original) != original_hash
        or manifest.get("pose_split_manifest_sha256", original_hash) != original_hash
    ):
        raise ValidationError(
            "The archived pose training split manifest checksum cannot be verified"
        )

    for role in ("training", "validation"):
        id_field = f"{role}_dataset_id"
        pin = f"{role}_dataset_manifest_sha256"
        if role == "validation" and split.get(id_field) is None and split.get(pin) is None:
            continue
        dataset_id = split.get(id_field)
        dataset = (
            session.get(PoseTrainingDataset, dataset_id) if isinstance(dataset_id, str) else None
        )
        source_pin = split.get(pin)
        if (
            dataset is None
            or dataset.project_id != run.project_id
            or dataset.status != "complete"
            or not isinstance(source_pin, str)
            or digests.get(source_pin) != dataset.manifest_sha256
            or (
                source_dataset_pins is not None
                and source_dataset_pins.get(original[id_field]) != source_pin
            )
            or dataset.pose_schema_id != split.get("pose_schema_id")
            or dataset.pose_schema_revision != split.get("pose_schema_revision")
            or dataset.pose_schema_content_hash != split.get("pose_schema_content_hash")
        ):
            raise ValidationError(
                f"The archived pose {role} dataset does not match its frozen provenance"
            )
        local[pin] = dataset.manifest_sha256
    old_dataset = split.get("training_dataset_manifest_sha256")
    if old_dataset != run.dataset_manifest_sha256:
        raise ValidationError("The archived pose training run names a different frozen dataset")

    updated_hash = canonical_json_sha256(local)
    restored = _local_manifest(manifest, split, local, "pose_split_manifest")
    snapshot = _local_manifest(run.draft_snapshot_json or {}, split, local, "split_manifest")
    if experiment is not None:
        if (
            experiment.project_id != run.project_id
            or experiment.dataset_manifest_sha256 != old_dataset
            or experiment.split_manifest_sha256 != original_hash
            or experiment.artifact_manifest_json.get("pose_split_manifest_sha256", original_hash)
            != original_hash
        ):
            raise ValidationError(
                "The archived pose experiment disagrees with its training dataset or split"
            )
        experiment.artifact_manifest_json = _local_manifest(
            experiment.artifact_manifest_json, split, local, "pose_split_manifest"
        )
        experiment.dataset_manifest_sha256 = local["training_dataset_manifest_sha256"]
        experiment.split_manifest_sha256 = updated_hash
    run.artifact_manifest_json = restored
    run.draft_snapshot_json = snapshot
    run.dataset_manifest_sha256 = local["training_dataset_manifest_sha256"]
    run.split_manifest_sha256 = updated_hash
    digests[original_hash] = updated_hash


def _legacy_package(session: Session, run: TrainingRun) -> ProjectExchangePackage | None:
    split = (run.artifact_manifest_json or {}).get("pose_split_manifest")
    if not isinstance(split, dict) or canonical_json_sha256(split) == run.split_manifest_sha256:
        return None
    return imported_pose_package(session, run)


def _restore_legacy(
    session: Session,
    run: TrainingRun,
    experiment: ExperimentRecord | None,
    package: ProjectExchangePackage,
) -> dict[str, str]:
    options = package.options_json
    digests = dict(options.get("digest_map", {}))
    source_ids = {local: source for source, local in options["id_map"].items()}
    previous_split, previous_dataset = run.split_manifest_sha256, run.dataset_manifest_sha256
    rebind_pose_training_run(session, run, source_ids, digests, experiment=experiment)
    if run.split_manifest_sha256 != previous_split:
        project = session.get(Project, run.project_id)
        if project is None:
            raise ValidationError("The imported pose training project is unavailable")
        source_root = (
            options.get("source_storage_root") or f"projects/{options['source_project_id']}"
        )
        bind_pose_history_digests(
            session,
            run,
            previous_split,
            previous_dataset,
            source_root,
            project.storage_root,
            digests,
        )
    return digests


def bind_pose_history_digests(
    session: Session,
    run: TrainingRun,
    previous_split: str,
    previous_dataset: str,
    source_root: str,
    target_root: str,
    digests: dict[str, str],
) -> None:
    run.artifact_manifest_json = local_pose_manifest_paths(
        run.artifact_manifest_json, source_root, target_root
    )
    experiment = session.scalar(
        select(ExperimentRecord).where(
            ExperimentRecord.project_id == run.project_id,
            ExperimentRecord.training_run_id == run.id,
        )
    )
    if experiment is not None:
        experiment.artifact_manifest_json = local_pose_manifest_paths(
            experiment.artifact_manifest_json, source_root, target_root
        )
    changed = restore_pose_training_history(
        session,
        run,
        source_split_sha256=previous_split,
        source_dataset_sha256=previous_dataset,
        source_storage_root=source_root,
        target_storage_root=target_root,
    )
    if changed:
        digests.update(
            {old: changed[current] for old, current in digests.items() if current in changed}
        )
        digests.update(changed)


def recover_imported_pose_training(session: Session, run: TrainingRun) -> None:
    """Earlier imports remapped the split UUIDs and kept its training-time hashes."""
    package = _legacy_package(session, run)
    if package is None:
        return
    experiment = session.scalar(
        select(ExperimentRecord).where(ExperimentRecord.training_run_id == run.id)
    )
    digests = _restore_legacy(session, run, experiment, package)
    package.options_json = {**package.options_json, "digest_map": digests}


def project_legacy_pose_export(session: Session, sections: dict[str, Sequence[Base]]) -> None:
    """Snapshot outgoing rows together and leave the source unchanged on success or failure."""
    legacy = [
        row
        for row in sections.get("training_runs", ())
        if isinstance(row, TrainingRun)
        and row.task == "pose"
        and _legacy_package(session, row) is not None
    ]
    if not legacy:
        return
    # The workflow provenance builder reads its dependent rows through the session. A savepoint
    # lets it see one consistent projection without committing repairs as a side effect of export.
    projection = session.begin_nested()
    try:
        for run in legacy:
            recover_imported_pose_training(session, run)
        session.flush()
        for name in (
            "training_runs",
            "experiments",
            "models",
            "jobs",
            "workflow_artifacts",
            "workflow_node_runs",
            "workflow_runs",
        ):
            if name not in sections:
                continue
            sections[name] = [
                type(row)(
                    **{attr.key: getattr(row, attr.key) for attr in row.__mapper__.column_attrs}
                )
                for row in sections[name]
            ]
    finally:
        projection.rollback()


def checkpoint_schema_matches(
    session: Session, run: TrainingRun, checkpoint_schema_id: Any, local_schema_id: str
) -> bool:
    if checkpoint_schema_id == local_schema_id:
        return True
    if not isinstance(checkpoint_schema_id, str):
        return False
    package = imported_pose_package(session, run)
    if package is None or canonical_json_sha256(package.manifest_json) != package.manifest_sha256:
        return False
    origin = package.manifest_json.get("origin") or {}
    source_id = origin.get("id_map", {}).get(checkpoint_schema_id, checkpoint_schema_id)
    mapped = package.options_json["id_map"].get(source_id)
    return isinstance(mapped, str) and mapped == local_schema_id
