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


def _file_fingerprint(stat: os.stat_result) -> tuple[int, ...]:
    """Compare file identity/content metadata from path and open-handle stat."""
    stable = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    if os.name == "nt":
        # CPython on Windows can report a different st_ctime_ns for stat(path)
        # and fstat(fd) of the *same* file. Using it as a cross-API identity
        # check rejects immutable JPEGs nondeterministically. Keep volume,
        # file ID, size and modification time checks, plus the content hash.
        # See CPython issue 157671. POSIX retains the stricter ctime check.
        return stable
    return (*stable, stat.st_ctime_ns)


def _is_windows_junction(path: Path) -> bool:
    """Detect NTFS junctions, which can bypass followlinks=False on Windows."""
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None:
        return bool(is_junction())
    # Python 3.11 lacks Path.is_junction(), but NTFS junctions still expose
    # the mount-point reparse tag through lstat. Never follow it to inspect
    # another study directory. The native API is preferred on Python 3.12+.
    try:
        return getattr(path.lstat(), "st_reparse_tag", None) == 0xA0000003
    except OSError:
        return False


def _is_linked_path(path: Path) -> bool:
    return path.is_symlink() or _is_windows_junction(path)


def inventory(root: Path, *, verify_decode: bool = False) -> tuple[list[dict[str, object]], list[str]]:
    # This function is also imported directly by tests and acceptance tools.
    # Enforce the same root boundary as the CLI before rglob can follow a
    # linked root or parent into an unapproved camera directory.
    candidate = root.absolute()
    if any(_is_linked_path(component) for component in (candidate, *candidate.parents)):
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
    # A lone approved path can be a hard link to another study's image outside
    # the fixture tree. Count every inventoried link to each known file ID;
    # fail acceptance when the filesystem reports additional unseen links.
    inventoried_link_counts: dict[tuple[int, int], int] = {}
    filesystem_link_counts: dict[tuple[int, int], int] = {}
    # Separate copied captures are not independent scientific observations
    # merely because they have distinct filenames and filesystem inodes.
    seen_content_hashes: dict[str, str] = {}
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
            elif _is_windows_junction(child):
                errors.append(f"junction directory not inspected: {child.relative_to(root)}")
            elif Path(dirname.rstrip(" .")).suffix.lower() in JPEG_SUFFIXES:
                # os.walk lists directories separately from filenames. A
                # JPEG-suffixed directory could otherwise vanish from the
                # camera-source manifest without an explicit acceptance error.
                # Still inspect its contents for genuine captures; never open
                # or alter the directory as if it were an image.
                errors.append(
                    f"non-regular JPEG fixture directory not inspected: {child.relative_to(root)}"
                )
        dirnames[:] = sorted(name for name in dirnames if not _is_linked_path(parent / name))
        # Win32 ignores trailing spaces/dots in filenames. A POSIX export
        # containing frame.JPG. or frame.jpeg<space> must be inventoried and
        # flagged below, not silently omitted from camera acceptance.
        jpeg_paths.extend(
            parent / name for name in filenames
            if Path(name.rstrip(" .")).suffix.lower() in JPEG_SUFFIXES
        )
    for path in sorted(jpeg_paths):
        relative = path.relative_to(root).as_posix()
        # An apparent JPEG may be a FIFO, socket, device or NTFS reparse
        # point. Reject it explicitly rather than silently producing a
        # scientifically incomplete inventory. Never attempt to open it.
        if path.is_symlink():
            errors.append(f"symlink not inspected: {relative}")
            continue
        if _is_windows_junction(path):
            errors.append(f"junction file not inspected: {relative}")
            continue
        if not path.is_file():
            errors.append(f"non-regular JPEG fixture not inspected: {relative}")
            continue
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
                # A camera source can be replaced between path.stat() and
                # open(). Hash only the actual file handle that was validated,
                # never a substituted file with another study's image bytes.
                opened = os.fstat(stream.fileno())
                if _file_fingerprint(opened) != _file_fingerprint(before):
                    errors.append(f"JPEG fixture changed during inventory: {relative}")
                    continue
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    if not first:
                        first = block[:2]
                    tail = (tail + block)[-2:]
                    size += len(block)
                    digest.update(block)
                read_finished = os.fstat(stream.fileno())
            after = path.stat()
        except OSError as exc:
            errors.append(f"cannot read JPEG fixture: {relative}: {type(exc).__name__}")
            continue
        if (
            size != before.st_size
            or path.is_symlink()
            or any(
                _file_fingerprint(observed) != _file_fingerprint(before)
                for observed in (opened, read_finished, after)
            )
        ):
            errors.append(f"JPEG fixture changed during inventory: {relative}")
            continue
        # Two directory entries may be hard links to one underlying capture.
        # Keep both manifest records, but flag duplicate scientific inputs so
        # downstream acceptance cannot mistake aliases for independent images.
        # Some filesystems report inode zero (unknown); never infer an alias
        # from an unavailable file identity.
        hardlink_alias = False
        if after.st_ino:
            identity = (after.st_dev, after.st_ino)
            inventoried_link_counts[identity] = inventoried_link_counts.get(identity, 0) + 1
            filesystem_link_counts[identity] = max(
                filesystem_link_counts.get(identity, 0), after.st_nlink
            )
            previous_identity = seen_file_identities.setdefault(identity, relative)
            if previous_identity != relative:
                hardlink_alias = True
                errors.append(f"JPEG hard-link alias (same source image): {previous_identity} / {relative}")
        checksum = digest.hexdigest()
        previous_source = seen_content_hashes.setdefault(checksum, relative)
        if previous_source != relative and not hardlink_alias:
            # Flag byte-identical copies in different files or directories.
            # Do not double-report an already identified hard-link alias.
            errors.append(f"JPEG duplicate source bytes (SHA-256): {previous_source} / {relative}")
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
                    with path.open("rb") as decode_stream:
                        # Decode the exact verified file, not another image
                        # swapped into the path between hashing and Pillow.
                        decode_opened = os.fstat(decode_stream.fileno())
                        if _file_fingerprint(decode_opened) != _file_fingerprint(after):
                            raise ValueError("JPEG fixture changed before decoding")
                        with Image.open(decode_stream) as decoded:
                            if decoded.format != "JPEG":
                                raise ValueError("decoded format is not JPEG")
                            decoded.load()
                            # Native camera pixels are not EXIF-transposed.
                            orientation = decoded.getexif().get(274)
                            if orientation is not None and (
                                not isinstance(orientation, int)
                                or orientation not in range(1, 9)
                            ):
                                raise ValueError("invalid EXIF orientation")
                            display_width, display_height = (
                                (decoded.height, decoded.width)
                                if orientation in (5, 6, 7, 8)
                                else (decoded.width, decoded.height)
                            )
                            decoded_metadata = {
                                "jpeg_pixel_width": decoded.width,
                                "jpeg_pixel_height": decoded.height,
                                "jpeg_display_width": display_width,
                                "jpeg_display_height": display_height,
                                "jpeg_color_mode": decoded.mode,
                                "jpeg_exif_orientation": orientation,
                            }
                        # Windows file identity/mtime can remain unchanged after
                        # a same-size in-place rewrite. Rehash the exact decoded
                        # handle so reported geometry is tied to manifest bytes.
                        decode_stream.seek(0)
                        decoded_digest = hashlib.sha256()
                        for block in iter(lambda: decode_stream.read(1024 * 1024), b""):
                            decoded_digest.update(block)
                        if decoded_digest.hexdigest() != checksum:
                            raise ValueError("JPEG bytes changed between hashing and decoding")
                        decode_finished = os.fstat(decode_stream.fileno())
                # A modified camera fixture cannot be accepted against the
                # SHA-256 generated by the prior immutable manifest pass.
                decoded_stat = path.stat()
                if (
                    path.is_symlink()
                    or any(
                        _file_fingerprint(observed) != _file_fingerprint(after)
                        for observed in (decode_opened, decode_finished, decoded_stat)
                    )
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
            "extension": Path(path.name.rstrip(" .")).suffix.lower(),
            "bytes": size,
            "sha256": checksum,
            "jpeg_boundary_markers": signature_ok,
        }
        if verify_decode:
            record["jpeg_decodable"] = decoded_ok
            # A failed decode or changed source has no validated dimensions.
            if decoded_ok:
                record.update(decoded_metadata)
        records.append(record)
    # An in-root duplicate is already reported above. An additional hard
    # link not inventoried by this read-only walk may point at an unapproved
    # camera/study source; it cannot be accepted as independently sourced.
    # Zero/unknown inode IDs are excluded from this inference above.
    for identity, link_total in filesystem_link_counts.items():
        inspected = inventoried_link_counts[identity]
        if link_total > inspected:
            relative = seen_file_identities[identity]
            errors.append(
                "JPEG hard-link alias outside approved fixture inventory: "
                f"{relative} ({inspected} inventoried of {link_total} filesystem links)"
            )
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
    if any(_is_linked_path(component) for component in (candidate, *candidate.parents)):
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
