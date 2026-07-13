#!/usr/bin/env python3
"""Download and verify every installable catalog checkpoint for desktop packaging."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any

CHUNK_SIZE = 1024 * 1024
MANIFEST_VERSION = 1


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
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    models = payload.get("models")
    if not isinstance(models, list):
        raise RuntimeError("Model catalog does not contain a models list")

    output_root.mkdir(parents=True, exist_ok=True)
    assets: dict[str, dict[str, Any]] = {}
    skipped_unavailable = 0
    total_bytes = 0

    for model in models:
        if not isinstance(model, dict):
            continue
        catalog_id = str(model.get("catalog_id") or "")
        expected_files = model.get("expected_files")
        if model.get("availability") != "available" or not expected_files:
            skipped_unavailable += 1
            continue
        if not isinstance(expected_files, list) or len(expected_files) != 1:
            raise RuntimeError(
                f"Bundled catalog model {catalog_id} must declare exactly one checkpoint file"
            )

        expected = expected_files[0]
        if not isinstance(expected, dict):
            raise RuntimeError(f"Invalid expected file declaration for {catalog_id}")
        filename = str(expected.get("filename") or "")
        if not filename or Path(filename).name != filename:
            raise RuntimeError(
                f"Unsafe checkpoint filename for {catalog_id}: {filename!r}"
            )
        source_url = str(expected.get("source_url") or "")
        expected_sha256 = str(expected.get("sha256") or "").lower()
        expected_size = int(expected.get("size_bytes") or 0)
        if len(expected_sha256) != 64 or expected_size <= 0:
            raise RuntimeError(f"Incomplete pinned checkpoint metadata for {catalog_id}")

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

    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "catalog_schema_version": payload.get("schema_version"),
        "catalog_version": payload.get("catalog_version"),
        "asset_count": len(assets),
        "total_size_bytes": total_bytes,
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

    print(
        f"Bundled {len(assets)} checkpoints "
        f"({total_bytes / (1024 * 1024):.1f} MB); "
        f"{skipped_unavailable} unavailable/planned entries remain catalog-only."
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    stage_models(args.catalog.resolve(), args.output.resolve())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Model bundle staging failed: {exc}", file=sys.stderr)
        raise
