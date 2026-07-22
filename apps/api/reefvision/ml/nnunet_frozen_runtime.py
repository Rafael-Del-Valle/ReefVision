"""Route nnU-Net CLI subprocesses through the packaged ReefVision executable."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_SUPPORTED_COMMANDS = {
    "nnUNetv2_plan_and_preprocess",
    "nnUNetv2_train",
    "nnUNetv2_predict",
}
_ENTRYPOINT_SUFFIX = ".reefvision-entrypoint"
_APPLIED = False


def _is_frozen() -> bool:
    return bool(vars(sys).get("frozen", False))


def apply_nnunet_frozen_runtime_patch() -> None:
    """Make existing nnU-Net subprocess calls work inside a PyInstaller bundle."""

    global _APPLIED
    if _APPLIED or not _is_frozen():
        return

    from reefvision.ml import semantic_segmentation

    original_command_path = semantic_segmentation._command_path
    original_run_command = semantic_segmentation._run_command

    def command_path(name: str) -> Path | None:
        existing = original_command_path(name)
        if existing is not None:
            return existing
        if name not in _SUPPORTED_COMMANDS:
            return None
        return Path(sys.executable).resolve().with_name(f"{name}{_ENTRYPOINT_SUFFIX}")

    def run_command(
        command: list[str],
        *,
        env: dict[str, str],
        log_path: Path | None,
        cwd: Path,
    ) -> None:
        if command:
            executable = Path(command[0])
            if executable.name.endswith(_ENTRYPOINT_SUFFIX):
                name = executable.name.removesuffix(_ENTRYPOINT_SUFFIX)
                if name not in _SUPPORTED_COMMANDS:
                    raise RuntimeError(f"Unsupported packaged nnU-Net command: {name}")
                command = [
                    str(Path(sys.executable).resolve()),
                    "--nnunet-entrypoint",
                    name,
                    *command[1:],
                ]
        original_run_command(
            command,
            env=env,
            log_path=log_path,
            cwd=cwd,
        )

    semantic_segmentation._command_path = command_path
    semantic_segmentation._run_command = run_command
    _APPLIED = True
