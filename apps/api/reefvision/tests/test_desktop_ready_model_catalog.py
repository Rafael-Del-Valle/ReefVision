"""Tests for the desktop installer model-bundle policy."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def _load_hydrator() -> ModuleType:
    script = (
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "hydrate-desktop-model-catalog.py"
    )
    spec = importlib.util.spec_from_file_location(
        "reefvision_hydrate_desktop_model_catalog",
        script,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _catalog_entry(
    *,
    display_name: str = "Example Model",
    availability: str = "unavailable",
) -> dict[str, Any]:
    return {
        "catalog_id": "example/model",
        "display_name": display_name,
        "provider": "planned",
        "provider_id": "planned",
        "provider_version": "planned",
        "checkpoint_identifier": "example.yaml",
        "checkpoint_source": "planned_catalog_entry",
        "expected_checksum": None,
        "expected_file_size": None,
        "download_source_type": "planned_catalog_entry",
        "expected_files": [],
        "expected_size": None,
        "model_weight_license": "Not pinned",
        "license_summary": "Not pinned",
        "required_provider_pack": "planned",
        "provider_pack_id": "planned",
        "desktop_package_status": "not_verified",
        "clean_machine_verification_status": "not_verified",
        "deprecation_status": "experimental",
        "known_limitations": ["Packaged-desktop validation remains unavailable."],
        "installation_state": "Unavailable",
        "installation_reason": "Not installed",
        "selection_kind": (
            "managed_catalog_model"
            if availability == "available"
            else "planned_unavailable"
        ),
        "requires_confirmation": True,
        "availability": availability,
    }


def _policy(target: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "policy_version": "test",
        "repository": "ultralytics/assets",
        "release_tags": ["v-test"],
        "license_summary": "Official test weights",
        "model_weight_license": "Official test weights",
        "required_models": [
            target
            or {
                "display_name": "Example Model",
                "filename": "example.pt",
            }
        ],
    }


def _release(
    *,
    filename: str = "example.pt",
    payload: bytes = b"checkpoint",
    digest: str | None = None,
) -> dict[str, Any]:
    checksum = digest or hashlib.sha256(payload).hexdigest()
    return {
        "assets": [
            {
                "name": filename,
                "browser_download_url": (
                    "https://github.com/ultralytics/assets/releases/download/"
                    f"v-test/{filename}"
                ),
                "digest": f"sha256:{checksum}",
                "size": len(payload),
            }
        ]
    }


def test_desktop_policy_contains_all_ready_models() -> None:
    policy_path = (
        Path(__file__).resolve().parents[4]
        / "config"
        / "desktop_ready_models.json"
    )
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    targets = policy["required_models"]

    assert len(targets) == 28
    assert len({item["display_name"] for item in targets}) == 28
    assert len({item["filename"] for item in targets}) == 28
    assert {"FastSAM", "MobileSAM", "SAM ViT-B", "SAM 2 Image"}.issubset(
        {item["display_name"] for item in targets}
    )
    sam_target = next(item for item in targets if item["display_name"] == "SAM ViT-B")
    assert sam_target["catalog_id"] == "sam/original/vit_b"


def test_actual_catalog_contains_every_desktop_policy_target() -> None:
    root = Path(__file__).resolve().parents[4]
    policy = json.loads(
        (root / "config" / "desktop_ready_models.json").read_text(encoding="utf-8")
    )
    catalog = json.loads(
        (root / "config" / "model_catalog.json").read_text(encoding="utf-8")
    )
    catalog_names = {item["display_name"] for item in catalog["models"]}
    catalog_ids = {item["catalog_id"] for item in catalog["models"]}

    for item in policy["required_models"]:
        if item.get("catalog_id"):
            assert item["catalog_id"] in catalog_ids
        else:
            assert item["display_name"] in catalog_names


def test_hydration_promotes_verified_release_asset() -> None:
    module = _load_hydrator()
    entry = _catalog_entry()
    policy = _policy(
        {
            "display_name": "Example Model",
            "filename": "example.pt",
            "provider": "segment_anything",
            "provider_id": "segment_anything",
            "provider_version": "1.0+reefvision-pack",
            "provider_pack_id": None,
            "required_provider_pack": None,
        }
    )

    hydrated = module.hydrate_catalog(
        {"models": [entry]},
        policy,
        release_loader=lambda _repository, _tag: _release(),
    )
    result = hydrated["models"][0]
    expected = result["expected_files"][0]

    assert hydrated["desktop_bundle_required_ids"] == ["example/model"]
    assert result["availability"] == "available"
    assert result["selection_kind"] == "managed_catalog_model"
    assert result["installation_state"] == "Not Installed"
    assert result["requires_confirmation"] is False
    assert result["provider_id"] == "segment_anything"
    assert result["provider_pack_id"] is None
    assert expected["filename"] == "example.pt"
    assert result["expected_checksum"] == expected["sha256"]
    assert result["expected_file_size"] == expected["size_bytes"]
    assert result["expected_size"] == expected["size_bytes"]


def test_complete_existing_asset_does_not_require_release_lookup() -> None:
    module = _load_hydrator()
    payload = b"existing"
    checksum = hashlib.sha256(payload).hexdigest()
    entry = _catalog_entry(availability="available")
    entry.update(
        {
            "expected_checksum": checksum,
            "expected_file_size": len(payload),
            "expected_size": len(payload),
            "expected_files": [
                {
                    "filename": "example.pt",
                    "source_url": (
                        "https://github.com/ultralytics/assets/releases/download/"
                        "v8.3.0/example.pt"
                    ),
                    "revision": "ultralytics-assets-v8.3.0",
                    "sha256": checksum,
                    "size_bytes": len(payload),
                }
            ],
        }
    )

    def unexpected_lookup(_repository: str, _tag: str) -> dict[str, Any]:
        raise AssertionError("release lookup should not run")

    hydrated = module.hydrate_catalog(
        {"models": [entry]},
        _policy(),
        release_loader=unexpected_lookup,
    )

    assert hydrated["desktop_bundle_required_ids"] == ["example/model"]


def test_hydration_rejects_release_without_sha256_digest() -> None:
    module = _load_hydrator()
    release = _release()
    release["assets"][0]["digest"] = None

    with pytest.raises(RuntimeError, match="does not expose a SHA-256"):
        module.hydrate_catalog(
            {"models": [_catalog_entry()]},
            _policy(),
            release_loader=lambda _repository, _tag: release,
        )
