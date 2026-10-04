"""Workflow adapter for verified ReefVision Results Packages."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    Project,
    TrainingRun,
    WorkflowArtifact,
)
from reefvision.domain.errors import ValidationError
from reefvision.schemas.results_packages import (
    ResultsPackageOptions,
)
from reefvision.services import (
    workflow_runtime_adapters as runtime_adapters,
)
from reefvision.services.results_packages import (
    ResultsPackageService,
)
from reefvision.storage.models import hash_model_file
from reefvision.storage.projects import (
    resolve_managed_project_path,
)

RESULTS_PACKAGE_WORKFLOW_NODE_TYPES = {
    "training_results_package",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)

    return digest.hexdigest()


def execute_training_results_package_adapter(
    session: Session,
    settings: Settings,
    project_id: str,
    parameters: dict[str, Any],
    inputs: dict[str, list[WorkflowArtifact]],
) -> list[dict[str, Any]]:
    source = runtime_adapters._single_artifact(
        inputs,
        "training",
    )

    training_payload = dict(source.payload_json or {})

    if training_payload.get("project_id") != project_id:
        raise ValidationError("Training Results Package received a result from another project")

    training_run_id = str(training_payload.get("training_run_id") or "")

    if not training_run_id:
        raise ValidationError("Training Results Package requires a persisted training_run_id")

    run = session.get(
        TrainingRun,
        training_run_id,
    )

    if run is None or run.project_id != project_id:
        raise ValidationError("Training Results Package requires a training run from this project")

    advertised_dataset_sha = str(training_payload.get("dataset_manifest_sha256") or "")

    if (
        advertised_dataset_sha
        and run.dataset_manifest_sha256
        and advertised_dataset_sha != run.dataset_manifest_sha256
    ):
        raise ValidationError("Training dataset manifest changed before Results Package creation")

    advertised_split_sha = str(training_payload.get("split_manifest_sha256") or "")

    if (
        advertised_split_sha
        and run.split_manifest_sha256
        and advertised_split_sha != run.split_manifest_sha256
    ):
        raise ValidationError("Training split manifest changed before Results Package creation")

    advertised_checkpoint_sha = str(training_payload.get("result_checkpoint_sha256") or "")

    if advertised_checkpoint_sha and run.result_checkpoint_path:
        checkpoint = resolve_managed_project_path(
            settings,
            run.result_checkpoint_path,
        )

        if not checkpoint.is_file():
            raise ValidationError("Training checkpoint is missing before Results Package creation")

        actual_checkpoint_sha, _ = hash_model_file(checkpoint)

        if actual_checkpoint_sha != advertised_checkpoint_sha:
            raise ValidationError(
                "Training checkpoint checksum changed before Results Package creation"
            )

    options = ResultsPackageOptions(
        include_excel=bool(
            parameters.get(
                "include_excel",
                True,
            )
        ),
        include_machine_data=bool(
            parameters.get(
                "include_machine_data",
                True,
            )
        ),
        include_native_artifacts=bool(
            parameters.get(
                "include_native_artifacts",
                True,
            )
        ),
        include_logs=bool(
            parameters.get(
                "include_logs",
                True,
            )
        ),
        checkpoint_mode=str(
            parameters.get(
                "checkpoint_mode",
                "best",
            )
        ),
    )

    service = ResultsPackageService(
        session,
        settings,
    )

    package = service.create(
        training_run_id,
        options,
    )

    verification = service.verify(
        training_run_id,
        package.package_name,
    )

    if not verification.valid:
        raise ValidationError(
            "Results Package failed post-build verification: " + "; ".join(verification.errors)
        )

    archive = service.archive(
        training_run_id,
        package.archive_name,
    )

    archive_sha256 = _sha256_file(archive)

    if archive.stat().st_size != package.archive_size_bytes:
        raise ValidationError("Results Package archive size changed after creation")

    project = session.get(
        Project,
        project_id,
    )

    if project is None:
        raise ValidationError("Results Package project no longer exists")

    package_directory_path = f"{project.storage_root}/results-packages/{package.package_name}"

    archive_path = f"{project.storage_root}/results-packages/{package.archive_name}"

    return [
        {
            "port_id": "package",
            "data_type": "results_package",
            "payload": {
                "schema_version": ("workflow-results-package-0001"),
                "project_id": project_id,
                "training_run_id": training_run_id,
                "source_training_artifact_id": source.id,
                "source_training_artifact_sha256": (source.payload_sha256),
                "package_type": package.package_type,
                "package_name": package.package_name,
                "archive_name": package.archive_name,
                "archive_size_bytes": (package.archive_size_bytes),
                "archive_sha256": archive_sha256,
                "package_directory_path": (package_directory_path),
                "archive_path": archive_path,
                "verification_status": (package.verification_status),
                "verification_valid": (verification.valid),
                "verification_checked_files": (verification.checked_files),
                "verification_errors": list(verification.errors),
                "warnings": list(package.warnings),
                "download_url": (package.download_url),
                "options": options.model_dump(mode="json"),
                "dataset_version_id": (run.dataset_version_id),
                "dataset_manifest_sha256": (run.dataset_manifest_sha256),
                "split_manifest_sha256": (run.split_manifest_sha256),
                "result_checkpoint_sha256": (advertised_checkpoint_sha or None),
                "pose_training_dataset_id": training_payload.get("pose_training_dataset_id"),
                "pose_validation_dataset_id": training_payload.get("pose_validation_dataset_id"),
                "pose_schema_id": training_payload.get("pose_schema_id"),
                "pose_schema_revision": training_payload.get("pose_schema_revision"),
                "pose_schema_content_hash": training_payload.get("pose_schema_content_hash"),
                "validation_mode": training_payload.get("validation_mode"),
                "source_workflow_run_id": (training_payload.get("workflow_run_id")),
                "source_workflow_node_run_id": (training_payload.get("workflow_node_run_id")),
            },
        }
    ]


_RESULTS_PACKAGE_ADAPTERS = {
    "training_results_package": (execute_training_results_package_adapter),
}


def register_results_package_workflow_adapter() -> None:
    """Install Results Package workflow execution."""

    runtime_adapters.RUNTIME_ADAPTER_NODE_TYPES.update(_RESULTS_PACKAGE_ADAPTERS)

    runtime_adapters._ADAPTERS.update(_RESULTS_PACKAGE_ADAPTERS)
