"""Scientific Training and Tuning Results Package orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import DatasetVersion, DatasetVersionItem, Project, TrainingRun
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.results_packages import (
    ResultsPackageOptions,
    ResultsPackageResponse,
    ResultsPackageVerificationResponse,
)
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.storage.results_packages import build_results_package, verify_results_package


class ResultsPackageService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def create(self, run_id: str, options: ResultsPackageOptions) -> ResultsPackageResponse:
        run = self.session.get(TrainingRun, run_id)
        if run is None:
            raise NotFoundError("Training run not found")
        if run.status in {
            "queued",
            "preflight",
            "preparing_dataset",
            "training",
            "tuning",
            "running",
            "cancel_requested",
        }:
            raise ValidationError(
                "A final Results Package is available only after the run reaches a terminal state"
            )
        project = self.session.get(Project, run.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        version = (
            self.session.get(DatasetVersion, run.dataset_version_id)
            if run.dataset_version_id
            else None
        )
        items = (
            list(
                self.session.scalars(
                    select(DatasetVersionItem)
                    .where(DatasetVersionItem.dataset_version_id == version.id)
                    .order_by(DatasetVersionItem.split, DatasetVersionItem.image_id)
                )
            )
            if version
            else []
        )
        sources = self._artifact_sources(run)
        export_root = resolve_managed_project_path(
            self.settings, f"{project.storage_root}/results-packages"
        )
        result = build_results_package(
            export_root=export_root,
            run=self._run_data(run),
            project={"id": project.id, "name": project.name, "slug": project.slug},
            dataset=self._dataset_data(version) if version else None,
            dataset_items=[self._item_data(item) for item in items],
            source_artifacts=sources,
            options=options.model_dump(mode="json"),
        )
        return ResultsPackageResponse(
            run_id=run.id,
            package_type=result["package_type"],
            package_name=result["package_name"],
            archive_name=result["archive_name"],
            archive_size_bytes=result["archive_size_bytes"],
            verification_status="verified",
            warnings=result["warnings"],
            download_url=(f"/training-runs/{run.id}/results-packages/{result['archive_name']}"),
        )

    def archive(self, run_id: str, archive_name: str) -> Path:
        run = self.session.get(TrainingRun, run_id)
        if run is None:
            raise NotFoundError("Training run not found")
        project = self.session.get(Project, run.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        if Path(archive_name).name != archive_name or not archive_name.endswith(".zip"):
            raise ValidationError("Invalid Results Package archive name")
        root = resolve_managed_project_path(
            self.settings, f"{project.storage_root}/results-packages"
        )
        path = (root / archive_name).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise NotFoundError("Results Package archive not found")
        return path

    def verify(self, run_id: str, package_name: str) -> ResultsPackageVerificationResponse:
        run = self.session.get(TrainingRun, run_id)
        if run is None:
            raise NotFoundError("Training run not found")
        project = self.session.get(Project, run.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        if Path(package_name).name != package_name:
            raise ValidationError("Invalid Results Package name")
        root = resolve_managed_project_path(
            self.settings, f"{project.storage_root}/results-packages"
        )
        package = (root / package_name).resolve()
        if not package.is_relative_to(root.resolve()) or not package.is_dir():
            raise NotFoundError("Results Package not found")
        result = verify_results_package(package)
        return ResultsPackageVerificationResponse(**result)

    def _artifact_sources(self, run: TrainingRun) -> list[tuple[dict[str, Any], Path]]:
        result: list[tuple[dict[str, Any], Path]] = []
        artifacts = run.artifact_manifest_json.get("artifacts", [])
        if isinstance(artifacts, list):
            for artifact in artifacts:
                if not isinstance(artifact, dict):
                    continue
                relative = artifact.get("relative_path")
                if not isinstance(relative, str):
                    continue
                path = resolve_managed_project_path(self.settings, relative)
                result.append((dict(artifact), path))
        if run.logs_path:
            log_path = resolve_managed_project_path(self.settings, run.logs_path)
            if not any(path == log_path for _, path in result):
                result.append(
                    (
                        {
                            "name": log_path.name,
                            "category": "log",
                            "relative_path": run.logs_path,
                        },
                        log_path,
                    )
                )
        return result

    def _run_data(self, run: TrainingRun) -> dict[str, Any]:
        manifest = dict(run.artifact_manifest_json)
        return {
            "id": run.id,
            "run_name": run.run_name,
            "status": run.status,
            "stage": run.stage,
            "task": run.task,
            "provider_id": run.provider_id,
            "architecture": run.architecture,
            "dataset_version_id": run.dataset_version_id,
            "dataset_manifest_sha256": run.dataset_manifest_sha256,
            "split_manifest_sha256": run.split_manifest_sha256,
            "initial_checkpoint_source": run.initial_checkpoint_source,
            "initial_checkpoint_model_id": run.initial_checkpoint_model_id,
            "resolved_model_asset_id": run.resolved_model_asset_id,
            "resolved_model_checksum": run.resolved_model_checksum,
            "device": run.device,
            "precision": run.precision,
            "random_seed": run.random_seed,
            "training_config": dict(run.training_config_json),
            "tuning_config": dict(run.tuning_config_json),
            "evaluation_config": dict(run.evaluation_config_json),
            "tiling_config": dict(run.tiling_config_json),
            "resource_limits": dict(run.resource_limits_json),
            "preflight_report": dict(run.preflight_report_json),
            "draft_snapshot": dict(run.draft_snapshot_json),
            "metrics": dict(run.metrics_json),
            "metrics_history": dict(run.metrics_history_json),
            "native_results_rows": manifest.get("native_results_rows", []),
            "per_class_metrics": manifest.get("per_class_metrics", []),
            "confusion_matrix": manifest.get("confusion_matrix"),
            "confusion_matrix_normalized": manifest.get("confusion_matrix_normalized"),
            "tuning_results": manifest.get("tuning_results"),
            "result_checkpoint_path": run.result_checkpoint_path,
            "warnings": list(run.warnings_json),
            "error_message": run.error_message,
            "created_at": run.created_at.isoformat(),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }

    def _dataset_data(self, version: DatasetVersion) -> dict[str, Any]:
        return {
            "id": version.id,
            "name": version.name,
            "version_number": version.version_number,
            "manifest_sha256": version.manifest_sha256,
            "class_map": list(version.class_map_json),
            "image_count": version.image_count,
            "annotation_count": version.annotation_count,
            "split_seed": version.split_seed,
            "requested_ratios": version.requested_ratios_json,
            "achieved_ratios": version.achieved_ratios_json,
            "reefvision_version": version.reefvision_version,
            "schema_version": version.schema_version,
            "created_at": version.created_at.isoformat(),
        }

    def _item_data(self, item: DatasetVersionItem) -> dict[str, Any]:
        return {
            "image_id": item.image_id,
            "original_filename": item.original_filename,
            "image_sha256": item.image_sha256,
            "split": item.split,
            "group_key": item.group_key,
            "annotation_count": item.annotation_count,
            "per_class_counts": item.per_class_counts_json,
        }
