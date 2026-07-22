"""Tests for offline-only classification architecture resolution."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.orm import Session

import reefvision.ml.classification as classification_module
from reefvision.db.models import TrainingRun
from reefvision.domain.errors import ValidationError
from reefvision.jobs.classification_training import _model_source
from reefvision.ml.classification import resolve_installed_classification_architecture


def _install_fake_architecture(tmp_path: Path, name: str = "yolo11n-cls.yaml") -> Path:
    architecture = tmp_path / "cfg" / "models" / "v11" / name
    architecture.parent.mkdir(parents=True, exist_ok=True)
    architecture.write_text("model: local\n", encoding="utf-8")
    return architecture


def test_classification_architecture_resolves_from_local_package(
    client,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    architecture = _install_fake_architecture(tmp_path)
    monkeypatch.setattr(
        classification_module,
        "files",
        cast(Any, lambda _package: tmp_path / "cfg"),
    )

    resolved = resolve_installed_classification_architecture(
        architecture.name,
        client.app.state.settings,
    )

    assert resolved == architecture.resolve()
    assert os.environ["YOLO_AUTOINSTALL"] == "false"


def test_classification_architecture_rejects_nonlocal_name(
    client,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_fake_architecture(tmp_path)
    monkeypatch.setattr(
        classification_module,
        "files",
        cast(Any, lambda _package: tmp_path / "cfg"),
    )

    with pytest.raises(ValidationError, match="not available in the installed"):
        resolve_installed_classification_architecture(
            "not-installed-cls.yaml",
            client.app.state.settings,
        )


def test_classification_architecture_rejects_paths(
    client,
) -> None:
    with pytest.raises(ValidationError, match="local \*-cls.yaml"):
        resolve_installed_classification_architecture(
            "..\\outside-cls.yaml",
            client.app.state.settings,
        )


def test_training_job_uses_resolved_architecture_path(
    client,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    architecture = _install_fake_architecture(tmp_path, "yolov8n-cls.yaml")
    monkeypatch.setattr(
        classification_module,
        "files",
        cast(Any, lambda _package: tmp_path / "cfg"),
    )
    run = cast(
        TrainingRun,
        type(
            "ScratchRun",
            (),
            {
                "initial_checkpoint_source": "scratch",
                "initial_checkpoint_model_id": None,
                "architecture": architecture.name,
            },
        )(),
    )

    source = _model_source(
        client.app.state.settings,
        cast(Session, object()),
        run,
    )

    assert source == str(architecture.resolve())
