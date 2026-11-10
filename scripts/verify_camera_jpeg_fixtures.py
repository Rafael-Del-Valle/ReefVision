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
    # Case-sensitive hosts can hold distinct camera names that collapse to one
    # path on default Windows filesystems. Flag this before acceptance/export.
    seen_casefolded_paths: dict[str, str] = {}
    seen_casefolded_components: dict[tuple[str, ...], str] = {}
    for path in sorted(root.rglob("*")):
        # Filter unrelated files before metadata checks; a JPEG-named symlink
        # remains explicitly rejected rather than followed.
        if path.suffix.lower() not in JPEG_SUFFIXES:
            continue
        if path.is_symlink():
            errors.append(f"symlink not inspected: {path.relative_to(root)}")
            continue
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        # Windows reserves device basenames in *every* path component, not
        # just the final JPEG name (e.g. CON/photos/valid.jpg is also invalid).
        # Match the basename before any extension, as Win32 does.
        components = path.relative_to(root).parts
        reserved = {
            "CON", "PRN", "AUX", "NUL",
            *(f"COM{number}" for number in range(1, 10)),
            *(f"LPT{number}" for number in range(1, 10)),
        }
        for index, component in enumerate(components):
            if component.rstrip(" .").split(".")[0].upper() in reserved:
                if index == len(components) - 1:
                    errors.append(f"Windows reserved device filename: {relative}")
                else:
                    errors.append(f"Windows reserved device directory: {relative}")
                break
        # Win32 rejects these characters in every path component, even when
        # a Linux camera export can store them. Flag without renaming originals.
        forbidden = set('<>:"\\\\|?*')
        if any(any(character in forbidden or ord(character) < 32
                   for character in component) for component in components):
            errors.append(f"Windows invalid path character: {relative}")
        # Detect case-only directory aliases too: Camera/a.jpg and camera/b.jpg
        # are different Linux trees but collapse into one Windows directory.
        # Win32 normalizes trailing dots/spaces in path components; such
        # exported names cannot be reliably addressed by the installed app.
        for component in components:
            if component.endswith((".", " ")):
                errors.append(f"Windows trailing dot/space path component: {relative}")
                break
        for depth in range(1, len(components)):
            key = tuple(part.casefold() for part in components[:depth])
            actual = "/".join(components[:depth])
            prior = seen_casefolded_components.setdefault(key, actual)
            if prior != actual:
                error = f"Windows case-insensitive directory collision: {prior} / {actual}"
                if error not in errors:
                    errors.append(error)
        folded = relative.casefold()
        previous = seen_casefolded_paths.setdefault(folded, relative)
        if previous != relative:
            errors.append(f"Windows case-insensitive filename collision: {previous} / {relative}")
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
    # Reject symlinks in any supplied path component, not only the final
    # directory: linked-parent/fixtures would otherwise escape the approved root.
    candidate = args.directory.absolute()
    if any(component.is_symlink() for component in (candidate, *candidate.parents)):
        parser.error("camera fixture directory must not be a symbolic link (including parent components)")
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
