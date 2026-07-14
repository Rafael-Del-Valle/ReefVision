from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from reefvision.ml import provider_hub
from reefvision.ml.catalog_expansion import (
    ExpandedUltralyticsDetectionProvider,
    UnifiedSegmentAnythingAssistProvider,
    apply_catalog_expansion_runtime_patches,
)
from reefvision.ml.fastsam_runtime_patch import apply_fastsam_runtime_patch


def _load_installer_module() -> ModuleType:
    root = Path(__file__).resolve().parents[4]
    path = root / "scripts" / "install-remaining-models.py"
    spec = importlib.util.spec_from_file_location("reefvision_optional_model_pack", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_factories_use_expanded_adapters() -> None:
    apply_catalog_expansion_runtime_patches()
    apply_fastsam_runtime_patch()

    assert provider_hub.UltralyticsDetectionProvider is ExpandedUltralyticsDetectionProvider
    assert provider_hub.SegmentAnythingAssistProvider is UnifiedSegmentAnythingAssistProvider


def test_optional_pack_writes_catalog_override_and_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer = _load_installer_module()
    source_catalog = Path(__file__).resolve().parents[4] / "config" / "model_catalog.json"
    model = installer.OPTIONAL_MODELS[0]
    payload = b"reefvision-test-checkpoint"

    def fake_download(optional_model: object, destination: Path) -> str:
        assert optional_model == model
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        return f"{installer.RELEASE_ROOT}/v8.3.0/{model.filename}"

    monkeypatch.setattr(installer, "download_official_asset", fake_download)

    installed, failed = installer.install_model_pack(
        data_dir=tmp_path,
        source_catalog=source_catalog,
        only={model.catalog_id},
    )

    assert installed == [model.catalog_id]
    assert failed == []
    catalog = json.loads((tmp_path / "config" / "model_catalog.json").read_text())
    entry = next(item for item in catalog["models"] if item["catalog_id"] == model.catalog_id)
    assert entry["availability"] == "available"
    assert entry["selection_kind"] == "managed_catalog_model"
    assert entry["expected_files"][0]["filename"] == model.filename
    assert entry["expected_files"][0]["size_bytes"] == len(payload)

    manifest = json.loads(
        (tmp_path / "models" / "catalog-models" / "manifest.json").read_text()
    )
    record = manifest["assets"][model.catalog_id]
    assert record["filename"] == model.filename
    assert record["size_bytes"] == len(payload)
    assert (tmp_path / record["relative_path"]).read_bytes() == payload
