"""Tests for checkpoints shipped inside the ReefVision desktop installer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.schemas.model_catalog import (
    CatalogExpectedFile,
    ModelCatalogEntryResponse,
    ModelCatalogResponse,
)
from reefvision.services import bundled_models
from reefvision.services.model_catalog import ModelCatalogService, _load_static_model_catalog
from reefvision.storage.catalog_models import catalog_asset_path, catalog_manifest_record


def _bundle_catalog(
    monkeypatch: pytest.MonkeyPatch, payload: bytes
) -> tuple[str, ModelCatalogEntryResponse]:
    original_catalog = _load_static_model_catalog()
    original = next(
        entry
        for entry in original_catalog.models
        if entry.catalog_id == "ultralytics/yolo11/detect/n"
    )
    checksum = hashlib.sha256(payload).hexdigest()
    expected = CatalogExpectedFile(
        filename="yolo11n.pt",
        source_url=("https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt"),
        revision="test-bundle",
        sha256=checksum,
        size_bytes=len(payload),
    )
    entry = original.model_copy(
        update={
            "expected_files": [expected],
            "expected_size": len(payload),
            "expected_checksum": checksum,
            "expected_file_size": len(payload),
        }
    )
    catalog = ModelCatalogResponse(
        schema_version=2,
        catalog_version="test-bundle",
        models=[entry],
    )
    monkeypatch.setattr(bundled_models, "_load_static_model_catalog", lambda: catalog)
    return checksum, entry


def _write_bundle(
    bundle_root: Path,
    entry: ModelCatalogEntryResponse,
    payload: bytes,
    checksum: str,
) -> None:
    expected = entry.expected_files[0]
    relative_path = f"{entry.catalog_id}/{expected.filename}"
    checkpoint = bundle_root / relative_path
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_bytes(payload)
    (bundle_root / "manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "catalog_version": "test-bundle",
                "asset_count": 1,
                "total_size_bytes": len(payload),
                "assets": {
                    entry.catalog_id: {
                        "catalog_id": entry.catalog_id,
                        "filename": expected.filename,
                        "relative_path": relative_path,
                        "sha256": checksum,
                        "size_bytes": len(payload),
                        "provider_version": entry.provider_version,
                        "revision": "test-bundle",
                    }
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_bundled_checkpoint_is_seeded_and_ready(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = b"installer-bundled-checkpoint"
    checksum, entry = _bundle_catalog(monkeypatch, payload)
    bundle_root = tmp_path / "bundle"
    _write_bundle(bundle_root, entry, payload, checksum)
    monkeypatch.setenv("REEFVISION_BUNDLED_MODELS_DIR", str(bundle_root))

    installed, warnings = bundled_models.install_bundled_catalog_models(
        cast(FastAPI, client.app).state.settings
    )

    assert warnings == []
    assert installed == [entry.catalog_id]
    destination = catalog_asset_path(
        cast(FastAPI, client.app).state.settings,
        entry.catalog_id,
        entry.expected_files[0].filename,
    )
    assert destination.read_bytes() == payload
    record = catalog_manifest_record(cast(FastAPI, client.app).state.settings, entry.catalog_id)
    assert record is not None
    assert record["sha256"] == checksum
    assert record["source"] == "bundled_installer"

    with cast(FastAPI, client.app).state.session_factory() as session:
        state = ModelCatalogService(
            session, cast(FastAPI, client.app).state.settings
        )._compose_static_state(
            entry,
            job=None,
            manifest={"manifest_version": 1, "assets": {entry.catalog_id: record}},
        )
    assert state.installation_state == "Ready"
    assert state.installed_checksum == checksum


def test_corrupt_bundled_checkpoint_is_rejected(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    expected_payload = b"expected-checkpoint"
    checksum, entry = _bundle_catalog(monkeypatch, expected_payload)
    bundle_root = tmp_path / "corrupt-bundle"
    _write_bundle(bundle_root, entry, b"short", checksum)
    monkeypatch.setenv("REEFVISION_BUNDLED_MODELS_DIR", str(bundle_root))

    installed, warnings = bundled_models.install_bundled_catalog_models(
        cast(FastAPI, client.app).state.settings
    )

    assert installed == []
    assert any("metadata does not match" in warning for warning in warnings)
    destination = catalog_asset_path(
        cast(FastAPI, client.app).state.settings,
        entry.catalog_id,
        entry.expected_files[0].filename,
    )
    assert not destination.exists()


def test_multifile_bundled_model_is_seeded(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    original_catalog = _load_static_model_catalog()
    original = next(
        entry
        for entry in original_catalog.models
        if entry.catalog_id == "transformers/depth_anything_v2/small"
    )
    payloads = {
        "config.json": b'{"model_type":"depth_anything"}',
        "preprocessor_config.json": b'{"do_resize":true}',
        "model.safetensors": b"tiny-depth-weights",
    }
    expected_files = [
        CatalogExpectedFile(
            filename=filename,
            source_url=(
                "https://huggingface.co/depth-anything/"
                "Depth-Anything-V2-Small-hf/resolve/"
                f"{original.expected_files[0].revision}/{filename}"
            ),
            revision=original.expected_files[0].revision,
            sha256=hashlib.sha256(payload).hexdigest(),
            size_bytes=len(payload),
        )
        for filename, payload in payloads.items()
    ]
    entry = original.model_copy(
        update={
            "availability": "available",
            "expected_files": expected_files,
            "expected_size": sum(len(payload) for payload in payloads.values()),
            "expected_checksum": None,
            "expected_file_size": None,
        }
    )
    catalog = ModelCatalogResponse(
        schema_version=2,
        catalog_version="test-bundle",
        models=[entry],
    )
    monkeypatch.setattr(bundled_models, "_load_static_model_catalog", lambda: catalog)

    bundle_root = tmp_path / "bundle-multifile"
    file_records = []
    total_size = 0
    for expected in entry.expected_files:
        payload = payloads[expected.filename]
        relative_path = f"{entry.catalog_id}/{expected.filename}"
        checkpoint = bundle_root / relative_path
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_bytes(payload)
        file_records.append(
            {
                "filename": expected.filename,
                "relative_path": relative_path,
                "sha256": expected.sha256,
                "size_bytes": expected.size_bytes,
                "revision": expected.revision,
            }
        )
        total_size += expected.size_bytes
    (bundle_root / "manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "catalog_version": "test-bundle",
                "asset_count": 1,
                "total_size_bytes": total_size,
                "assets": {
                    entry.catalog_id: {
                        "catalog_id": entry.catalog_id,
                        "filename": entry.expected_files[0].filename,
                        "relative_path": entry.catalog_id,
                        "sha256": None,
                        "size_bytes": total_size,
                        "files": file_records,
                        "provider_version": entry.provider_version,
                        "revision": entry.expected_files[0].revision,
                    }
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("REEFVISION_BUNDLED_MODELS_DIR", str(bundle_root))

    installed, warnings = bundled_models.install_bundled_catalog_models(
        cast(FastAPI, client.app).state.settings
    )

    assert warnings == []
    assert installed == [entry.catalog_id]
    for expected in entry.expected_files:
        destination = catalog_asset_path(
            cast(FastAPI, client.app).state.settings, entry.catalog_id, expected.filename
        )
        assert destination.read_bytes() == payloads[expected.filename]
    record = catalog_manifest_record(cast(FastAPI, client.app).state.settings, entry.catalog_id)
    assert record is not None
    assert record["sha256"] is None
    assert len(record["files"]) == 3
