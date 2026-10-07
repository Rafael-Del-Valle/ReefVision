"""Validate that every model shown as Available has a real installer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def _optional_provider_ids() -> set[str]:
    from reefvision.ml.optional_transformers_runtime import (
        OPTIONAL_MODEL_SPECS,
    )

    return set(OPTIONAL_MODEL_SPECS)


BASE_BUNDLE_STATUSES = {
    "base_sidecar_provider",
    "base_bundled_checkpoint",
}


def valid_sha(value: object) -> bool:
    text = str(value or "").lower()
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def audit(catalog_path: Path) -> None:
    payload: dict[str, Any] = json.loads(catalog_path.read_text(encoding="utf-8"))

    if payload.get("schema_version") != 2:
        raise RuntimeError("Expected model catalog schema 2.")

    if payload.get("catalog_version") != "2.1.0":
        raise RuntimeError("Expected model catalog version 2.1.0.")

    models = payload.get("models")

    if not isinstance(models, list):
        raise RuntimeError("Catalog models must be a list.")

    failures: list[str] = []
    provider_ids = _optional_provider_ids()
    available_count = 0
    manifest_backed = 0
    provider_backed = 0
    base_bundled = 0
    optional_network = 0

    for entry in models:
        if not isinstance(entry, dict):
            continue

        if entry.get("availability") != "available":
            continue

        available_count += 1
        catalog_id = str(entry.get("catalog_id") or "")
        provider_id = str(entry.get("provider_id") or "")
        expected_files = entry.get("expected_files")
        package_status = str(entry.get("desktop_package_status") or "")

        if entry.get("selection_kind") != "managed_catalog_model":
            failures.append(f"{catalog_id}: available static model is not managed_catalog_model")

        if isinstance(expected_files, list) and expected_files:
            manifest_backed += 1

            for expected in expected_files:
                if not isinstance(expected, dict):
                    failures.append(f"{catalog_id}: malformed expected_files record")
                    continue

                filename = str(expected.get("filename") or "")
                source_url = str(expected.get("source_url") or "")
                size = expected.get("size_bytes")

                if not filename or Path(filename).name != filename:
                    failures.append(f"{catalog_id}: unsafe filename {filename!r}")

                if not source_url.startswith("https://"):
                    failures.append(f"{catalog_id}: non-HTTPS model source")

                if not valid_sha(expected.get("sha256")):
                    failures.append(f"{catalog_id}: invalid SHA-256 for {filename}")

                if not isinstance(size, int) or size <= 0:
                    failures.append(f"{catalog_id}: invalid size for {filename}")

            if package_status in BASE_BUNDLE_STATUSES:
                base_bundled += 1
            elif package_status == "optional_network_download":
                optional_network += 1
            else:
                failures.append(
                    f"{catalog_id}: ambiguous desktop_package_status {package_status!r}"
                )

        elif provider_id in provider_ids:
            provider_backed += 1

        else:
            failures.append(
                f"{catalog_id}: Available but has neither trusted "
                "expected_files nor a pinned provider installer"
            )

    if optional_network != 17:
        failures.append(f"Expected 17 promoted optional downloads; found {optional_network}")

    if base_bundled != 11:
        failures.append(f"Expected 11 base bundled catalog models; found {base_bundled}")

    sam2 = next(
        (
            entry
            for entry in models
            if isinstance(entry, dict) and entry.get("catalog_id") == "sam2/image/base"
        ),
        None,
    )

    if not isinstance(sam2, dict):
        failures.append("sam2/image/base is missing")
    elif sam2.get("provider_id") != "sam2":
        failures.append("sam2/image/base lost its canonical pinned provider route")

    if failures:
        print("MODEL DOWNLOADABILITY AUDIT FAILED", file=sys.stderr)

        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)

        raise SystemExit(1)

    print("MODEL DOWNLOADABILITY AUDIT PASSED")
    print(f"  Available catalog models: {available_count}")
    print(f"  Manifest-backed:         {manifest_backed}")
    print(f"  Provider-backed:         {provider_backed}")
    print(f"  Base bundled:            {base_bundled}")
    print(f"  Optional downloads:      {optional_network}")
    print("  Invalid Available paths: 0")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=ROOT / "config" / "model_catalog.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    audit(args.catalog.expanduser().resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
