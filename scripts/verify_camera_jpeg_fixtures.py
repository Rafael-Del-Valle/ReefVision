#!/usr/bin/env python3
"""Read-only JPEG camera-fixture inventory for ReefVision 1.0.3 acceptance.

By default this validates JPEG signatures and produces an integrity manifest.
--verify-decode additionally asks Pillow to load every JPEG pixel stream, so
syntactically marked but undecodable images fail acceptance. Neither mode
proves installed WebView2 or GPU behavior. No originals are modified.
Run against a backed-up, owner-approved fixture set.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import warnings
from pathlib import Path

JPEG_SUFFIXES = {".jpg", ".jpeg", ".jpe", ".jfif", ".jfi", ".jif"}
JPEG_SOI = b"\xff\xd8"
JPEG_EOI = b"\xff\xd9"


def inventory(root: Path, *, verify_decode: bool = False) -> tuple[list[dict[str, object]], list[str]]:
    # This function is also imported directly by tests and acceptance tools.
    # Enforce the same root boundary as the CLI before rglob can follow a
    # linked root or parent into an unapproved camera directory.
    candidate = root.absolute()
    if any(component.is_symlink() for component in (candidate, *candidate.parents)):
        return [], ["camera fixture directory must not be a symbolic link (including parent components)"]
    if not root.is_dir():
        return [], ["camera fixture directory is not a directory"]
    records: list[dict[str, object]] = []
    errors: list[str] = []
    # Case-sensitive hosts can hold distinct camera names that collapse to one
    # path on default Windows filesystems. Flag this before acceptance/export.
    seen_casefolded_paths: dict[str, str] = {}
    seen_casefolded_components: dict[tuple[str, ...], str] = {}
    seen_file_identities: dict[tuple[int, int], str] = {}
    # os.walk separates directories from files without statting unrelated
    # scientific files. Never follow directory links outside the approved root.
    jpeg_paths: list[Path] = []

    def report_walk_error(error: OSError) -> None:
        # os.walk otherwise silently skips unreadable camera subdirectories,
        # producing a deceptively complete scientific acceptance manifest.
        # Do not retry, follow links, or modify the source directory.
        location = getattr(error, "filename", None) or str(root)
        errors.append(f"camera directory traversal failed: {location}: {type(error).__name__}")

    for directory, dirnames, filenames in os.walk(root, followlinks=False, onerror=report_walk_error):
        parent = Path(directory)
        for dirname in sorted(dirnames):
            child = parent / dirname
            if child.is_symlink():
                errors.append(f"symlinked directory not inspected: {child.relative_to(root)}")
        dirnames[:] = sorted(name for name in dirnames if not (parent / name).is_symlink())
        jpeg_paths.extend(parent / name for name in filenames
                          if Path(name).suffix.lower() in JPEG_SUFFIXES)
    for path in sorted(jpeg_paths):
        # JPEG-named symlinks remain explicitly rejected, not followed.
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
            # Win32 also reserves superscript 1/2/3 as COM/LPT port digits.
            *(f"{prefix}{digit}" for prefix in ("COM", "LPT") for digit in "¹²³"),
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
        # Two directory entries may be hard links to one underlying capture.
        # Keep both manifest records, but flag duplicate scientific inputs so
        # downstream acceptance cannot mistake aliases for independent images.
        # Some filesystems report inode zero (unknown); never infer an alias
        # from an unavailable file identity.
        if after.st_ino:
            identity = (after.st_dev, after.st_ino)
            previous_identity = seen_file_identities.setdefault(identity, relative)
            if previous_identity != relative:
                errors.append(f"JPEG hard-link alias (same source image): {previous_identity} / {relative}")
        signature_ok = first == JPEG_SOI and tail == JPEG_EOI
        if not signature_ok:
            errors.append(f"invalid JPEG boundary markers: {relative}")
        # Valid boundary markers do not prove that the complete JPEG pixel
        # stream can be decoded. Decoding remains opt-in for large panoramas.
        decoded_ok = False
        decoded_metadata: dict[str, object] = {}
        if verify_decode and signature_ok:
            try:
                from PIL import Image

                # Pillow raises only a warning for images exceeding its
                # configured pixel budget (until twice that limit). Treat
                # the warning as failed acceptance, without altering the
                # application's or any other thread's decoder settings.
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(path) as decoded:
                        if decoded.format != "JPEG":
                            raise ValueError("decoded format is not JPEG")
                        decoded.load()
                        # Raster dimensions are deliberately not EXIF-transposed:
                        # recording the orientation separately lets scientific
                        # reviewers compare native and displayed geometry.
                        decoded_metadata = {
                            "jpeg_pixel_width": decoded.width,
                            "jpeg_pixel_height": decoded.height,
                            "jpeg_color_mode": decoded.mode,
                            "jpeg_exif_orientation": decoded.getexif().get(274),
                        }
                # A modified camera fixture cannot be accepted against the
                # SHA-256 generated by the prior immutable manifest pass.
                decoded_stat = path.stat()
                if (
                    decoded_stat.st_size != after.st_size
                    or decoded_stat.st_mtime_ns != after.st_mtime_ns
                    or decoded_stat.st_ctime_ns != after.st_ctime_ns
                    or decoded_stat.st_ino != after.st_ino
                    or decoded_stat.st_dev != after.st_dev
                ):
                    errors.append(f"JPEG fixture changed during decoding: {relative}")
                else:
                    decoded_ok = True
            except ImportError:
                errors.append(f"Pillow JPEG decoder unavailable: {relative}")
            except (
                OSError,
                ValueError,
                Image.DecompressionBombError,
                Image.DecompressionBombWarning,
            ) as exc:
                # Both Pillow's hard pixel limit and its earlier warning
                # indicate that a camera image exceeded the decode budget.
                # Neither may silently pass this scientific acceptance check.
                errors.append(f"JPEG decode failed: {relative}: {type(exc).__name__}")
        record: dict[str, object] = {
            "path": relative,
            "extension": path.suffix.lower(),
            "bytes": size,
            "sha256": digest.hexdigest(),
            "jpeg_boundary_markers": signature_ok,
        }
        if verify_decode:
            record["jpeg_decodable"] = decoded_ok
            # A failed decode or changed source has no validated dimensions.
            if decoded_ok:
                record.update(decoded_metadata)
        records.append(record)
    # A read failure is not evidence that the fixture directory is empty.
    # Preserve the actionable read/integrity error without adding a false
    # missing-fixtures diagnosis when matching camera files were encountered.
    if not records and not errors:
        errors.append("no JPEG-family fixtures found")
    return records, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Camera fixture directory (read-only)")
    parser.add_argument(
        "--verify-decode",
        action="store_true",
        help="Also require Pillow to decode every JPEG pixel stream (read-only).",
    )
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
    records, errors = inventory(root, verify_decode=args.verify_decode)
    print(json.dumps({"root": str(root), "files": records, "errors": errors},
                     indent=2, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
