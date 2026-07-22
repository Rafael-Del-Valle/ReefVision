#!/usr/bin/env python3
"""Download and stage the six official Transformers vision model repositories."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected a JSON object in {path}")
    return payload


def _safe_catalog_segments(catalog_id: str) -> list[str]:
    segments = catalog_id.split("/")
    if not segments or any(
        not segment
        or segment in {".", ".."}
        or Path(segment).name != segment
        for segment in segments
    ):
        raise RuntimeError(f"Unsafe catalog id: {catalog_id!r}")
    return segments


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_files(root: Path) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        files.append(
            {
                "relative_path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    if not files:
        raise RuntimeError(f"Model snapshot is empty: {root}")
    return files


def stage_model_pack(policy_path: Path, output_root: Path) -> dict[str, Any]:
    try:
        from huggingface_hub import model_info, snapshot_download
    except Exception as exc:
        raise RuntimeError(
            "huggingface-hub is required to stage the Transformers provider pack"
        ) from exc

    policy = _load_object(policy_path)
    raw_models = policy.get("models")
    if not isinstance(raw_models, list) or len(raw_models) != 6:
        raise RuntimeError("Transformers model pack must declare exactly six models")
    output_root.mkdir(parents=True, exist_ok=True)
    records: dict[str, Any] = {}
    declared_roots: set[Path] = set()

    for raw_model in raw_models:
        if not isinstance(raw_model, dict):
            raise RuntimeError("Transformers model pack contains a non-object entry")
        catalog_id = str(raw_model.get("catalog_id") or "").strip()
        repo_id = str(raw_model.get("repo_id") or "").strip()
        revision = str(raw_model.get("revision") or "").strip()
        provider_id = str(raw_model.get("provider_id") or "").strip()
        if not catalog_id or not repo_id or not revision or not provider_id:
            raise RuntimeError("Transformers model pack entry is incomplete")
        destination = output_root.joinpath(*_safe_catalog_segments(catalog_id))
        declared_roots.add(destination.resolve())
        info = model_info(repo_id, revision=revision)
        resolved_revision = str(info.sha or revision)
        print(f"Staging {catalog_id} from {repo_id}@{resolved_revision}")
        temporary = destination.with_name(destination.name + ".part")
        if temporary.exists():
            shutil.rmtree(temporary)
        temporary.mkdir(parents=True)
        snapshot_path = Path(
            snapshot_download(
                repo_id=repo_id,
                revision=resolved_revision,
                local_dir=temporary,
                local_dir_use_symlinks=False,
                ignore_patterns=("*.md", ".gitattributes"),
            )
        )
        if not (snapshot_path / "config.json").is_file():
            shutil.rmtree(temporary, ignore_errors=True)
            raise RuntimeError(f"Snapshot {repo_id} does not contain config.json")
        if destination.exists():
            shutil.rmtree(destination)
        os.replace(temporary, destination)
        files = _snapshot_files(destination)
        records[catalog_id] = {
            "catalog_id": catalog_id,
            "repo_id": repo_id,
            "requested_revision": revision,
            "resolved_revision": resolved_revision,
            "provider_id": provider_id,
            "relative_path": destination.relative_to(output_root).as_posix(),
            "file_count": len(files),
            "total_size_bytes": sum(item["size_bytes"] for item in files),
            "files": files,
        }

    manifest = {
        "manifest_version": 1,
        "pack_id": str(policy.get("pack_id") or "transformers-vision"),
        "model_count": len(records),
        "models": records,
        "total_size_bytes": sum(item["total_size_bytes"] for item in records.values()),
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    for child in output_root.iterdir():
        if child == manifest_path:
            continue
        if child.resolve() in declared_roots:
            continue
        # Top-level catalog roots are shared, so cleanup is intentionally conservative.
    print(
        f"Staged {manifest['model_count']} Transformers models "
        f"({manifest['total_size_bytes'] / (1024**3):.2f} GiB)."
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    stage_model_pack(args.policy.resolve(), args.output.resolve())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Transformers model-pack staging failed: {exc}")
        raise
