"""Preview and apply conservative project-storage repairs."""

from __future__ import annotations

import hashlib
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    ArtifactRecord,
    ClassificationCrop,
    DepthMap,
    ExportRecord,
    ImageAsset,
    Job,
    MaskAnnotation,
    ModelRegistration,
    PredictionProposal,
    Project,
    TrainingRun,
    VideoAsset,
    WorkflowArtifact,
    WorkflowRun,
)
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.project_integrity import (
    ProjectRepairAction,
    ProjectRepairApplyResponse,
    ProjectRepairPlanResponse,
)
from reefvision.storage.projects import resolve_managed_project_path


def _as_utc_timestamp(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC)


def _action_id(kind: str, managed_path: str, *, size: int = 0, modified_ns: int = 0) -> str:
    payload = f"{kind}|{managed_path}|{size}|{modified_ns}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


def _path_strings(value: Any) -> list[str]:
    """Conservatively extract managed-path-looking strings from nested JSON."""

    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result: list[str] = []
        for item in value.values():
            result.extend(_path_strings(item))
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(_path_strings(item))
        return result
    return []


class ProjectRepairService:
    """Discover safe repairs and quarantine selected orphan files."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    def _reference_sets(
        self,
        project: Project,
    ) -> tuple[set[Path], set[Path], list[str]]:
        project_root = resolve_managed_project_path(self.settings, project.storage_root)
        exact: set[Path] = set()
        prefixes: set[Path] = set()
        warnings: list[str] = []

        def add(managed_path: str | None) -> None:
            if not managed_path:
                return
            normalized = managed_path.replace("\\", "/").strip()
            if not normalized.startswith(project.storage_root.rstrip("/") + "/"):
                return
            try:
                path = resolve_managed_project_path(self.settings, normalized)
                path.relative_to(project_root)
            except (ValidationError, ValueError):
                warnings.append(f"Ignored unsafe referenced path: {managed_path}")
                return
            exact.add(path)
            if path.is_dir():
                prefixes.add(path)

        for image in self.session.scalars(
            select(ImageAsset).where(ImageAsset.project_id == project.id)
        ):
            add(image.managed_path)
            add(image.thumbnail_path)

        image_ids = select(ImageAsset.id).where(ImageAsset.project_id == project.id)
        for mask in self.session.scalars(
            select(MaskAnnotation).where(MaskAnnotation.image_id.in_(image_ids))
        ):
            add(mask.mask_path)

        for model in self.session.scalars(
            select(ModelRegistration).where(ModelRegistration.project_id == project.id)
        ):
            add(model.managed_path)
            for path in _path_strings(model.metadata_json):
                add(path)

        for export in self.session.scalars(
            select(ExportRecord).where(ExportRecord.project_id == project.id)
        ):
            add(export.output_path)
            add(export.manifest_path)
            add(export.archive_path)

        for run in self.session.scalars(
            select(TrainingRun).where(TrainingRun.project_id == project.id)
        ):
            add(run.logs_path)
            add(run.result_checkpoint_path)
            for path in _path_strings(run.artifact_manifest_json):
                add(path)
            for path in _path_strings(run.metrics_json):
                add(path)

        for video in self.session.scalars(
            select(VideoAsset).where(VideoAsset.project_id == project.id)
        ):
            add(video.managed_path)

        for artifact in self.session.scalars(
            select(ArtifactRecord).where(ArtifactRecord.project_id == project.id)
        ):
            add(artifact.managed_path)
            for path in _path_strings(artifact.metadata_json):
                add(path)

        for crop in self.session.scalars(
            select(ClassificationCrop).where(ClassificationCrop.project_id == project.id)
        ):
            add(crop.managed_path)

        for depth_map in self.session.scalars(
            select(DepthMap).where(DepthMap.project_id == project.id)
        ):
            add(depth_map.managed_path)
            add(depth_map.preview_path)

        for proposal in self.session.scalars(
            select(PredictionProposal).where(PredictionProposal.project_id == project.id)
        ):
            add(proposal.mask_path)

        for workflow_artifact in self.session.scalars(
            select(WorkflowArtifact)
            .join(WorkflowRun, WorkflowRun.id == WorkflowArtifact.workflow_run_id)
            .where(WorkflowRun.project_id == project.id)
        ):
            add(workflow_artifact.managed_path)
            for path in _path_strings(workflow_artifact.payload_json):
                add(path)

        for job in self.session.scalars(select(Job).where(Job.project_id == project.id)):
            for path in _path_strings(job.request_json):
                add(path)
            for path in _path_strings(job.result_json or {}):
                add(path)

        return exact, prefixes, warnings

    @staticmethod
    def _referenced(path: Path, exact: set[Path], prefixes: set[Path]) -> bool:
        if path in exact:
            return True
        return any(prefix == path or prefix in path.parents for prefix in prefixes)

    def plan(
        self,
        project_id: str,
        *,
        minimum_orphan_age_seconds: int = 3600,
    ) -> ProjectRepairPlanResponse:
        if minimum_orphan_age_seconds < 60:
            raise ValidationError("minimum_orphan_age_seconds must be at least 60")
        project = self._project(project_id)
        project_root = resolve_managed_project_path(self.settings, project.storage_root)
        now = datetime.now(UTC)
        actions: list[ProjectRepairAction] = []
        warnings: list[str] = []

        if not project_root.exists():
            actions.append(
                ProjectRepairAction(
                    action_id=_action_id("create_project_root", project.storage_root),
                    action_kind="create_project_root",
                    managed_path=project.storage_root,
                    reason="The managed project root is missing.",
                )
            )
            return ProjectRepairPlanResponse(
                project_id=project.id,
                generated_at=now,
                minimum_orphan_age_seconds=minimum_orphan_age_seconds,
                referenced_path_count=0,
                orphan_file_count=0,
                orphan_file_bytes=0,
                actions=actions,
                warnings=warnings,
            )
        if not project_root.is_dir():
            raise ValidationError("The managed project root exists but is not a directory")

        exact, prefixes, reference_warnings = self._reference_sets(project)
        warnings.extend(reference_warnings)
        cutoff = now - timedelta(seconds=minimum_orphan_age_seconds)
        orphan_bytes = 0
        for path in sorted(project_root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(project_root)
            if relative.parts and relative.parts[0] == ".quarantine":
                continue
            modified = _as_utc_timestamp(path)
            if modified >= cutoff:
                continue
            resolved = path.resolve()
            try:
                resolved.relative_to(project_root.resolve())
            except ValueError:
                warnings.append(f"Skipped path outside the resolved project root: {relative}")
                continue
            if self._referenced(resolved, exact, prefixes):
                continue
            stat = path.stat()
            managed_path = path.relative_to(self.settings.resolved_data_dir).as_posix()
            orphan_bytes += stat.st_size
            actions.append(
                ProjectRepairAction(
                    action_id=_action_id(
                        "quarantine_orphan_file",
                        managed_path,
                        size=stat.st_size,
                        modified_ns=stat.st_mtime_ns,
                    ),
                    action_kind="quarantine_orphan_file",
                    managed_path=managed_path,
                    reason=(
                        "The file is older than the safety window and is not referenced by "
                        "a known project record or artifact manifest."
                    ),
                    size_bytes=stat.st_size,
                    modified_at=modified,
                )
            )

        actions.sort(key=lambda item: (item.action_kind, item.managed_path))
        return ProjectRepairPlanResponse(
            project_id=project.id,
            generated_at=now,
            minimum_orphan_age_seconds=minimum_orphan_age_seconds,
            referenced_path_count=len(exact | prefixes),
            orphan_file_count=sum(
                1 for action in actions if action.action_kind == "quarantine_orphan_file"
            ),
            orphan_file_bytes=orphan_bytes,
            actions=actions,
            warnings=warnings,
        )

    def apply(
        self,
        project_id: str,
        action_ids: list[str],
        *,
        minimum_orphan_age_seconds: int = 3600,
    ) -> ProjectRepairApplyResponse:
        project = self._project(project_id)
        plan = self.plan(
            project_id,
            minimum_orphan_age_seconds=minimum_orphan_age_seconds,
        )
        known = {action.action_id: action for action in plan.actions}
        requested = list(dict.fromkeys(action_ids))
        if set(requested) - known.keys():
            raise ValidationError(
                "The repair plan changed; regenerate the preview before applying actions"
            )

        project_root = resolve_managed_project_path(self.settings, project.storage_root)
        applied: list[str] = []
        skipped: list[str] = []
        quarantined: list[str] = []
        created: list[str] = []
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        for action_id in requested:
            action = known[action_id]
            if action.action_kind == "create_project_root":
                if project_root.exists():
                    skipped.append(action_id)
                    continue
                project_root.mkdir(parents=True, exist_ok=False)
                created.append(project.storage_root)
                applied.append(action_id)
                continue

            source = resolve_managed_project_path(self.settings, action.managed_path)
            if not source.is_file() or source.is_symlink():
                skipped.append(action_id)
                continue
            stat = source.stat()
            current_id = _action_id(
                "quarantine_orphan_file",
                action.managed_path,
                size=stat.st_size,
                modified_ns=stat.st_mtime_ns,
            )
            if current_id != action_id:
                skipped.append(action_id)
                continue
            relative = source.relative_to(project_root)
            destination = project_root / ".quarantine" / "orphans" / stamp / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                destination = destination.with_name(f"{action_id}-{destination.name}")
            shutil.move(str(source), destination)
            quarantined.append(
                destination.relative_to(self.settings.resolved_data_dir).as_posix()
            )
            applied.append(action_id)

        return ProjectRepairApplyResponse(
            project_id=project.id,
            applied_at=datetime.now(UTC),
            applied_action_ids=applied,
            skipped_action_ids=skipped,
            quarantined_paths=quarantined,
            created_paths=created,
        )
