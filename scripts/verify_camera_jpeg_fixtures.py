#!/usr/bin/env python3
"""Read-only JPEG camera-fixture inventory for ReefVision 1.0.3 acceptance.

This validates JPEG signatures and produces an integrity manifest; it does NOT
prove that Pillow, the backend decoder, or installed WebView2 can render files.
No source files are modified. Run against a backed-up, owner-approved fixture set.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

JPEG_SUFFIXES = {".jpg", ".jpeg", ".jpe", ".jfif", ".jfi", ".jif"}
JPEG_SOI = b"\xff\xd8"
JPEG_EOI = b"\xff\xd9"


def inventory(root: Path) -> tuple[list[dict[str, object]], list[str]]:
    records: list[dict[str, object]] = []
    errors: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            errors.append(f"symlink not inspected: {path.relative_to(root)}")
            continue
        if not path.is_file() or path.suffix.lower() not in JPEG_SUFFIXES:
            continue
        relative = path.relative_to(root).as_posix()
        digest = hashlib.sha256()
        first = b""
        tail = b""
        size = 0
        try:
            before = path.stat()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    if not first:
                        first = block[:2]
                    tail = (tail + block)[-2:]
                    size += len(block)
                    digest.update(block)
            after = path.stat()
        except OSError as exc:
            errors.append(f"cannot read JPEG fixture: {relative}: {type(exc).__name__}")
            continue
        if (before.st_size != size or after.st_size != size or
                before.st_mtime_ns != after.st_mtime_ns or
                before.st_ctime_ns != after.st_ctime_ns or
                before.st_ino != after.st_ino or before.st_dev != after.st_dev):
            errors.append(f"JPEG fixture changed during inventory: {relative}")
            continue
        signature_ok = first == JPEG_SOI and tail == JPEG_EOI
        if not signature_ok:
            errors.append(f"invalid JPEG boundary markers: {relative}")
        records.append({
            "path": relative,
            "extension": path.suffix.lower(),
            "bytes": size,
            "sha256": digest.hexdigest(),
            "jpeg_boundary_markers": signature_ok,
        })
    # A read failure is not evidence that the fixture directory is empty.
    # Preserve the actionable read/integrity error without adding a false
    # missing-fixtures diagnosis when matching camera files were encountered.
    if not records and not errors:
        errors.append("no JPEG-family fixtures found")
    return records, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Camera fixture directory (read-only)")
    args = parser.parse_args()
    # Reject a linked root before resolve() can silently follow it outside the
    # owner-approved camera fixture directory.
    if args.directory.is_symlink():
        parser.error("camera fixture directory must not be a symbolic link")
    try:
        root = args.directory.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        parser.error(f"cannot resolve camera fixture directory: {type(exc).__name__}")
    if not root.is_dir():
        parser.error("directory must be a directory")
    records, errors = inventory(root)
    print(json.dumps({"root": str(root), "files": records, "errors": errors},
                     indent=2, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
