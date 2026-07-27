"""Preview, quarantine, and restore terminal workflow artifacts conservatively."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
    WorkflowArtifactQuarantineItem,
    WorkflowArtifactQuarantineResponse,
    WorkflowArtifactRestoreRequest,
    WorkflowArtifactRestoreResponse,
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


def _valid_sha256(value: object) -> str | None:
    candidate = str(value or "").strip().casefold()
    if len(candidate) != 64 or any(character not in "0123456789abcdef" for character in candidate):
        return None
    return candidate


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

    def _managed_path_blockers(
        self,
        managed_path: str,
        *,
        artifact_id: str,
    ) -> list[str]:
        blockers: list[str] = []
        other_workflow = self.session.scalar(
            select(WorkflowArtifact.id).where(
                WorkflowArtifact.id != artifact_id,
                WorkflowArtifact.managed_path == managed_path,
            )
        )
        if other_workflow is not None:
            blockers.append("Another workflow artifact references this managed file.")
        other_artifact = self.session.scalar(
            select(ArtifactRecord.id).where(ArtifactRecord.managed_path == managed_path)
        )
        if other_artifact is not None:
            blockers.append("A registered project artifact references this managed file.")
        return blockers

    def _shared_reference_blockers(self, artifact: WorkflowArtifact) -> list[str]:
        if not artifact.managed_path:
            return []
        return self._managed_path_blockers(
            artifact.managed_path,
            artifact_id=artifact.id,
        )

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
                blockers.append(
                    "Only files inside the project's workflows directory can be cleaned."
                )
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
            project_root / "workflow-quarantine" / run.id / timestamp.strftime("%Y%m%dT%H%M%S%fZ")
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
                original_artifact_checksum = artifact.checksum
                original_size_bytes = artifact.size_bytes
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
                    "original_artifact_checksum": original_artifact_checksum,
                    "original_size_bytes": original_size_bytes,
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

    def quarantine(self, run_id: str) -> WorkflowArtifactQuarantineResponse:
        run, project = self._context(run_id)
        project_root = resolve_managed_project_path(self.settings, project.storage_root)
        workflow_root = (project_root / "workflows").resolve()
        quarantine_root = (project_root / "workflow-quarantine").resolve()
        artifacts = list(
            self.session.scalars(
                select(WorkflowArtifact)
                .where(WorkflowArtifact.workflow_run_id == run.id)
                .order_by(
                    WorkflowArtifact.node_id,
                    WorkflowArtifact.port_name,
                    WorkflowArtifact.id,
                )
            )
        )
        items: list[WorkflowArtifactQuarantineItem] = []
        for artifact in artifacts:
            payload = dict(artifact.payload_json or {})
            cleanup_raw = payload.get("_cleanup")
            if not isinstance(cleanup_raw, dict):
                continue
            cleanup: dict[str, Any] = cleanup_raw
            if cleanup.get("action_kind") != "quarantine_file":
                continue
            original = str(cleanup.get("original_managed_path") or "").strip()
            quarantine = str(cleanup.get("quarantine_path") or "").strip()
            if not original or not quarantine:
                continue
            blockers = self._managed_path_blockers(original, artifact_id=artifact.id)
            try:
                original_path = resolve_managed_project_path(self.settings, original)
                quarantine_path = resolve_managed_project_path(self.settings, quarantine)
            except ValidationError as exc:
                blockers.append(str(exc))
                original_path = project_root
                quarantine_path = project_root
            if not original_path.is_relative_to(workflow_root):
                blockers.append("The original path is outside the workflow directory.")
            if not quarantine_path.is_relative_to(quarantine_root):
                blockers.append("The quarantine path is outside workflow quarantine.")
            if original_path.exists():
                blockers.append("The original destination already exists.")
            if quarantine_path.is_symlink():
                blockers.append("Quarantined symbolic links cannot be restored.")
            if not quarantine_path.is_file():
                blockers.append("The quarantined file is missing.")
            expected_sha = _valid_sha256(cleanup.get("file_sha256"))
            if (
                quarantine_path.is_file()
                and expected_sha is not None
                and _file_sha256(quarantine_path) != expected_sha
            ):
                blockers.append("The quarantined file checksum has changed.")
            size_bytes = max(0, int(cleanup.get("size_bytes") or 0))
            items.append(
                WorkflowArtifactQuarantineItem(
                    artifact_id=artifact.id,
                    node_id=artifact.node_id,
                    port_name=artifact.port_name,
                    original_managed_path=original,
                    quarantine_path=quarantine,
                    file_sha256=expected_sha,
                    size_bytes=size_bytes,
                    quarantined_at=str(cleanup.get("applied_at") or ""),
                    restorable=not blockers,
                    blockers=blockers,
                )
            )
        return WorkflowArtifactQuarantineResponse(
            workflow_run_id=run.id,
            item_count=len(items),
            restorable_count=sum(item.restorable for item in items),
            total_bytes=sum(item.size_bytes for item in items),
            items=items,
        )

    def restore(
        self,
        run_id: str,
        request: WorkflowArtifactRestoreRequest,
    ) -> WorkflowArtifactRestoreResponse:
        quarantine = self.quarantine(run_id)
        selected_ids = list(dict.fromkeys(request.artifact_ids))
        if len(selected_ids) != len(request.artifact_ids):
            raise ValidationError("Workflow restore artifact IDs must be unique")
        item_by_id = {item.artifact_id: item for item in quarantine.items}
        selected: list[WorkflowArtifactQuarantineItem] = []
        for artifact_id in selected_ids:
            item = item_by_id.get(artifact_id)
            if item is None:
                raise ValidationError("A selected artifact is not in workflow quarantine")
            if not item.restorable:
                raise ValidationError("Blocked workflow quarantine items cannot be restored")
            selected.append(item)

        run, _project = self._context(run_id)
        restored_moves: list[tuple[Path, Path]] = []
        restored_paths: list[str] = []
        restored_bytes = 0
        restored_at = datetime.now(UTC)
        try:
            for item in selected:
                artifact = self.session.get(WorkflowArtifact, item.artifact_id)
                if artifact is None or artifact.workflow_run_id != run.id:
                    raise ConflictError("A quarantined workflow artifact changed")
                payload = dict(artifact.payload_json or {})
                cleanup_raw = payload.get("_cleanup")
                if not isinstance(cleanup_raw, dict):
                    raise ConflictError("Workflow artifact cleanup metadata is missing")
                cleanup = dict(cleanup_raw)
                if (
                    str(cleanup.get("original_managed_path") or "") != item.original_managed_path
                    or str(cleanup.get("quarantine_path") or "") != item.quarantine_path
                ):
                    raise ConflictError("Workflow artifact cleanup metadata changed")
                source = resolve_managed_project_path(
                    self.settings,
                    item.quarantine_path,
                )
                destination = resolve_managed_project_path(
                    self.settings,
                    item.original_managed_path,
                )
                if not source.is_file() or destination.exists():
                    raise ConflictError("Workflow quarantine changed before restore")
                if item.file_sha256 and _file_sha256(source) != item.file_sha256:
                    raise ConflictError("Quarantined workflow artifact checksum changed")
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, destination)
                restored_moves.append((source, destination))

                payload.pop("_cleanup", None)
                history_raw = payload.get("_cleanup_history")
                history = list(history_raw) if isinstance(history_raw, list) else []
                history.append(
                    {
                        **cleanup,
                        "restored_at": restored_at.isoformat(),
                        "restored_managed_path": item.original_managed_path,
                    }
                )
                payload["_cleanup_history"] = history[-100:]
                artifact.payload_json = payload
                artifact.managed_path = item.original_managed_path
                artifact.size_bytes = item.size_bytes
                artifact.checksum = _valid_sha256(
                    cleanup.get("original_artifact_checksum")
                ) or canonical_json_sha256(payload)
                restored_paths.append(item.original_managed_path)
                restored_bytes += item.size_bytes
            self.session.commit()
        except Exception:
            self.session.rollback()
            for source, destination in reversed(restored_moves):
                if destination.exists() and not source.exists():
                    source.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(destination, source)
            raise

        return WorkflowArtifactRestoreResponse(
            workflow_run_id=run.id,
            restored_artifact_count=len(selected),
            restored_bytes=restored_bytes,
            restored_paths=restored_paths,
        )
