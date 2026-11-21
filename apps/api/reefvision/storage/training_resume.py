"""Publish and check a paired last/best checkpoint for one interrupted native run."""

import os
import shutil
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID, uuid4

from reefvision.config import Settings
from reefvision.domain.errors import ConflictError
from reefvision.storage.models import hash_model_file
from reefvision.storage.projects import resolve_managed_project_path


def capture_checkpoints(settings: Settings, source: Path, destination: Path) -> dict[str, Any]:
    current = source / "cancelled.pt"
    if not current.is_file():
        current = source / "last.pt"
    if not current.is_file():
        return {}
    destination.mkdir(parents=True, exist_ok=True)
    saved = destination / f"resume-{uuid4()}"
    snapshot: dict[str, Any] = {
        "resume_best_checkpoint_path": None,
        "resume_best_checkpoint_sha256": None,
    }
    with TemporaryDirectory(prefix=".staging-", dir=destination) as tmp:
        incoming = Path(tmp) / "pair"
        incoming.mkdir()
        for field, original in (
            ("resume_checkpoint", current),
            ("resume_best_checkpoint", source / "best.pt"),
        ):
            if field == "resume_best_checkpoint" and not original.is_file():
                continue
            staged = incoming / original.name
            shutil.copy2(original, staged)
            snapshot[field + "_sha256"] = hash_model_file(staged)[0]
            snapshot[field + "_path"] = (
                (saved / original.name).relative_to(settings.resolved_data_dir).as_posix()
            )
        os.replace(incoming, saved)
    return snapshot


def verify_resume_checkpoint(settings: Settings, manifest: dict[str, Any], run_root: str) -> None:
    root = resolve_managed_project_path(settings, run_root)
    for name in ("resume_checkpoint", "resume_best_checkpoint"):
        relative = manifest.get(name + "_path")
        expected = manifest.get(name + "_sha256")
        if name == "resume_best_checkpoint" and relative is None and expected is None:
            continue
        if not isinstance(relative, str) or not isinstance(expected, str) or len(expected) != 64:
            raise ConflictError("This training run has no checksum-pinned recovery checkpoint.")
        candidate = resolve_managed_project_path(settings, relative)
        if candidate.is_relative_to(root):
            with suppress(OSError):
                if hash_model_file(candidate)[0] == expected:
                    continue
        raise ConflictError(
            "The recovery checkpoint is missing or its checksum changed. "
            "The saved run has been preserved."
        )


def retire_previous_pair(settings: Settings, root: Path, previous: object, current: object) -> None:
    """Remove only our superseded transient pair after the next pair is committed."""
    if not isinstance(previous, str) or previous == current:
        return
    folder = resolve_managed_project_path(settings, previous).parent
    if folder.parent != root.resolve() or not folder.name.startswith("resume-"):
        return
    try:
        UUID(folder.name.removeprefix("resume-"))
    except ValueError:
        return
    with suppress(OSError):
        for filename in ("last.pt", "cancelled.pt", "best.pt"):
            (folder / filename).unlink(missing_ok=True)
        folder.rmdir()
