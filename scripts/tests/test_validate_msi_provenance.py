"""Offline MSI/CAB provenance regression tests (no installer execution)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "validate_msi_provenance.py"
SPEC = importlib.util.spec_from_file_location("validate_msi_provenance", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)

VERSION = "1.0.2"
COMMIT = "a" * 40


def make_bundle(tmp_path: Path) -> tuple[Path, dict]:
    directory = tmp_path / "bundle"
    directory.mkdir()
    files = []
    for name in ("ReefVision_1.0.2_x64_en-US.msi", "rv1.cab"):
        payload = name.encode("ascii")
        (directory / name).write_bytes(payload)
        files.append({"name": name, "sha256": hashlib.sha256(payload).hexdigest()})
    manifest = {
        "version": VERSION,
        "source_commit": COMMIT,
        "source_tree_clean": True,
        "msi_verified": True,
        "files": files,
    }
    save(directory, manifest)
    return directory, manifest


def save(directory: Path, manifest: dict) -> None:
    (directory / "build-provenance.json").write_text(json.dumps(manifest))


def verify(directory: Path, **kwargs):
    return validator.validate_bundle(
        directory, expected_version=VERSION, expected_commit=COMMIT, **kwargs
    )


def test_valid_bundle(tmp_path: Path) -> None:
    directory, _ = make_bundle(tmp_path)
    result = verify(directory)
    assert result["installer"] == "ReefVision_1.0.2_x64_en-US.msi"
    assert result["external_cabinets"] == ["rv1.cab"]
    assert result["source_commit"] == COMMIT


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("version", "1.0.3", "version"),
        ("source_commit", "bad", "source commit"),
        ("source_tree_clean", False, "clean-source"),
        ("msi_verified", False, "verification"),
        ("files", [], "must list"),
    ],
)
def test_reject_invalid_manifest(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    directory, manifest = make_bundle(tmp_path)
    manifest[field] = value
    save(directory, manifest)
    with pytest.raises(validator.BundleValidationError, match=message):
        verify(directory)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("rv1.cab", "Missing"),
        ("ReefVision_1.0.2_x64_en-US.msi", "Missing"),
    ],
)
def test_missing_file(tmp_path: Path, name: str, expected: str) -> None:
    directory, _ = make_bundle(tmp_path)
    (directory / name).unlink()
    with pytest.raises(validator.BundleValidationError, match=expected):
        verify(directory)


def test_tampered_cab(tmp_path: Path) -> None:
    directory, _ = make_bundle(tmp_path)
    (directory / "rv1.cab").write_bytes(b"tampered")
    with pytest.raises(validator.BundleValidationError, match="SHA-256 mismatch"):
        verify(directory)


def test_unlisted_msi(tmp_path: Path) -> None:
    directory, _ = make_bundle(tmp_path)
    (directory / "unexpected.msi").write_bytes(b"extra")
    with pytest.raises(validator.BundleValidationError, match="Unexpected"):
        verify(directory)


def test_unlisted_cab(tmp_path: Path) -> None:
    directory, _ = make_bundle(tmp_path)
    (directory / "unexpected.cab").write_bytes(b"extra")
    with pytest.raises(validator.BundleValidationError, match="Unexpected"):
        verify(directory)


def test_duplicate_manifest_key(tmp_path: Path) -> None:
    directory, _ = make_bundle(tmp_path)
    manifest = directory / "build-provenance.json"
    manifest.write_text(manifest.read_text().replace('"version":', '"version": "1.0.2", "version":'))
    with pytest.raises(validator.BundleValidationError, match="Duplicate provenance"):
        verify(directory)


def test_case_colliding_cab(tmp_path: Path) -> None:
    directory, _ = make_bundle(tmp_path)
    (directory / "RV1.CAB").write_bytes(b"extra")
    with pytest.raises(validator.BundleValidationError, match="Unexpected"):
        verify(directory)


def test_linked_cab(tmp_path: Path) -> None:
    directory, _ = make_bundle(tmp_path)
    cab = directory / "rv1.cab"
    target = directory / "target"
    cab.rename(target)
    cab.symlink_to(target)
    with pytest.raises(validator.BundleValidationError, match="linked"):
        verify(directory)


def test_linked_parent_directory(tmp_path: Path) -> None:
    directory, _ = make_bundle(tmp_path)
    linked = tmp_path / "linked"
    linked.symlink_to(directory, target_is_directory=True)
    with pytest.raises(validator.BundleValidationError, match="ancestor"):
        verify(linked)


def test_invalid_expected_commit(tmp_path: Path) -> None:
    directory, _ = make_bundle(tmp_path)
    with pytest.raises(validator.BundleValidationError, match="Expected source commit"):
        validator.validate_bundle(
            directory, expected_version=VERSION, expected_commit="short"
        )


def test_rejection_preserves_user_artifacts(tmp_path: Path) -> None:
    directory, _ = make_bundle(tmp_path)
    cab = directory / "rv1.cab"
    before = cab.read_bytes()
    (directory / "extra.cab").write_bytes(b"extra")
    with pytest.raises(validator.BundleValidationError):
        verify(directory)
    assert cab.read_bytes() == before
