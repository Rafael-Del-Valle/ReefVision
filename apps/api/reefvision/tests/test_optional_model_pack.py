from __future__ import annotations

import importlib.util
import json
import sys
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
from reefvision.schemas.model_catalog import ModelCatalogResponse


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


def test_optional_pack_preserves_shipped_downloadable_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer = _load_script("install-remaining-models.py", "reefvision_optional_model_pack")
    repair = _load_script("repair-optional-model-catalog.py", "reefvision_optional_model_repair")
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
    catalog_path = tmp_path / "config" / "model_catalog.json"
    before = json.loads(catalog_path.read_text())
    before_entry = next(item for item in before["models"] if item["catalog_id"] == model.catalog_id)
    assert before_entry["availability"] == "available"

    repaired, skipped = repair.repair_catalog(tmp_path)

    assert model.catalog_id in repaired
    assert all(not reason.startswith(f"{model.catalog_id}:") for reason in skipped)
    catalog = json.loads(catalog_path.read_text())
    validated = ModelCatalogResponse.model_validate(
        {
            **catalog,
            "application_version": "test",
            "validation_warnings": [],
            "rejected_entries": 0,
        }
    )
    assert len(validated.models) >= 43
    entry = next(item for item in catalog["models"] if item["catalog_id"] == model.catalog_id)
    assert entry["availability"] == "available"
    assert entry["selection_kind"] == "managed_catalog_model"
    assert entry["installation_state"] == "Ready"
    assert entry["expected_files"][0]["filename"] == model.filename
    assert entry["expected_files"][0]["size_bytes"] == len(payload)

    manifest = json.loads((tmp_path / "models" / "catalog-models" / "manifest.json").read_text())
    record = manifest["assets"][model.catalog_id]
    assert record["filename"] == model.filename
    assert record["size_bytes"] == len(payload)
    assert (tmp_path / record["relative_path"]).read_bytes() == payload


def test_desktop_stager_skips_optional_network_downloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib

    stager = _load_script(
        "stage-bundled-models.py",
        "reefvision_optional_bundle_policy",
    )

    base_payload = b"base"
    optional_payload = b"optional"

    def entry(
        catalog_id: str,
        filename: str,
        payload: bytes,
        package_status: str,
    ) -> dict[str, object]:
        return {
            "catalog_id": catalog_id,
            "availability": "available",
            "desktop_package_status": package_status,
            "provider_version": "test",
            "expected_files": [
                {
                    "filename": filename,
                    "source_url": f"https://example.invalid/{filename}",
                    "revision": "test",
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size_bytes": len(payload),
                }
            ],
        }

    catalog = {
        "schema_version": 2,
        "catalog_version": "test",
        "models": [
            entry(
                "base/test",
                "base.pt",
                base_payload,
                "base_bundled_checkpoint",
            ),
            entry(
                "optional/test",
                "optional.pt",
                optional_payload,
                "optional_network_download",
            ),
        ],
    }

    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(catalog),
        encoding="utf-8",
    )

    def fake_download(
        url: str,
        destination: Path,
        expected_size: int,
        expected_sha256: str,
    ) -> None:
        payload = base_payload if destination.name == "base.pt" else optional_payload
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)

    monkeypatch.setattr(
        stager,
        "_download",
        fake_download,
    )

    output = tmp_path / "bundle"

    manifest = stager.stage_models(
        catalog_path,
        output,
        include_base_assistant=False,
    )

    assert manifest["asset_count"] == 1
    assert set(manifest["assets"]) == {"base/test"}
    assert not (output / "optional" / "test" / "optional.pt").exists()
