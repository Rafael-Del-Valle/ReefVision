#!/usr/bin/env python3
"""Verify clean application-data seeding for the six bundled Transformers models."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from reefvision.config import Settings
from reefvision.services.bundled_transformers_models import (
    bundled_transformers_model_record,
    install_bundled_transformers_models,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--keep-data", action="store_true")
    args = parser.parse_args()

    bundle_root = args.bundle_root.resolve()
    data_dir = args.data_dir.resolve()
    manifest = json.loads((bundle_root / "manifest.json").read_text(encoding="utf-8"))
    expected_ids = sorted(str(item) for item in manifest.get("models", {}))
    if len(expected_ids) != 6:
        raise RuntimeError("Clean startup seeding requires exactly six bundled model records")

    if data_dir.exists():
        shutil.rmtree(data_dir)
    os.environ["REEFVISION_BUNDLED_TRANSFORMERS_MODELS_DIR"] = str(bundle_root)
    settings = Settings(
        env="desktop",
        data_dir=data_dir,
        database_url=f"sqlite:///{(data_dir / 'reefvision.db').as_posix()}",
        background_worker_enabled=False,
        safe_mode=True,
    )
    settings.ensure_directories()
    installed, warnings = install_bundled_transformers_models(settings)
    if warnings:
        raise RuntimeError("; ".join(warnings))
    if sorted(installed) != expected_ids:
        raise RuntimeError(
            f"Clean startup seeded {len(installed)} models instead of {len(expected_ids)}"
        )
    for catalog_id in expected_ids:
        record = bundled_transformers_model_record(settings, catalog_id)
        if record is None or record.get("verified") is not True:
            raise RuntimeError(f"Clean startup did not verify {catalog_id}")
        model_path = Path(record["path"])
        if not (model_path / "config.json").is_file():
            raise RuntimeError(f"Clean startup model is incomplete: {catalog_id}")
    print(
        json.dumps(
            {
                "status": "passed",
                "seeded_model_count": len(installed),
                "data_dir": str(data_dir),
                "catalog_ids": expected_ids,
            },
            indent=2,
        )
    )
    if not args.keep_data:
        shutil.rmtree(data_dir)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Clean Transformers seeding smoke failed: {exc}", file=sys.stderr)
        raise
