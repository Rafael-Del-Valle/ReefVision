from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from reefvision.domain.errors import ValidationError
from reefvision.ml import provider_hub
from reefvision.ml.catalog_expansion import (
    ExpandedUltralyticsDetectionProvider,
    UnifiedSegmentAnythingAssistProvider,
    apply_catalog_expansion_runtime_patches,
)
from reefvision.ml.fastsam_runtime_patch import apply_fastsam_runtime_patch


def _load_script(filename: str, module_name: str) -> ModuleType:
    root = Path(__file__).resolve().parents[4]
    path = root / "scripts" / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_runtime_factories_use_expanded_adapters() -> None:
    apply_catalog_expansion_runtime_patches()
    apply_fastsam_runtime_patch()

    assert provider_hub.UltralyticsDetectionProvider is ExpandedUltralyticsDetectionProvider
    assert provider_hub.SegmentAnythingAssistProvider is UnifiedSegmentAnythingAssistProvider


@pytest.mark.parametrize("task", ["detect", "segment", "pose", "classify"])
def test_catalog_checkpoint_inspection_preserves_task_geometry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, task: str
) -> None:
    apply_catalog_expansion_runtime_patches()
    checkpoint = tmp_path / "trained.pt"
    checkpoint.touch()
    model = SimpleNamespace(
        task=task,
        model=SimpleNamespace(yaml={"kpt_shape": [2, 3]} if task == "pose" else {}),
        names={0: "fish"},
        overrides={"imgsz": 96},
    )
    monkeypatch.setattr(
        "reefvision.ml.catalog_expansion._ultralytics_detection_model", lambda _: model
    )
    provider = provider_hub.UltralyticsDetectionProvider()
    if task == "classify":
        with pytest.raises(ValidationError):
            provider.inspect_model(checkpoint)
        return

    inspected = provider.inspect_model(checkpoint)
    assert inspected.task == task
    assert inspected.class_labels == ["fish"] and inspected.input_size == {"imgsz": 96}
    assert inspected.metadata["checkpoint_family"] == "trained"
    assert inspected.metadata["expanded_catalog_runtime"] is True
    assert inspected.metadata["proposal_geometry"] == (
        "keypoints+bbox" if task == "pose" else "bounding_box"
    )
    assert inspected.metadata.get("pose_keypoint_shape") == ([2, 3] if task == "pose" else None)


@pytest.mark.parametrize(
    "filename",
    [
        "install-remaining-models.py",
        "repair-optional-model-catalog.py",
        "migrate-model-catalog-v2.py",
    ],
)
def test_retired_model_utilities_fail_without_mutating_data(
    filename: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = tmp_path / "researcher.pt"
    model.write_bytes(b"keep my model")
    monkeypatch.chdir(tmp_path)
    script = _load_script(filename, "retired_" + filename.replace("-", "_"))
    assert script.main() == 2
    assert model.read_bytes() == b"keep my model"
    assert list(tmp_path.iterdir()) == [model]
