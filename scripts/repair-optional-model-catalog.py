"""Repair locally installed optional-model catalogue entries.

The first optional model-pack installer populated checkpoint metadata and the
managed manifest but failed to change the original planned entries from
``availability=unavailable`` to ``availability=available``. This utility safely
repairs only entries whose checkpoint is present and whose size and SHA-256
match the managed manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

CHUNK_SIZE = 1024 * 1024
OPTIONAL_CATALOG_IDS = {
    *(f"ultralytics/yolo11/segment/{size}" for size in ("n", "s", "m", "l", "x")),
    *(f"ultralytics/yolov8/segment/{size}" for size in ("n", "s", "m", "l", "x")),
    "ultralytics/rtdetr/l",
    "ultralytics/rtdetr/x",
    "sam/original/vit_b",
    "sam2/image/base",
    "mobilesam/default",
    "fastsam/default",
    "ultralytics/yolo_world/base",
    "ultralytics/yoloe/base",
}


def default_data_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "org.reefvision.desktop"
    return Path.home() / ".reefvision"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def repair_catalog(data_dir: Path) -> tuple[list[str], list[str]]:
    catalog_path = data_dir / "config" / "model_catalog.json"
    manifest_path = data_dir / "models" / "catalog-models" / "manifest.json"
    if not catalog_path.is_file():
        raise FileNotFoundError(f"Local model catalog was not found: {catalog_path}")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Managed model manifest was not found: {manifest_path}")

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assets = manifest.get("assets", {})
    if not isinstance(assets, dict):
        raise ValueError("Managed model manifest does not contain an assets object")

    repaired: list[str] = []
    skipped: list[str] = []
    entries = {
        str(entry.get("catalog_id")): entry
        for entry in catalog.get("models", [])
        if isinstance(entry, dict)
    }

    for catalog_id in sorted(OPTIONAL_CATALOG_IDS):
        entry = entries.get(catalog_id)
        record = assets.get(catalog_id)
        if not isinstance(entry, dict) or not isinstance(record, dict):
            skipped.append(f"{catalog_id}: catalogue entry or manifest record is missing")
            continue
        filename = str(record.get("filename") or "")
        expected_size = record.get("size_bytes")
        expected_sha = str(record.get("sha256") or "")
        relative_path = str(record.get("relative_path") or "")
        if not filename or not relative_path or not isinstance(expected_size, int) or not expected_sha:
            skipped.append(f"{catalog_id}: manifest record is incomplete")
            continue
        checkpoint = (data_dir / Path(relative_path)).resolve()
        if not checkpoint.is_file():
            skipped.append(f"{catalog_id}: checkpoint is missing")
            continue
        if checkpoint.stat().st_size != expected_size:
            skipped.append(f"{catalog_id}: checkpoint size does not match the manifest")
            continue
        if sha256_file(checkpoint) != expected_sha:
            skipped.append(f"{catalog_id}: checkpoint checksum does not match the manifest")
            continue

        entry.update(
            {
                "availability": "available",
                "selection_kind": "managed_catalog_model",
                "installation_state": "Ready",
                "installation_reason": "Installed and verified by the optional ReefVision model pack.",
                "advanced_only": False,
                "requires_confirmation": False,
            }
        )
        repaired.append(catalog_id)

    catalog["catalog_version"] = "2.1.1-local-model-pack"
    atomic_json(catalog_path, catalog)
    return repaired, skipped


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_dir = args.data_dir.expanduser().resolve()
    try:
        repaired, skipped = repair_catalog(data_dir)
    except Exception as exc:
        print(f"Optional model catalogue repair failed: {exc}", file=sys.stderr)
        return 1

    print(f"Repaired {len(repaired)} optional model catalogue entries.")
    for catalog_id in repaired:
        print(f"  READY {catalog_id}")
    if skipped:
        print(f"Skipped {len(skipped)} entries that were not fully installed:")
        for reason in skipped:
            print(f"  - {reason}")
    print(f"Catalogue: {data_dir / 'config' / 'model_catalog.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
