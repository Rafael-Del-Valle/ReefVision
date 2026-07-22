"""Install bundled Transformers model snapshots into managed application data."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from reefvision.config import Settings


def _bundle_roots() -> list[Path]:
    candidates: list[Path] = []
    configured = os.environ.get("REEFVISION_BUNDLED_TRANSFORMERS_MODELS_DIR")
    if configured and not configured.isspace():
        candidates.append(Path(configured).expanduser())
    bundle_root = vars(sys).get("_MEIPASS")
    if bundle_root:
        candidates.append(Path(str(bundle_root)).resolve() / "bundled-transformers-models")
    executable = getattr(sys, "executable", None)
    if executable:
        root = Path(executable).resolve().parent
        candidates.extend(
            [
                root / "bundled-transformers-models",
                root / "_internal" / "bundled-transformers-models",
                root.parent / "bundled-transformers-models",
                root.parent.parent / "bundled-transformers-models",
            ]
        )
    candidates.append(
        Path(__file__).resolve().parents[4] / ".desktop" / "bundled-transformers-models"
    )
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(candidate.resolve(strict=False)).casefold()
        if normalized not in seen:
            seen.add(normalized)
            unique.append(candidate)
    return unique


def _load_manifest() -> tuple[Path, dict[str, Any]] | None:
    for root in _bundle_roots():
        path = root / "manifest.json"
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("manifest_version") == 1 and isinstance(payload.get("models"), dict):
            return root, payload
    return None


def install_bundled_transformers_models(
    settings: Settings,
) -> tuple[dict[str, Path], list[str]]:
    loaded = _load_manifest()
    if loaded is None:
        return {}, []
    bundle_root, manifest = loaded
    destination_root = settings.resolved_data_dir / "models" / "provider-packs" / "transformers-vision"
    destination_root.mkdir(parents=True, exist_ok=True)
    installed: dict[str, Path] = {}
    warnings: list[str] = []
    for catalog_id, raw_record in manifest["models"].items():
        if not isinstance(raw_record, dict):
            warnings.append(f"Invalid bundled Transformers record: {catalog_id}")
            continue
        relative_path = str(raw_record.get("relative_path") or "")
        source = (bundle_root / relative_path).resolve()
        try:
            source.relative_to(bundle_root.resolve())
        except ValueError:
            warnings.append(f"Bundled Transformers path escapes resource root: {catalog_id}")
            continue
        if not source.is_dir() or not (source / "config.json").is_file():
            warnings.append(f"Bundled Transformers model is incomplete: {catalog_id}")
            continue
        destination = destination_root.joinpath(*catalog_id.split("/"))
        marker = destination / ".reefvision-revision"
        revision = str(raw_record.get("resolved_revision") or "")
        if not destination.is_dir() or not marker.is_file() or marker.read_text(encoding="utf-8").strip() != revision:
            temporary = destination.with_name(destination.name + ".bundled.part")
            if temporary.exists():
                shutil.rmtree(temporary)
            temporary.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, temporary)
            (temporary / ".reefvision-revision").write_text(revision + "\n", encoding="utf-8")
            if destination.exists():
                shutil.rmtree(destination)
            os.replace(temporary, destination)
        installed[str(catalog_id)] = destination
    index_path = destination_root / "manifest.json"
    index_path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "pack_id": manifest.get("pack_id"),
                "models": {
                    catalog_id: {
                        "path": str(path),
                        "provider_id": manifest["models"][catalog_id].get("provider_id"),
                        "resolved_revision": manifest["models"][catalog_id].get(
                            "resolved_revision"
                        ),
                    }
                    for catalog_id, path in installed.items()
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return installed, warnings


def bundled_transformers_model_path(settings: Settings, catalog_id: str) -> Path | None:
    index = (
        settings.resolved_data_dir
        / "models"
        / "provider-packs"
        / "transformers-vision"
        / "manifest.json"
    )
    if not index.is_file():
        return None
    try:
        payload = json.loads(index.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    record = payload.get("models", {}).get(catalog_id)
    if not isinstance(record, dict):
        return None
    path = Path(str(record.get("path") or "")).resolve()
    return path if path.is_dir() and (path / "config.json").is_file() else None
