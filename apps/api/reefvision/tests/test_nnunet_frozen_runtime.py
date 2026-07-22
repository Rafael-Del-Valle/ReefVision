"""Tests for packaged nnU-Net command dispatch."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from reefvision.ml import nnunet_frozen_runtime, semantic_segmentation


def test_frozen_nnunet_commands_route_through_sidecar(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: list[tuple[list[str], dict[str, str], Path | None, Path]] = []

    monkeypatch.setitem(vars(sys), "frozen", True)
    monkeypatch.setattr(
        nnunet_frozen_runtime,
        "_APPLIED",
        False,
    )
    monkeypatch.setattr(
        semantic_segmentation,
        "_command_path",
        lambda _name: None,
    )

    def capture(
        command: list[str],
        *,
        env: dict[str, str],
        log_path: Path | None,
        cwd: Path,
    ) -> None:
        captured.append((command, env, log_path, cwd))

    monkeypatch.setattr(semantic_segmentation, "_run_command", capture)

    nnunet_frozen_runtime.apply_nnunet_frozen_runtime_patch()
    command_path = semantic_segmentation._command_path("nnUNetv2_train")

    assert command_path is not None
    assert command_path.name == "nnUNetv2_train.reefvision-entrypoint"

    semantic_segmentation._run_command(
        [str(command_path), "500", "2d", "0"],
        env={"nnUNet_results": str(tmp_path / "results")},
        log_path=tmp_path / "training.log",
        cwd=tmp_path,
    )

    assert len(captured) == 1
    command, environment, log_path, cwd = captured[0]
    assert command[:3] == [
        str(Path(sys.executable).resolve()),
        "--nnunet-entrypoint",
        "nnUNetv2_train",
    ]
    assert command[3:] == ["500", "2d", "0"]
    assert environment["nnUNet_results"].endswith("results")
    assert log_path == tmp_path / "training.log"
    assert cwd == tmp_path
