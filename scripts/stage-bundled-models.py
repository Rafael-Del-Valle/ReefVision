#!/usr/bin/env python3
"""Download, audit, and verify every zero-input desktop model asset."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CHUNK_SIZE = 1024 * 1024
MANIFEST_VERSION = 1
ALLOWED_SELECTION_KINDS = {
    "builtin_architecture",
    "managed_catalog_model",
    "planned_unavailable",
}


@dataclass(frozen=True)
class DeliveryAudit:
    managed_catalog_ids: tuple[str, ...]
    builtin_architecture_ids: tuple[str, ...]
    experimental_ids: tuple[str, ...]
    unavailable_ids: tuple[str, ...]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.errors


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _is_verified(path: Path, expected_size: int, expected_sha256: str) -> bool:
    return (
        path.is_file()
        and path.stat().st_size == expected_size
        and _sha256(path) == expected_sha256
    )


def _safe_segments(value: str) -> list[str]:
    segments = value.split("/")
    if not segments or any(
        not segment or segment in {".", ".."} or Path(segment).name != segment
        for segment in segments
    ):
        raise RuntimeError(f"Unsafe catalog id: {value!r}")
    return segments


def _expected_file(model: dict[str, Any], catalog_id: str) -> dict[str, Any]:
    expected_files = model.get("expected_files")
    if not isinstance(expected_files, list) or len(expected_files) != 1:
        raise RuntimeError(
            f"Managed catalog model {catalog_id} must declare exactly one checkpoint file"
        )
    expected = expected_files[0]
    if not isinstance(expected, dict):
        raise RuntimeError(f"Invalid expected-file declaration for {catalog_id}")
    filename = str(expected.get("filename") or "")
    if not filename or Path(filename).name != filename:
        raise RuntimeError(f"Unsafe checkpoint filename for {catalog_id}: {filename!r}")
    source_url = str(expected.get("source_url") or "")
    expected_sha256 = str(expected.get("sha256") or "").lower()
    expected_size = int(expected.get("size_bytes") or 0)
    if not source_url.startswith("https://"):
        raise RuntimeError(f"Only HTTPS checkpoint sources are allowed: {catalog_id}")
    if len(expected_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in expected_sha256
    ):
        raise RuntimeError(f"Incomplete pinned checkpoint checksum for {catalog_id}")
    if expected_size <= 0:
        raise RuntimeError(f"Incomplete pinned checkpoint size for {catalog_id}")
    if int(model.get("expected_size") or 0) != expected_size:
        raise RuntimeError(f"Catalog expected_size does not match expected_files for {catalog_id}")
    if str(model.get("expected_checksum") or "").lower() != expected_sha256:
        raise RuntimeError(
            f"Catalog expected_checksum does not match expected_files for {catalog_id}"
        )
    if int(model.get("expected_file_size") or 0) != expected_size:
        raise RuntimeError(
            f"Catalog expected_file_size does not match expected_files for {catalog_id}"
        )
    return expected


def audit_catalog(payload: dict[str, Any]) -> DeliveryAudit:
    models = payload.get("models")
    if not isinstance(models, list):
        raise RuntimeError("Model catalog does not contain a models list")

    managed: list[str] = []
    builtins: list[str] = []
    experimental: list[str] = []
    unavailable: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()

    for index, raw_model in enumerate(models):
        if not isinstance(raw_model, dict):
            errors.append(f"Catalog entry {index} is not an object")
            continue
        model = dict(raw_model)
        catalog_id = str(model.get("catalog_id") or "").strip()
        if not catalog_id:
            errors.append(f"Catalog entry {index} has no catalog_id")
            continue
        if catalog_id in seen:
            errors.append(f"Duplicate catalog_id: {catalog_id}")
            continue
        seen.add(catalog_id)

        availability = str(model.get("availability") or "").strip()
        selection_kind = str(model.get("selection_kind") or "").strip()
        if selection_kind not in ALLOWED_SELECTION_KINDS:
            errors.append(
                f"Static catalog entry {catalog_id} has unsupported selection_kind "
                f"{selection_kind!r}"
            )
            continue

        if availability == "experimental":
            experimental.append(catalog_id)
            warnings.append(
                f"Experimental entry {catalog_id} is catalog-only and is not bundled automatically"
            )
            continue
        if availability == "unavailable":
            unavailable.append(catalog_id)
            if selection_kind != "planned_unavailable":
                warnings.append(
                    f"Unavailable entry {catalog_id} is not marked planned_unavailable"
                )
            continue
        if availability != "available":
            errors.append(
                f"Catalog entry {catalog_id} has unsupported availability {availability!r}"
            )
            continue

        if selection_kind == "builtin_architecture":
            architecture = str(model.get("architecture_reference") or "").strip()
            if not architecture:
                errors.append(
                    f"Available builtin architecture {catalog_id} has no architecture_reference"
                )
            if model.get("expected_files"):
                errors.append(
                    f"Builtin architecture {catalog_id} must not declare downloadable checkpoints"
                )
            builtins.append(catalog_id)
            continue

        if selection_kind == "managed_catalog_model":
            try:
                _expected_file(model, catalog_id)
            except RuntimeError as exc:
                errors.append(str(exc))
            managed.append(catalog_id)
            continue

        errors.append(
            f"Available catalog entry {catalog_id} cannot use selection_kind {selection_kind!r}"
        )

    return DeliveryAudit(
        managed_catalog_ids=tuple(sorted(managed)),
        builtin_architecture_ids=tuple(sorted(builtins)),
        experimental_ids=tuple(sorted(experimental)),
        unavailable_ids=tuple(sorted(unavailable)),
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def require_complete_delivery_contract(payload: dict[str, Any]) -> DeliveryAudit:
    audit = audit_catalog(payload)
    if audit.errors:
        details = "\n".join(f"  - {message}" for message in audit.errors)
        raise RuntimeError(f"Model delivery contract failed:\n{details}")
    return audit


def _download(
    url: str,
    destination: Path,
    expected_size: int,
    expected_sha256: str,
) -> None:
    if not url.startswith("https://"):
        raise RuntimeError(f"Only HTTPS checkpoint sources are allowed: {url}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ReefVision-desktop-model-bundler/2"},
    )
    digest = hashlib.sha256()
    downloaded = 0
    try:
        with (
            urllib.request.urlopen(request, timeout=120) as response,
            temporary.open("wb") as output,
        ):
            while chunk := response.read(CHUNK_SIZE):
                output.write(chunk)
                digest.update(chunk)
                downloaded += len(chunk)
                print(
                    f"  {destination.name}: {downloaded / (1024 * 1024):.1f} / "
                    f"{expected_size / (1024 * 1024):.1f} MB",
                    end="\r",
                    flush=True,
                )
            output.flush()
            os.fsync(output.fileno())
        print()
        if downloaded != expected_size:
            raise RuntimeError(
                f"Size mismatch for {destination.name}: expected {expected_size}, "
                f"got {downloaded}"
            )
        actual_sha256 = digest.hexdigest()
        if actual_sha256 != expected_sha256:
            raise RuntimeError(
                f"Checksum mismatch for {destination.name}: expected {expected_sha256}, "
                f"got {actual_sha256}"
            )
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def stage_models(catalog_path: Path, output_root: Path) -> dict[str, Any]:
    catalog_bytes = catalog_path.read_bytes()
    payload = json.loads(catalog_bytes.decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Model catalog root must be an object")
    audit = require_complete_delivery_contract(payload)
    models = payload["models"]

    output_root.mkdir(parents=True, exist_ok=True)
    assets: dict[str, dict[str, Any]] = {}
    total_bytes = 0
    managed_ids = set(audit.managed_catalog_ids)

    for raw_model in models:
        if not isinstance(raw_model, dict):
            continue
        model = dict(raw_model)
        catalog_id = str(model.get("catalog_id") or "")
        if catalog_id not in managed_ids:
            continue
        expected = _expected_file(model, catalog_id)
        filename = str(expected["filename"])
        source_url = str(expected["source_url"])
        expected_sha256 = str(expected["sha256"]).lower()
        expected_size = int(expected["size_bytes"])

        destination = output_root.joinpath(*_safe_segments(catalog_id), filename)
        print(f"Bundling {catalog_id} ({filename})")
        if _is_verified(destination, expected_size, expected_sha256):
            print("  verified cached checkpoint")
        else:
            destination.unlink(missing_ok=True)
            _download(source_url, destination, expected_size, expected_sha256)

        relative_path = destination.relative_to(output_root).as_posix()
        assets[catalog_id] = {
            "catalog_id": catalog_id,
            "filename": filename,
            "relative_path": relative_path,
            "sha256": expected_sha256,
            "size_bytes": expected_size,
            "provider_version": model.get("provider_version"),
            "revision": expected.get("revision"),
        }
        total_bytes += expected_size

    missing_assets = sorted(managed_ids.difference(assets))
    if missing_assets:
        raise RuntimeError(
            "Bundle staging omitted managed catalog models: " + ", ".join(missing_assets)
        )

    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "delivery_contract_complete": True,
        "catalog_schema_version": payload.get("schema_version"),
        "catalog_version": payload.get("catalog_version"),
        "catalog_sha256": hashlib.sha256(catalog_bytes).hexdigest(),
        "asset_count": len(assets),
        "managed_catalog_model_count": len(audit.managed_catalog_ids),
        "builtin_architecture_count": len(audit.builtin_architecture_ids),
        "experimental_entry_count": len(audit.experimental_ids),
        "unavailable_entry_count": len(audit.unavailable_ids),
        "total_size_bytes": total_bytes,
        "builtin_architectures": list(audit.builtin_architecture_ids),
        "experimental_entries": list(audit.experimental_ids),
        "assets": assets,
    }
    manifest_path = output_root / "manifest.json"
    temporary_manifest = manifest_path.with_suffix(".json.part")
    temporary_manifest.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_manifest, manifest_path)

    declared_paths = {
        output_root / record["relative_path"] for record in assets.values()
    }
    declared_paths.add(manifest_path)
    for candidate in output_root.rglob("*"):
        if candidate.is_file() and candidate not in declared_paths:
            candidate.unlink()
    for directory in sorted(
        (path for path in output_root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        try:
            directory.rmdir()
        except OSError:
            pass

    for warning in audit.warnings:
        print(f"Warning: {warning}", file=sys.stderr)
    print(
        f"Bundled {len(assets)} checkpoints "
        f"({total_bytes / (1024 * 1024):.1f} MB); "
        f"{len(audit.builtin_architecture_ids)} scratch architectures require no download; "
        f"{len(audit.experimental_ids)} experimental and "
        f"{len(audit.unavailable_ids)} unavailable entries remain catalog-only."
    )
    return manifest


def audit_only(catalog_path: Path) -> DeliveryAudit:
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Model catalog root must be an object")
    audit = require_complete_delivery_contract(payload)
    print(
        "Model delivery contract passed: "
        f"{len(audit.managed_catalog_ids)} bundled checkpoints, "
        f"{len(audit.builtin_architecture_ids)} offline scratch architectures, "
        f"{len(audit.experimental_ids)} experimental entries, and "
        f"{len(audit.unavailable_ids)} unavailable entries."
    )
    for warning in audit.warnings:
        print(f"Warning: {warning}", file=sys.stderr)
    return audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()

    catalog = args.catalog.resolve()
    if args.audit_only:
        audit_only(catalog)
        return 0
    if args.output is None:
        parser.error("--output is required unless --audit-only is used")
    stage_models(catalog, args.output.resolve())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Model bundle staging failed: {exc}", file=sys.stderr)
        raise
