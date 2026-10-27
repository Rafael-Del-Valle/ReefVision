"""Read-only verification of a ReefVision MSI/CAB build-provenance bundle.

Does not install, extract, download, or modify any artifact. Windows Installer
Media-table/ProductVersion verification is separate and remains mandatory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
from pathlib import Path


class BundleValidationError(ValueError):
    """The installer bundle is incomplete, untrusted, or inconsistent."""


def _reject(message: str) -> None:
    raise BundleValidationError(message)


def _is_redirected(path: Path) -> bool:
    """Reject symlinks and Windows junction/reparse paths on Python 3.11+."""
    if path.is_symlink():
        return True
    # Path.is_junction() exists only on Python 3.12+; ReefVision supports 3.11.
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    # Windows lstat exposes FILE_ATTRIBUTE_REPARSE_POINT even for junctions.
    # Missing paths are rejected by the caller's existence checks.
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except FileNotFoundError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_bundle(
    directory: Path,
    *,
    expected_version: str,
    expected_commit: str | None = None,
) -> dict[str, object]:
    """Fail closed on missing, extra, empty, linked, or tampered MSI/CAB files."""
    directory = Path(directory)
    if not directory.is_dir():
        _reject("Installer bundle directory is missing")
    # A normal-looking bundle can still traverse a linked parent directory.
    # Refuse all linked ancestors before opening any provenance or artifact file.
    for ancestor in (directory, *directory.parents):
        if _is_redirected(ancestor):
            _reject("Installer bundle path contains a symlink/junction ancestor")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", expected_version):
        _reject("Expected version must be a three-component numeric version")
    manifest_path = directory / "build-provenance.json"
    if _is_redirected(manifest_path) or not manifest_path.is_file():
        _reject("build-provenance.json is missing or is a symlink")

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                _reject(f"Duplicate provenance JSON key: {key}")
            result[key] = value
        return result

    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8-sig"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except BundleValidationError:
        raise
    except (ValueError, UnicodeError) as exc:
        raise BundleValidationError("build-provenance.json is not valid JSON") from exc
    if not isinstance(manifest, dict):
        _reject("Build provenance must be an object")
    if manifest.get("version") != expected_version:
        _reject("Build provenance version does not match the expected version")
    if manifest.get("source_tree_clean") is not True or manifest.get("msi_verified") is not True:
        _reject("Build provenance lacks clean-source and MSI verification evidence")
    commit = manifest.get("source_commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        _reject("Build provenance source commit is invalid")
    if expected_commit is not None and not re.fullmatch(r"[0-9a-fA-F]{40}", expected_commit):
        _reject("Expected source commit must be a full 40-character SHA")
    if expected_commit is not None and commit.lower() != expected_commit.lower():
        _reject("Build provenance source commit differs from expected HEAD")
    records = manifest.get("files")
    if not isinstance(records, list) or len(records) < 2:
        _reject("Build provenance must list an MSI and at least one external CAB")

    names: set[str] = set()
    msi: list[str] = []
    cabinets: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            _reject("Build provenance contains a non-object file record")
        name, digest = record.get("name"), record.get("sha256")
        if not isinstance(name, str) or not re.fullmatch(
            r"[A-Za-z0-9_-][A-Za-z0-9_.-]*\.(?:msi|cab)", name, re.I
        ):
            _reject("Build provenance contains an unsafe filename")
        if name.casefold() in names:
            _reject("Build provenance contains duplicate filenames")
        names.add(name.casefold())
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            _reject(f"Invalid SHA-256 for {name}")
        path = directory / name
        if _is_redirected(path) or not path.is_file() or path.stat().st_size <= 0:
            _reject(f"Missing, linked, or empty installer artifact: {name}")
        if _sha256(path) != digest.lower():
            _reject(f"SHA-256 mismatch for {name}")
        if name.lower().endswith(".msi"):
            msi.append(name)
        else:
            cabinets.append(name)

    if len(msi) != 1 or not cabinets:
        _reject("Bundle must have exactly one MSI and at least one CAB")
    if not re.fullmatch(
        rf"ReefVision_{re.escape(expected_version)}_[A-Za-z0-9_.-]+\.msi",
        msi[0],
        re.I,
    ):
        _reject("MSI filename does not match expected ReefVision version")
    physical_files = [
        item.name.casefold()
        for item in directory.iterdir()
        if item.suffix.lower() in {".msi", ".cab"}
    ]
    # A set comparison alone hides case-colliding filenames in ZIPs and on
    # case-sensitive filesystems; reject even if the manifest lists one copy.
    if len(physical_files) != len(names) or set(physical_files) != names:
        _reject("Unexpected, duplicated, or unlisted MSI/CAB files in bundle directory")
    return {
        "version": expected_version,
        "source_commit": commit.lower(),
        "installer": msi[0],
        "external_cabinets": sorted(cabinets),
        "artifact_count": len(records),
        "manifest_sha256": _sha256(manifest_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-commit")
    args = parser.parse_args()
    try:
        result = validate_bundle(
            args.directory,
            expected_version=args.expected_version,
            expected_commit=args.expected_commit,
        )
    except BundleValidationError as exc:
        parser.exit(2, f"INVALID MSI BUNDLE: {exc}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
