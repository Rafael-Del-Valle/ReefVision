"""Legacy command name for the offline no-pretrained-weights release audit."""

from __future__ import annotations

import argparse
from pathlib import Path

from release_model_policy import audit_catalog, audit_model_root, audit_runtime_root

ROOT = Path(__file__).resolve().parents[1]


def audit(
    catalog_path: Path,
    *,
    bundle_roots: list[Path] | None = None,
    runtime_roots: list[Path] | None = None,
) -> None:
    catalog = audit_catalog(catalog_path)
    for root in bundle_roots or []:
        audit_model_root(root)
    for root in runtime_roots or []:
        audit_runtime_root(root)
    print(
        f"NO-PRETRAINED RELEASE AUDIT PASSED: {len(catalog['models'])} catalog definitions; "
        "no acquisition paths."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT / "config" / "model_catalog.json")
    parser.add_argument("--bundle-root", type=Path, action="append", default=[])
    parser.add_argument("--runtime-root", type=Path, action="append", default=[])
    args = parser.parse_args()
    audit(args.catalog, bundle_roots=args.bundle_root, runtime_roots=args.runtime_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
