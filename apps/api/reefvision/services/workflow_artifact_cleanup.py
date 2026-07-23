"""Preview and apply conservative cleanup of terminal workflow artifacts."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import ArtifactRecord, Project, WorkflowArtifact, WorkflowRun
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.workflow_cleanup import (
    WorkflowArtifactCleanupAction,
    WorkflowArtifactCleanupApplyRequest,
    WorkflowArtifactCleanupApplyResponse,
    WorkflowArtifactCleanupPreviewRequest,
    WorkflowArtifactCleanupPreviewResponse,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.projects import resolve_managed_project_path

_TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _action_id(
    artifact: WorkflowArtifact,
    *,
    action_kind: str,
    file_sha256: str | None,
    size_bytes: int,
) -> str:
    value = (
        f"{artifact.id}|{artifact.managed_path}|{action_kind}|"
        f"{file_sha256 or 'missing'}|{size_bytes}"
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


class WorkflowArtifactCleanupService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _context(self, run_id: str) -> tuple[WorkflowRun, Project]:
        run = self.session.get(WorkflowRun, run_id)
        if run is None:
            raise NotFoundError("Workflow run not found")
        project = self.session.get(Project, run.project_id)
        if project is None:
            raise NotFoundError("Workflow project not found")
        if run.status not in _TERMINAL_STATUSES:
            raise ConflictError("Only terminal workflow runs can have artifacts cleaned")
        return run, project

    def _shared_reference_blockers(self, artifact: WorkflowArtifact) -> list[str]:
        if not artifact.managed_path:
            return []
        blockers: list[str] = []
        other_workflow = self.session.scalar(
            select(WorkflowArtifact.id).where(
                WorkflowArtifact.id != artifact.id,
                WorkflowArtifact.managed_path == artifact.managed_path,
            )
        )
        if other_workflow is not None:
            blockers.append("Another workflow artifact references this managed file.")
        other_artifact = self.session.scalar(
            select(ArtifactRecord.id).where(
                ArtifactRecord.managed_path == artifact.managed_path
            )
        )
        if other_artifact is not None:
            blockers.append("A registered project artifact references this managed file.")
        return blockers

    def preview(
        self,
        run_id: str,
        request: WorkflowArtifactCleanupPreviewRequest,
    ) -> WorkflowArtifactCleanupPreviewResponse:
        run, project = self._context(run_id)
        query = select(WorkflowArtifact).where(
            WorkflowArtifact.workflow_run_id == run.id,
            WorkflowArtifact.managed_path.is_not(None),
        )
        if request.node_ids:
            query = query.where(WorkflowArtifact.node_id.in_(request.node_ids))
        artifacts = list(
            self.session.scalars(
                query.order_by(
                    WorkflowArtifact.node_id,
                    WorkflowArtifact.port_name,
                    WorkflowArtifact.id,
                )
            )
        )
        project_root = resolve_managed_project_path(self.settings, project.storage_root)
        workflow_root = (project_root / "workflows").resolve()
        actions: list[WorkflowArtifactCleanupAction] = []
        for artifact in artifacts:
            assert artifact.managed_path is not None
            blockers = self._shared_reference_blockers(artifact)
            try:
                path = resolve_managed_project_path(self.settings, artifact.managed_path)
            except ValidationError as exc:
                actions.append(
                    WorkflowArtifactCleanupAction(
                        action_id=_action_id(
                            artifact,
                            action_kind="clear_missing_reference",
                            file_sha256=None,
                            size_bytes=0,
                        ),
                        action_kind="clear_missing_reference",
                        artifact_id=artifact.id,
                        node_id=artifact.node_id,
                        port_name=artifact.port_name,
                        managed_path=artifact.managed_path,
                        size_bytes=0,
                        eligible=False,
                        blockers=[*blockers, str(exc)],
                    )
                )
                continue
            if not path.is_relative_to(workflow_root):
                blockers.append("Only files inside the project's workflows directory can be cleaned.")
            if path.is_symlink():
                blockers.append("Symbolic links are never moved by workflow cleanup.")
            if not path.exists():
                action_kind = "clear_missing_reference"
                size_bytes = 0
                checksum = None
            elif not path.is_file():
                action_kind = "quarantine_file"
                size_bytes = 0
                checksum = None
                blockers.append("Workflow cleanup currently supports files, not directories.")
            else:
                action_kind = "quarantine_file"
                size_bytes = int(path.stat().st_size)
                checksum = _file_sha256(path)
            actions.append(
                WorkflowArtifactCleanupAction(
                    action_id=_action_id(
                        artifact,
                        action_kind=action_kind,
                        file_sha256=checksum,
                        size_bytes=size_bytes,
                    ),
                    action_kind=action_kind,
                    artifact_id=artifact.id,
                    node_id=artifact.node_id,
                    port_name=artifact.port_name,
                    managed_path=artifact.managed_path,
                    size_bytes=size_bytes,
                    file_sha256=checksum,
                    eligible=not blockers,
                    blockers=blockers,
                )
            )
        checksum_payload = {
            "workflow_run_id": run.id,
            "run_status": run.status,
            "node_ids": sorted(request.node_ids),
            "actions": [item.model_dump(mode="json") for item in actions],
        }
        return WorkflowArtifactCleanupPreviewResponse(
            workflow_run_id=run.id,
            run_status=run.status,
            preview_checksum=canonical_json_sha256(checksum_payload),
            action_count=len(actions),
            eligible_action_count=sum(item.eligible for item in actions),
            reclaimable_bytes=sum(item.size_bytes for item in actions if item.eligible),
            actions=actions,
        )

    def apply(
        self,
        run_id: str,
        request: WorkflowArtifactCleanupApplyRequest,
    ) -> WorkflowArtifactCleanupApplyResponse:
        preview = self.preview(
            run_id,
            WorkflowArtifactCleanupPreviewRequest(node_ids=request.node_ids),
        )
        if preview.preview_checksum != request.preview_checksum:
            raise ConflictError("The workflow cleanup preview is stale; preview again")
        action_by_id = {item.action_id: item for item in preview.actions}
        selected_ids = list(dict.fromkeys(request.action_ids))
        if len(selected_ids) != len(request.action_ids):
            raise ValidationError("Workflow cleanup action IDs must be unique")
        selected: list[WorkflowArtifactCleanupAction] = []
        for action_id in selected_ids:
            action = action_by_id.get(action_id)
            if action is None:
                raise ValidationError("A selected workflow cleanup action is not in the preview")
            if not action.eligible:
                raise ValidationError("Blocked workflow cleanup actions cannot be applied")
            selected.append(action)

        run, project = self._context(run_id)
        project_root = resolve_managed_project_path(self.settings, project.storage_root)
        workflow_root = (project_root / "workflows").resolve()
        timestamp = datetime.now(UTC)
        quarantine_root = (
            project_root
            / "workflow-quarantine"
            / run.id
            / timestamp.strftime("%Y%m%dT%H%M%S%fZ")
        ).resolve()
        if not quarantine_root.is_relative_to(project_root):
            raise ValidationError("Workflow quarantine path escaped the project")

        moved: list[tuple[Path, Path]] = []
        quarantine_paths: list[str] = []
        quarantined_count = 0
        cleared_count = 0
        reclaimed_bytes = 0
        try:
            for action in selected:
                artifact = self.session.get(WorkflowArtifact, action.artifact_id)
                if (
                    artifact is None
                    or artifact.workflow_run_id != run.id
                    or artifact.managed_path != action.managed_path
                ):
                    raise ConflictError("A workflow artifact changed after preview")
                original_path = artifact.managed_path
                quarantine_relative: str | None = None
                if action.action_kind == "quarantine_file":
                    source = resolve_managed_project_path(self.settings, original_path)
                    if not source.is_file() or _file_sha256(source) != action.file_sha256:
                        raise ConflictError("A workflow artifact file changed after preview")
                    relative = source.relative_to(workflow_root)
                    destination = (quarantine_root / relative).resolve()
                    if not destination.is_relative_to(quarantine_root):
                        raise ValidationError("Workflow quarantine destination escaped its root")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if destination.exists():
                        raise ConflictError("Workflow quarantine destination already exists")
                    os.replace(source, destination)
                    moved.append((source, destination))
                    quarantine_relative = destination.relative_to(
                        self.settings.resolved_data_dir
                    ).as_posix()
                    quarantine_paths.append(quarantine_relative)
                    quarantined_count += 1
                    reclaimed_bytes += action.size_bytes
                else:
                    cleared_count += 1

                payload = dict(artifact.payload_json or {})
                payload.pop("_cache_key", None)
                payload["_cleanup"] = {
                    "action_id": action.action_id,
                    "action_kind": action.action_kind,
                    "original_managed_path": original_path,
                    "quarantine_path": quarantine_relative,
                    "file_sha256": action.file_sha256,
                    "size_bytes": action.size_bytes,
                    "applied_at": timestamp.isoformat(),
                }
                artifact.payload_json = payload
                artifact.checksum = canonical_json_sha256(payload)
                artifact.managed_path = None
                artifact.size_bytes = None
            self.session.commit()
        except Exception:
            self.session.rollback()
            for source, destination in reversed(moved):
                if destination.exists() and not source.exists():
                    source.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(destination, source)
            raise

        return WorkflowArtifactCleanupApplyResponse(
            workflow_run_id=run.id,
            applied_action_count=len(selected),
            quarantined_file_count=quarantined_count,
            cleared_reference_count=cleared_count,
            reclaimed_bytes=reclaimed_bytes,
            quarantine_paths=quarantine_paths,
        )
