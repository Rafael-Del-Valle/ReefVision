#!/usr/bin/env python3
"""Download and verify every installable catalog checkpoint for desktop packaging."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.request
from contextlib import suppress
from pathlib import Path
from typing import Any

CHUNK_SIZE = 1024 * 1024
MANIFEST_VERSION = 1

DESKTOP_BUNDLED_PACKAGE_STATUSES = {
    "base_sidecar_provider",
    "base_bundled_checkpoint",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _is_verified(path: Path, expected_size: int, expected_sha256: str) -> bool:
    return (
        path.is_file() and path.stat().st_size == expected_size and _sha256(path) == expected_sha256
    )


def _safe_segments(value: str) -> list[str]:
    segments = value.split("/")
    if not segments or any(
        not segment or segment in {".", ".."} or Path(segment).name != segment
        for segment in segments
    ):
        raise RuntimeError(f"Unsafe catalog id: {value!r}")
    return segments


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
        headers={"User-Agent": "ReefVision-desktop-model-bundler/1"},
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
                f"Size mismatch for {destination.name}: expected {expected_size}, got {downloaded}"
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


def stage_models(
    catalog_path: Path,
    output_root: Path,
    *,
    include_base_assistant: bool = False,
) -> dict[str, Any]:
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    models = payload.get("models")
    if not isinstance(models, list):
        raise RuntimeError("Model catalog does not contain a models list")

    output_root.mkdir(parents=True, exist_ok=True)
    assets: dict[str, dict[str, Any]] = {}
    skipped_catalog_only = 0
    total_bytes = 0

    for model in models:
        if not isinstance(model, dict):
            continue
        catalog_id = str(model.get("catalog_id") or "")
        expected_files = model.get("expected_files")
        package_status = str(model.get("desktop_package_status") or "")
        if (
            model.get("availability") != "available"
            or not expected_files
            or package_status not in DESKTOP_BUNDLED_PACKAGE_STATUSES
        ):
            skipped_catalog_only += 1
            continue
        if not isinstance(expected_files, list):
            raise RuntimeError(
                f"Bundled catalog model {catalog_id} has an invalid expected_files declaration"
            )

        file_records: list[dict[str, Any]] = []
        seen_filenames: set[str] = set()
        model_total_bytes = 0

        for expected in expected_files:
            if not isinstance(expected, dict):
                raise RuntimeError(f"Invalid expected file declaration for {catalog_id}")
            filename = str(expected.get("filename") or "")
            if not filename or Path(filename).name != filename:
                raise RuntimeError(f"Unsafe checkpoint filename for {catalog_id}: {filename!r}")
            if filename in seen_filenames:
                raise RuntimeError(
                    f"Bundled catalog model {catalog_id} declares duplicate file {filename!r}"
                )
            seen_filenames.add(filename)

            source_url = str(expected.get("source_url") or "")
            expected_sha256 = str(expected.get("sha256") or "").lower()
            expected_size = int(expected.get("size_bytes") or 0)
            if len(expected_sha256) != 64 or expected_size <= 0:
                raise RuntimeError(
                    f"Incomplete pinned checkpoint metadata for {catalog_id}/{filename}"
                )

            destination = output_root.joinpath(*_safe_segments(catalog_id), filename)
            print(f"Bundling {catalog_id} ({filename})")
            if _is_verified(destination, expected_size, expected_sha256):
                print("  verified cached checkpoint")
            else:
                destination.unlink(missing_ok=True)
                _download(source_url, destination, expected_size, expected_sha256)

            relative_path = destination.relative_to(output_root).as_posix()
            file_records.append(
                {
                    "filename": filename,
                    "relative_path": relative_path,
                    "sha256": expected_sha256,
                    "size_bytes": expected_size,
                    "source_url": source_url,
                    "revision": expected.get("revision"),
                }
            )
            model_total_bytes += expected_size
            total_bytes += expected_size

        if not file_records:
            raise RuntimeError(f"Bundled catalog model {catalog_id} declares no checkpoint files")

        first = file_records[0]
        model_root = output_root.joinpath(*_safe_segments(catalog_id))
        assets[catalog_id] = {
            "catalog_id": catalog_id,
            "filename": first["filename"],
            "relative_path": (
                first["relative_path"]
                if len(file_records) == 1
                else model_root.relative_to(output_root).as_posix()
            ),
            "sha256": first["sha256"] if len(file_records) == 1 else None,
            "size_bytes": model_total_bytes,
            "files": file_records,
            "provider_version": model.get("provider_version"),
            "revision": first.get("revision"),
        }

    provider_assets: dict[str, dict[str, Any]] = {}

    if include_base_assistant:
        api_root = Path(__file__).resolve().parents[1] / "apps" / "api"

        if str(api_root) not in sys.path:
            sys.path.insert(
                0,
                str(api_root),
            )

        from reefvision.config import Settings
        from reefvision.ml.optional_transformers_runtime import (
            OPTIONAL_MODEL_SPECS,
            ensure_optional_model,
        )

        spec = OPTIONAL_MODEL_SPECS["smolvlm"]

        print(f"Bundling base Research Assistant model: {spec.display_name}")

        # Keep packaging independent of Windows symlink privileges.
        # ensure_optional_model() downloads directly into ReefVision's
        # managed provider directory and performs pinned provenance and
        # checksum verification before returning the usable directory.
        provider_cache_root = Path(__file__).resolve().parents[1] / ".reefvision"

        provider_settings = Settings(
            data_dir=provider_cache_root,
        )

        snapshot = ensure_optional_model(
            provider_settings,
            spec.provider_id,
            allow_download=True,
        )

        provider_root = output_root / "provider-models" / spec.provider_id

        if provider_root.exists():
            shutil.rmtree(provider_root)

        provider_root.mkdir(parents=True, exist_ok=True)

        provider_files: list[dict[str, Any]] = []

        for pattern in spec.allow_patterns:
            source = snapshot / pattern
            if not source.is_file():
                continue

            destination = provider_root / source.name
            shutil.copy2(source, destination)

            digest = _sha256(destination)
            size = destination.stat().st_size

            provider_files.append(
                {
                    "filename": destination.name,
                    "relative_path": destination.relative_to(output_root).as_posix(),
                    "sha256": digest,
                    "size_bytes": size,
                }
            )

            total_bytes += size

        weight = provider_root / spec.weight_filename

        if not weight.is_file():
            raise RuntimeError(f"Base SmolVLM bundle is missing {spec.weight_filename}")

        actual_weight_sha = _sha256(weight)

        if spec.weight_sha256 is not None and actual_weight_sha != spec.weight_sha256:
            raise RuntimeError("Base SmolVLM weight failed pinned checksum verification")

        provider_assets[spec.provider_id] = {
            "provider_id": spec.provider_id,
            "display_name": spec.display_name,
            "repo_id": spec.repo_id,
            "revision": spec.revision,
            "weight_filename": spec.weight_filename,
            "weight_sha256": spec.weight_sha256,
            "license_summary": spec.license_summary,
            "files": provider_files,
        }

    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "catalog_schema_version": payload.get("schema_version"),
        "catalog_version": payload.get("catalog_version"),
        "asset_count": len(assets),
        "provider_asset_count": len(provider_assets),
        "total_size_bytes": total_bytes,
        "assets": assets,
        "provider_assets": provider_assets,
    }
    manifest_path = output_root / "manifest.json"
    temporary_manifest = manifest_path.with_suffix(".json.part")
    temporary_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary_manifest, manifest_path)

    declared_paths: set[Path] = {manifest_path}
    for record in assets.values():
        files = record.get("files")
        if isinstance(files, list):
            for file_record in files:
                if isinstance(file_record, dict):
                    relative_path = str(file_record.get("relative_path") or "")
                    if relative_path:
                        declared_paths.add(output_root / relative_path)

    for provider_record in provider_assets.values():
        files = provider_record.get("files")

        if not isinstance(files, list):
            continue

        for file_record in files:
            if not isinstance(file_record, dict):
                continue

            relative_path = str(file_record.get("relative_path") or "")

            if relative_path:
                declared_paths.add(output_root / relative_path)

    for candidate in output_root.rglob("*"):
        if candidate.is_file() and candidate not in declared_paths:
            candidate.unlink()
    for directory in sorted(
        (path for path in output_root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        with suppress(OSError):
            directory.rmdir()

    print(
        f"Bundled {len(assets)} catalog models "
        f"({total_bytes / (1024 * 1024):.1f} MB); "
        f"{skipped_catalog_only} entries remain outside the base installer bundle."
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--include-base-assistant",
        action="store_true",
        help="Bundle pinned SmolVLM for the offline Research Assistant.",
    )
    args = parser.parse_args()
    stage_models(
        args.catalog.resolve(),
        args.output.resolve(),
        include_base_assistant=args.include_base_assistant,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Model bundle staging failed: {exc}", file=sys.stderr)
        raise
