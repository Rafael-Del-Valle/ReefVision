#!/usr/bin/env python3
"""Generate ReefVision's deterministic acceptance-data bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from reefvision.testing.synthetic_acceptance import (
    generate_synthetic_acceptance_dataset,
    manifest_as_dict,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".artifacts/synthetic-acceptance"),
    )
    parser.add_argument("--keep-existing", action="store_true")
    args = parser.parse_args()
    manifest = generate_synthetic_acceptance_dataset(
        args.output,
        replace=not args.keep_existing,
    )
    print(json.dumps(manifest_as_dict(manifest), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
