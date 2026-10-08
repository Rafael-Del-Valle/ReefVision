"""Release model policy: definitions are weight-free; acquisition is disabled."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.ml import optional_transformers_runtime as optional_runtime
from reefvision.tests.test_annotations import create_project


def test_source_architectures_have_no_weight_acquisition_manifest() -> None:
    source = Path(__file__).resolve().parents[4] / "config/model_catalog.json"
    entries = json.loads(source.read_text(encoding="utf-8"))["models"]
    for entry in entries:
        assert not entry.get("expected_files"), entry["catalog_id"]
        assert not entry.get("expected_checksum"), entry["catalog_id"]
        assert entry["selection_kind"] != "managed_catalog_model"
        assert entry["category"] != "pretrained_catalog"


@pytest.mark.parametrize("task,suffix", [("detect", ""), ("segment", "-seg"), ("pose", "-pose")])
def test_yolo11_architectures_are_available_without_model_files(
    client: TestClient, task: str, suffix: str
) -> None:
    project = create_project(client, "Architecture-only study")
    response = client.get(f"/api/v1/projects/{project['id']}/model-catalog?task={task}")
    assert response.status_code == 200, response.text
    entries = {entry["catalog_id"]: entry for entry in response.json()["models"]}
    for size in "nsmlx":
        entry = entries[f"ultralytics/yolo11/{task}/{size}"]
        assert entry["category"] == "architecture"
        assert entry["selection_kind"] == "builtin_architecture"
        assert entry["architecture_reference"] == f"yolo11{size}{suffix}.yaml"
        assert entry["installation_state"] == "Available"
        assert entry["inference_requires_registered_model"] is True
        assert entry["training_supported"] is True
        assert entry["installed_path"] is None
        assert entry["installed_checksum"] is None


def test_install_request_cannot_queue_weight_download(client: TestClient) -> None:
    project = create_project(client, "No acquisition")
    response = client.post(
        f"/api/v1/projects/{project['id']}/model-installs/ultralytics/yolo11/detect/n",
        json={"confirmed": True},
    )
    assert response.status_code == 400, response.text
    assert "register" in response.text.lower()


def test_optional_download_flag_cannot_acquire_or_remove_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(data_dir=tmp_path)
    target = optional_runtime.optional_model_root(settings, "grounding_dino")
    target.mkdir(parents=True)
    original = target / "researcher-notes.txt"
    original.write_text("preserve", encoding="utf-8")
    monkeypatch.setattr(optional_runtime, "_transformers_version", lambda: "4.57.0")
    monkeypatch.setattr(
        optional_runtime, "optional_model_status", lambda *_: {"ready": False, "reason": None}
    )
    hub = ModuleType("huggingface_hub")

    def reject_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("Model acquisition must never reach Hugging Face")

    monkeypatch.setattr(hub, "snapshot_download", reject_network, raising=False)
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    with pytest.raises(ValidationError, match="register"):
        optional_runtime.ensure_optional_model(settings, "grounding_dino", allow_download=True)
    assert original.read_text(encoding="utf-8") == "preserve"


def test_supported_assist_distinguishes_model_required(client: TestClient) -> None:
    project = create_project(client, "Local models")
    response = client.get(f"/api/v1/projects/{project['id']}/model-catalog")
    assert response.status_code == 200
    entry = next(
        item
        for item in response.json()["models"]
        if item["catalog_id"] == "transformers/grounding_dino/tiny"
    )
    assert entry["availability"] == "available"
    assert entry["selection_kind"] == "model_required"
    assert entry["installation_state"] == "Model Required"
    assert "register" in entry["installation_reason"].lower()
