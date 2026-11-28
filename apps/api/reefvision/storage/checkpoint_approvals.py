"""Local execution approvals for researcher-supplied checkpoint files."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from reefvision.config import Settings
from reefvision.db.models import ModelRegistration
from reefvision.domain.errors import ConflictError, ValidationError
from reefvision.ml.model_bundles import checkpoint_requires_trust, require_checkpoint_trust
from reefvision.schemas.models import ModelRegistrationResponse
from reefvision.storage.models import hash_model_file
from reefvision.storage.projects import filesystem_io_path, resolve_managed_project_path

Checkpoint = ModelRegistration | ModelRegistrationResponse


def _approval_path(settings: Settings, model: Checkpoint) -> Path:
    # Keep consent outside portable project storage. Exchange assigns new
    # project and model IDs and cannot import a matching local receipt.
    identity = [
        model.project_id,
        model.id,
        model.provider_name,
        model.task,
        model.purpose,
        model.sha256,
    ]
    key = hashlib.sha256(json.dumps(identity).encode("utf-8")).hexdigest()
    return filesystem_io_path(settings.resolved_data_dir / "checkpoint-approvals" / key)


def remember_checkpoint_approval(settings: Settings, model: Checkpoint) -> None:
    marker = _approval_path(settings, model)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch(exist_ok=True)


def require_local_execution_approval(settings: Settings, model: Checkpoint, path: Path) -> None:
    if not checkpoint_requires_trust(
        path, purpose=model.purpose, provider_name=model.provider_name
    ):
        return
    policy = settings.allow_unsafe_pickled_models
    if policy is False:
        require_checkpoint_trust(policy, approved=False)
    if policy is None and not _approval_path(settings, model).is_file():
        raise ValidationError(
            "Approve this checkpoint's SHA-256 in Model Hub before using its weights on this device"
        )


def verified_registered_checkpoint(
    settings: Settings,
    model: Checkpoint,
    *,
    approving_sha256: str | None = None,
) -> Path:
    path = resolve_managed_project_path(settings, model.managed_path)
    project_root = resolve_managed_project_path(settings, f"projects/{model.project_id}")
    if not path.is_relative_to(project_root):
        raise ValidationError("The registered checkpoint must belong to its project")
    if approving_sha256 is not None and approving_sha256 != model.sha256:
        raise ConflictError("The SHA-256 being approved differs from the registered checkpoint")
    try:
        actual = hash_model_file(path)
    except OSError as exc:
        raise ValidationError("The registered checkpoint is missing or unreadable") from exc
    if actual != (model.sha256, model.file_size_bytes):
        raise ConflictError("The checkpoint bytes differ from the registered checksum or size")
    if approving_sha256 is not None and checkpoint_requires_trust(
        path, purpose=model.purpose, provider_name=model.provider_name
    ):
        require_checkpoint_trust(settings.allow_unsafe_pickled_models, approved=True)
        remember_checkpoint_approval(settings, model)
    else:
        require_local_execution_approval(settings, model, path)
    return path
