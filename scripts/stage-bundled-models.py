#!/usr/bin/env python3
"""Stage the weight-free release manifest; never acquire or remove model files."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from release_model_policy import MODEL_POLICY, audit_catalog, audit_model_root


def stage_models(
    catalog_path: Path,
    output_root: Path,
    *,
    include_base_assistant: bool = False,
) -> dict[str, Any]:
    if include_base_assistant:
        raise RuntimeError("Bundling pretrained assistant weights is disabled in ReefVision 1.0.")
    payload = audit_catalog(catalog_path)
    # Reject stale assets before writing anything. Never clean a researcher cache.
    if output_root.exists():
        audit_model_root(output_root)
        unexpected = [
            p for p in output_root.rglob("*") if p.is_file() and p.name != "manifest.json"
        ]
        if unexpected:
            raise RuntimeError(
                f"Existing assets require a fresh staging directory: {unexpected[0]}"
            )
    manifest = {
        "manifest_version": 1,
        "model_policy": MODEL_POLICY,
        "catalog_schema_version": payload.get("schema_version"),
        "catalog_version": payload.get("catalog_version"),
        "asset_count": 0,
        "provider_asset_count": 0,
        "total_size_bytes": 0,
        "assets": {},
        "provider_assets": {},
    }
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "manifest.json"
    temporary = output_root / "manifest.json.part"
    with temporary.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(manifest, indent=2) + "\n")
    os.replace(temporary, manifest_path)
    print(f"Staged weight-free model manifest: {manifest_path}")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--include-base-assistant", action="store_true", help="Retired; always fails."
    )
    args = parser.parse_args()
    stage_models(
        args.catalog.resolve(),
        args.output.resolve(),
        include_base_assistant=args.include_base_assistant,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
