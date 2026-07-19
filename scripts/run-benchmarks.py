#!/usr/bin/env python3
"""Generate synthetic fixtures and run ReefVision's provider-free benchmark suite."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from reefvision.benchmarks import synthetic_benchmark_suite, write_benchmark_suite
from reefvision.testing.synthetic_acceptance import generate_synthetic_acceptance_dataset


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=Path(".artifacts/synthetic-acceptance"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".artifacts/benchmarks/provider-free.json"),
    )
    parser.add_argument("--regenerate", action="store_true")
    args = parser.parse_args()
    if args.regenerate or not (args.fixtures / "manifest.json").is_file():
        generate_synthetic_acceptance_dataset(args.fixtures, replace=True)
    suite = synthetic_benchmark_suite(args.fixtures.resolve())
    write_benchmark_suite(args.output, suite)
    print(json.dumps(asdict(suite), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
