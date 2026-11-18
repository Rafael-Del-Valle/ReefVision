from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

import pytest

from reefvision.config import Settings
from reefvision.ml.local_provider_manifests import (
    MAX_LOCAL_PROVIDER_MANIFEST_BYTES,
    discover_local_provider_manifests,
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data")


def _manifest(provider_id: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "manifest_version": 1,
        "provider_id": provider_id,
        "display_name": provider_id.replace("_", " ").title(),
        "provider_version": "1.0.0",
        "description": "An inspect-only local provider declaration.",
        "capabilities": ["image_detection", "cpu_inference"],
        "supported_tasks": ["detect"],
        "availability": {
            "status": "unavailable",
            "reason": "A reviewed ReefVision adapter is not installed.",
        },
        "code_license": "Apache-2.0",
        "weight_license": "User supplied",
        "notes": ["Manifest inspection does not load provider code."],
    }
    payload.update(overrides)
    return payload


def _write_manifest(settings: Settings, name: str, payload: object) -> Path:
    directory = settings.resolved_data_dir / "provider-manifests"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_discovers_valid_manifests_in_deterministic_filename_order(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _write_manifest(settings, "z-last.json", _manifest("zeta_provider"))
    _write_manifest(settings, "a-first.json", _manifest("alpha_provider"))

    records = discover_local_provider_manifests(settings)

    assert [record.source_filename for record in records] == ["a-first.json", "z-last.json"]
    assert [record.record_id for record in records] == ["alpha_provider", "zeta_provider"]
    assert all(record.discovery_status == "valid" for record in records)
    assert all(record.execution_allowed is False for record in records)
    assert records[0].manifest is not None
    assert records[0].manifest.capabilities == ["image_detection", "cpu_inference"]
    assert len(records[0].source_sha256 or "") == 64


@pytest.mark.parametrize(
    ("name", "payload", "expected_error"),
    [
        (
            "unknown-field.json",
            _manifest("unknown_field", entrypoint="bad.module:run"),
            "entrypoint",
        ),
        ("unsupported.json", _manifest("future_provider", manifest_version=2), "manifest_version"),
        ("invalid-id.json", _manifest("Not Valid"), "provider_id"),
        (
            "missing-reason.json",
            _manifest(
                "missing_reason",
                availability={"status": "unavailable", "reason": None},
            ),
            "reason",
        ),
        (
            "unknown-capability.json",
            _manifest("unknown_capability", capabilities=["execute_anything"]),
            "capabilities",
        ),
    ],
)
def test_schema_failures_are_retained_as_blocked_records(
    tmp_path: Path,
    name: str,
    payload: object,
    expected_error: str,
) -> None:
    settings = _settings(tmp_path)
    _write_manifest(settings, name, payload)

    [record] = discover_local_provider_manifests(settings)

    assert record.discovery_status == "invalid"
    assert record.manifest is None
    assert record.execution_allowed is False
    assert any(expected_error in error for error in record.errors)


def test_malformed_and_non_utf8_files_do_not_hide_valid_records(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    directory = settings.resolved_data_dir / "provider-manifests"
    directory.mkdir(parents=True)
    (directory / "a-malformed.json").write_text("{not-json", encoding="utf-8")
    (directory / "b-non-utf8.json").write_bytes(b"\xff\xfe\x00")
    _write_manifest(settings, "c-valid.json", _manifest("valid_provider"))

    records = discover_local_provider_manifests(settings)

    assert [record.discovery_status for record in records] == ["invalid", "invalid", "valid"]
    assert records[2].record_id == "valid_provider"
    assert "JSON" in " ".join(records[0].errors)
    assert "UTF-8" in " ".join(records[1].errors)


def test_duplicate_and_builtin_ids_remain_visible_without_shadowing(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _write_manifest(settings, "a-first.json", _manifest("shared_provider"))
    _write_manifest(settings, "b-duplicate.json", _manifest("shared_provider"))
    _write_manifest(settings, "c-builtin.json", _manifest("ultralytics"))

    records = discover_local_provider_manifests(settings, built_in_ids={"ultralytics"})

    assert records[0].record_id == "shared_provider"
    assert records[0].discovery_status == "valid"
    assert records[1].record_id.startswith("local_manifest_")
    assert records[1].discovery_status == "duplicate"
    assert records[2].record_id.startswith("local_manifest_")
    assert records[2].discovery_status == "built_in_conflict"
    assert all(record.execution_allowed is False for record in records)
    assert len({record.record_id for record in records}) == 3


def test_oversized_file_and_json_named_directory_are_retained_without_reading(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    directory = settings.resolved_data_dir / "provider-manifests"
    directory.mkdir(parents=True)
    oversized = directory / "oversized.json"
    oversized.write_bytes(b"{" + b" " * MAX_LOCAL_PROVIDER_MANIFEST_BYTES + b"}")
    (directory / "folder.json").mkdir()

    records = discover_local_provider_manifests(settings)

    assert [record.source_filename for record in records] == ["folder.json", "oversized.json"]
    assert all(record.discovery_status == "invalid" for record in records)
    assert "regular file" in " ".join(records[0].errors)
    assert "size limit" in " ".join(records[1].errors)
    assert records[1].source_sha256 is None


def test_symlink_is_rejected_without_following_target(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    directory = settings.resolved_data_dir / "provider-manifests"
    directory.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(_manifest("outside_provider")), encoding="utf-8")
    link = directory / "linked.json"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"Symlink creation is unavailable: {exc}")

    [record] = discover_local_provider_manifests(settings)

    assert record.discovery_status == "invalid"
    assert record.manifest is None
    assert "symbolic link" in " ".join(record.errors)


def test_manifest_content_cannot_trigger_imports_or_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    marker = tmp_path / "must-not-exist"
    payload = _manifest(
        "hostile_provider",
        python_module="hostile_provider",
        command=f"echo unsafe > {marker}",
    )
    _write_manifest(settings, "hostile.json", payload)

    def fail_import(name: str, package: str | None = None) -> object:
        raise AssertionError(f"Manifest discovery attempted to import {name!r}")

    monkeypatch.setattr(importlib, "import_module", fail_import)
    [record] = discover_local_provider_manifests(settings)

    assert record.discovery_status == "invalid"
    assert record.execution_allowed is False
    assert not marker.exists()
    assert {"python_module", "command"}.issubset(
        {part for error in record.errors for part in error.split()}
    )


def test_discovery_does_not_create_the_manifest_directory(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    assert discover_local_provider_manifests(settings) == []
    assert not (settings.resolved_data_dir / "provider-manifests").exists()


def test_only_json_entries_in_the_exact_directory_are_considered(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    directory = settings.resolved_data_dir / "provider-manifests"
    nested = directory / "nested"
    nested.mkdir(parents=True)
    (directory / "ignored.txt").write_text("not a manifest", encoding="utf-8")
    (nested / "nested.json").write_text(json.dumps(_manifest("nested_provider")), encoding="utf-8")
    _write_manifest(settings, "visible.json", _manifest("visible_provider"))

    [record] = discover_local_provider_manifests(settings)

    assert record.record_id == "visible_provider"
    assert os.path.basename(record.source_filename) == record.source_filename
