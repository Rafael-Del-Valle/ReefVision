#!/usr/bin/env python3
"""Deterministically partition ReefVision pytest files for CI.

The script prints a space-separated list suitable for command substitution. Files are
sorted by a stable SHA-256 key rather than filesystem order, so adding one test file
redistributes work predictably across the configured shard count.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def shard_paths(root: Path, *, shard_index: int, shard_count: int) -> list[Path]:
    if shard_count < 1:
        raise ValueError("shard_count must be at least 1")
    if shard_index < 0 or shard_index >= shard_count:
        raise ValueError("shard_index must be between 0 and shard_count - 1")
    files = sorted(
        root.glob("test_*.py"),
        key=lambda path: hashlib.sha256(path.as_posix().encode("utf-8")).hexdigest(),
    )
    return [path for index, path in enumerate(files) if index % shard_count == shard_index]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("apps/api/reefvision/tests"))
    parser.add_argument("--index", type=int, required=True)
    parser.add_argument("--count", type=int, required=True)
    args = parser.parse_args()
    selected = shard_paths(args.root, shard_index=args.index, shard_count=args.count)
    if not selected:
        raise SystemExit(
            f"No tests selected for shard {args.index}/{args.count}; reduce the shard count"
        )
    print(" ".join(path.as_posix() for path in selected))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
