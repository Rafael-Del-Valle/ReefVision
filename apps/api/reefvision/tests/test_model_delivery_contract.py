"""Tests for zero-input catalog delivery and desktop bundle completeness."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def _load_bundle_module() -> ModuleType:
    script = Path(__file__).resolve().parents[4] / "scripts" / "stage-bundled-models.py"
    spec = importlib.util.spec_from_file_location("reefvision_stage_bundled_models", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _managed_entry(payload: bytes) -> dict[str, Any]:
    checksum = hashlib.sha256(payload).hexdigest()
    return {
        "catalog_id": "example/provider/detect/n",
        "availability": "available",
        "selection_kind": "managed_catalog_model",
        "provider_version": "1.0.0",
        "expected_checksum": checksum,
        "expected_file_size": len(payload),
        "expected_size": len(payload),
        "expected_files": [
            {
                "filename": "example.pt",
                "source_url": "https://example.invalid/example.pt",
                "revision": "test",
                "sha256": checksum,
                "size_bytes": len(payload),
            }
        ],
    }


def _builtin_entry() -> dict[str, Any]:
    return {
        "catalog_id": "example/provider/detect/scratch-n",
        "availability": "available",
        "selection_kind": "builtin_architecture",
        "architecture_reference": "example.yaml",
        "expected_files": [],
    }


def _unavailable_entry() -> dict[str, Any]:
    return {
        "catalog_id": "example/provider/future",
        "availability": "unavailable",
        "selection_kind": "planned_unavailable",
        "expected_files": [],
    }


def test_current_catalog_has_complete_zero_input_delivery_contract() -> None:
    module = _load_bundle_module()
    catalog = Path(__file__).resolve().parents[4] / "config" / "model_catalog.json"
    payload = json.loads(catalog.read_text(encoding="utf-8"))

    audit = module.require_complete_delivery_contract(payload)

    assert audit.complete is True
    assert audit.managed_catalog_ids
    assert set(audit.managed_catalog_ids).isdisjoint(audit.builtin_architecture_ids)


def test_stage_models_records_all_delivery_modes(tmp_path: Path) -> None:
    module = _load_bundle_module()
    checkpoint_payload = b"verified-checkpoint"
    managed = _managed_entry(checkpoint_payload)
    payload = {
        "schema_version": 2,
        "catalog_version": "test",
        "models": [managed, _builtin_entry(), _unavailable_entry()],
    }
    catalog = tmp_path / "model_catalog.json"
    catalog.write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "bundle"
    expected = output / "example" / "provider" / "detect" / "n" / "example.pt"
    expected.parent.mkdir(parents=True, exist_ok=True)
    expected.write_bytes(checkpoint_payload)

    manifest = module.stage_models(catalog, output)

    assert manifest["delivery_contract_complete"] is True
    assert manifest["asset_count"] == manifest["managed_catalog_model_count"] == 1
    assert manifest["builtin_architecture_count"] == 1
    assert manifest["unavailable_entry_count"] == 1
    assert manifest["builtin_architectures"] == ["example/provider/detect/scratch-n"]
    assert manifest["catalog_sha256"] == hashlib.sha256(catalog.read_bytes()).hexdigest()


def test_available_managed_model_requires_complete_pinned_metadata() -> None:
    module = _load_bundle_module()
    model = _managed_entry(b"checkpoint")
    model["expected_files"] = []
    payload = {"models": [model]}

    with pytest.raises(RuntimeError, match="exactly one checkpoint file"):
        module.require_complete_delivery_contract(payload)


def test_builtin_architecture_cannot_hide_a_download() -> None:
    module = _load_bundle_module()
    model = _builtin_entry()
    model["expected_files"] = [
        {
            "filename": "unexpected.pt",
            "source_url": "https://example.invalid/unexpected.pt",
            "revision": "test",
            "sha256": "0" * 64,
            "size_bytes": 1,
        }
    ]
    payload = {"models": [model]}

    with pytest.raises(RuntimeError, match="must not declare downloadable checkpoints"):
        module.require_complete_delivery_contract(payload)
