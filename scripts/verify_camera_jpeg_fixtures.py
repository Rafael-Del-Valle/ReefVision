#!/usr/bin/env python3
"""Read-only JPEG camera-fixture inventory for ReefVision 1.0.3 acceptance.

By default this validates JPEG signatures and produces an integrity manifest.
--verify-decode additionally asks Pillow to load every JPEG pixel stream, so
syntactically marked but undecodable images fail acceptance. Neither mode
proves installed WebView2 or GPU behavior. No originals are modified.
Decoded ICC payload hashes identify bytes, not scientifically validated color calibration.
Run against a backed-up, owner-approved fixture set.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import warnings
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

JPEG_SUFFIXES = {".jpg", ".jpeg", ".jpe", ".jfif", ".jfi", ".jif"}
JPEG_SOI = b"\xff\xd8"
JPEG_EOI = b"\xff\xd9"


def _camera_exif_label(value: object) -> tuple[str | None, bool]:
    """Return optional camera-declared Make/Model without accepting malformed tags.

    These are untrusted descriptive EXIF labels, not proof of camera origin;
    omit serial numbers, owner fields, location and original EXIF payloads.
    """
    if value is None:
        return None, False
    if type(value) is not str:
        return None, True
    label = value.rstrip("\x00").strip()
    if not label or len(label) > 128 or not label.isprintable():
        return None, True
    return label, False



def _normalized_exif_ascii(value: object) -> str | None:
    """Canonicalize ASCII EXIF text or NUL-padded bytes without guessing values.

    Pillow and camera firmware can expose the same EXIF tag as a string in
    IFD0 and as an ASCII byte sequence in ExifIFD. Only strip outer ASCII
    padding; undecodable bytes, interior NULs and non-text types remain
    untrusted. This matches the read-only application import validator.
    """
    if isinstance(value, bytes):
        try:
            value = value.decode("ascii")
        except UnicodeDecodeError:
            return None
    return value.strip(" \t\r\n\x00") if isinstance(value, str) else None


def _camera_exif_fields_agree(left: object, right: object) -> bool:
    """Require unambiguous matching exposure fields across EXIF directories."""
    normalized_left = _normalized_exif_ascii(left)
    return normalized_left is not None and normalized_left == _normalized_exif_ascii(right)


def _camera_exif_datetime_original(value: object) -> tuple[str | None, bool]:
    """Validate camera-local EXIF exposure time without inventing a UTC instant."""
    if value is None:
        return None, False
    normalized = _normalized_exif_ascii(value)
    if normalized is None or len(normalized) != 19:
        return None, True
    if re.fullmatch(r"[0-9]{4}:[0-9]{2}:[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}", normalized) is None:
        return None, True
    try:
        datetime.strptime(normalized, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None, True
    return normalized, False


def _camera_exif_offset_time_original(value: object) -> tuple[str | None, bool]:
    """Validate an explicit EXIF exposure offset; absence is not UTC."""
    if value is None:
        return None, False
    normalized = _normalized_exif_ascii(value)
    if normalized is None or len(normalized) != 6:
        return None, True
    if re.fullmatch(r"[+-][0-9]{2}:[0-9]{2}", normalized) is None:
        return None, True
    hours, minutes = int(normalized[1:3]), int(normalized[4:6])
    if hours > 14 or minutes > 59 or (hours == 14 and minutes != 0):
        return None, True
    return normalized, False


def _camera_exif_subsec_time_original(value: object) -> tuple[str | None, bool]:
    """Validate camera-local fractional seconds without fabricating precision.

    Preserve leading zeros; reject non-ASCII, non-digit and excessively long
    values rather than silently treating them as valid exposure evidence.
    """
    if value is None:
        return None, False
    normalized = _normalized_exif_ascii(value)
    if normalized is None or re.fullmatch(r"[0-9]{1,9}", normalized) is None:
        return None, True
    return normalized, False


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


def _open_camera_file(path: Path) -> BinaryIO:
    """Open a read-only handle without blocking on a substituted POSIX FIFO."""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        return os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise


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
            if not stat.S_ISREG(before.st_mode):
                errors.append(f"JPEG fixture changed during inventory: {relative}")
                continue
            with _open_camera_file(path) as stream:
                # A camera source can be replaced between path.stat() and
                # open(). Hash only the actual file handle that was validated,
                # never a substituted file with another study's image bytes.
                opened = os.fstat(stream.fileno())
                if not stat.S_ISREG(opened.st_mode) or (
                    _file_fingerprint(opened) != _file_fingerprint(before)
                ):
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
            or _is_linked_path(path)
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
                    with _open_camera_file(path) as decode_stream:
                        # Decode the exact verified file, not another image
                        # swapped into the path between hashing and Pillow.
                        decode_opened = os.fstat(decode_stream.fileno())
                        if not stat.S_ISREG(decode_opened.st_mode) or (
                            _file_fingerprint(decode_opened) != _file_fingerprint(after)
                        ):
                            raise ValueError("JPEG fixture changed before decoding")
                        with Image.open(decode_stream) as decoded:
                            if decoded.format != "JPEG":
                                raise ValueError("decoded format is not JPEG")
                            decoded.load()
                            # Native camera pixels are not EXIF-transposed.
                            exif = decoded.getexif()
                            orientation = exif.get(274)
                            camera_make, invalid_make = _camera_exif_label(exif.get(271))
                            camera_model, invalid_model = _camera_exif_label(exif.get(272))
                            if orientation is not None and (
                                # bool is an int subclass (True == 1), but a
                                # boolean EXIF orientation is not a valid
                                # camera-defined raster transform.
                                type(orientation) is not int
                                or orientation not in range(1, 9)
                            ):
                                raise ValueError("invalid EXIF orientation")
                            display_width, display_height = (
                                (decoded.height, decoded.width)
                                if orientation in (5, 6, 7, 8)
                                else (decoded.width, decoded.height)
                            )
                            # Real camera JPEGs can spread ICC payloads across
                            # multiple APP2 segments. Fingerprint the assembled
                            # bytes, never infer a calibrated color space from
                            # their presence or alter the original capture.
                            icc_profile = decoded.info.get("icc_profile")
                            if icc_profile is not None and (
                                not isinstance(icc_profile, bytes) or not icc_profile
                            ):
                                raise ValueError("invalid embedded ICC profile payload")
                            # EXIF PixelXDimension/PixelYDimension describe
                            # native raster axes, not orientation-corrected
                            # display dimensions. A stale value after cropping
                            # or recompression invalidates camera geometry QC.
                            # Some exporters store these tags in IFD0; prefer
                            # the standard nested Exif IFD when available.
                            exif_ifd = exif.get_ifd(34665)
                            if not isinstance(exif_ifd, dict):
                                raise ValueError("invalid EXIF IFD metadata")
                            # EXIF DateTimeOriginal is camera-local; prefer its
                            # standard nested IFD, but never silently hide
                            # contradictory metadata written in IFD0.
                            top_local = exif.get(36867)
                            top_offset = exif.get(36881)
                            nested_local = exif_ifd.get(36867)
                            nested_offset = exif_ifd.get(36881)
                            # SubSecTimeOriginal (37521) is part of the
                            # exposure timestamp too. Contradictory fractional
                            # seconds across IFD0 and ExifIFD must invalidate
                            # acquisition-time provenance, even when the whole
                            # seconds and UTC offset agree. Mirror the import
                            # validator's three-field conflict check.
                            exposure_ifd_conflict = any(
                                nested is not None
                                and top is not None
                                and not _camera_exif_fields_agree(nested, top)
                                for nested, top in (
                                    (nested_local, top_local),
                                    (nested_offset, top_offset),
                                    (exif_ifd.get(37521), exif.get(37521)),
                                )
                            )
                            capture_local, invalid_capture_local = (
                                _camera_exif_datetime_original(
                                    nested_local if nested_local is not None else top_local
                                )
                            )
                            capture_offset, invalid_capture_offset = (
                                _camera_exif_offset_time_original(
                                    nested_offset if nested_offset is not None else top_offset
                                )
                            )
                            capture_subsec, invalid_capture_subsec = (
                                _camera_exif_subsec_time_original(
                                    exif_ifd.get(37521)
                                    if exif_ifd.get(37521) is not None
                                    else exif.get(37521)
                                )
                            )
                            # A timezone offset without a timestamp cannot
                            # identify an exposure instant. Keep its QC finding
                            # separate from a missing (legitimate) timezone.
                            orphaned_exposure_offset = (
                                capture_local is None
                                and capture_offset is not None
                                and not invalid_capture_local
                            )
                            orphaned_exposure_subsec = (
                                capture_local is None
                                and capture_subsec is not None
                                and not invalid_capture_local
                            )
                            if exposure_ifd_conflict:
                                # Suppress the disputed values in the scientific
                                # manifest, while retaining an explicit QC flag.
                                capture_local = None
                                capture_offset = None
                                capture_subsec = None
                            ifd0_width = exif.get(40962)
                            ifd0_height = exif.get(40963)
                            exif_pixel_width = exif_ifd.get(40962, ifd0_width)
                            exif_pixel_height = exif_ifd.get(40963, ifd0_height)
                            # Some exporters leave stale pixel dimensions in
                            # IFD0 while writing corrected values into Exif IFD.
                            # Preferring Exif IFD must not silently conceal
                            # contradictory provenance even when its values
                            # match the decoded raster.
                            exif_ifd0_conflict = any(
                                nested is not None
                                and top_level is not None
                                and (
                                    type(nested) is not int
                                    or type(top_level) is not int
                                    or nested != top_level
                                )
                                for nested, top_level in (
                                    (exif_ifd.get(40962), ifd0_width),
                                    (exif_ifd.get(40963), ifd0_height),
                                )
                            )
                            # Absence of these optional EXIF tags is not
                            # evidence of consistency. Report conflicts as
                            # scientific QC errors, not JPEG decode failures.
                            exif_dimensions_match_raster: bool | None = None
                            if (
                                exif_pixel_width is not None
                                or exif_pixel_height is not None
                            ):
                                exif_dimensions_match_raster = (
                                    type(exif_pixel_width) is int
                                    and type(exif_pixel_height) is int
                                    and exif_pixel_width > 0
                                    and exif_pixel_height > 0
                                    and (exif_pixel_width, exif_pixel_height)
                                    == (decoded.width, decoded.height)
                                    and not exif_ifd0_conflict
                                )
                            decoded_metadata = {
                                "jpeg_pixel_width": decoded.width,
                                "jpeg_pixel_height": decoded.height,
                                "jpeg_display_width": display_width,
                                "jpeg_display_height": display_height,
                                "jpeg_color_mode": decoded.mode,
                                "jpeg_exif_orientation": orientation,
                                "jpeg_exif_camera_make": camera_make,
                                "jpeg_exif_camera_model": camera_model,
                                "jpeg_exif_camera_make_malformed": invalid_make,
                                "jpeg_exif_camera_model_malformed": invalid_model,
                                "jpeg_exif_datetime_original_local": capture_local,
                                "jpeg_exif_offset_time_original": capture_offset,
                                "jpeg_exif_subsec_time_original": capture_subsec,
                                "jpeg_exif_subsec_time_original_malformed": (
                                    invalid_capture_subsec
                                ),
                                "jpeg_exif_subsec_without_datetime_original": (
                                    orphaned_exposure_subsec
                                ),
                                "jpeg_exif_datetime_original_malformed": invalid_capture_local,
                                "jpeg_exif_offset_time_original_malformed": invalid_capture_offset,
                                "jpeg_exif_exposure_ifd_conflict": exposure_ifd_conflict,
                                "jpeg_exif_offset_without_datetime_original": orphaned_exposure_offset,
                                "jpeg_exif_capture_timezone_unknown": (
                                    capture_local is not None and capture_offset is None
                                ),
                                # Malformed EXIF scalar tags can decode as bytes,
                                # tuples, or strings. A raw bytes object breaks the
                                # JSON acceptance manifest; do not coerce it into
                                # a plausible scientific pixel measurement.
                                "jpeg_exif_pixel_width": (
                                    exif_pixel_width if type(exif_pixel_width) is int else None
                                ),
                                "jpeg_exif_pixel_height": (
                                    exif_pixel_height if type(exif_pixel_height) is int else None
                                ),
                                "jpeg_exif_pixel_width_invalid_type": (
                                    type(exif_pixel_width).__name__
                                    if exif_pixel_width is not None
                                    and type(exif_pixel_width) is not int
                                    else None
                                ),
                                "jpeg_exif_pixel_height_invalid_type": (
                                    type(exif_pixel_height).__name__
                                    if exif_pixel_height is not None
                                    and type(exif_pixel_height) is not int
                                    else None
                                ),
                                "jpeg_exif_dimensions_match_raster": (
                                    exif_dimensions_match_raster
                                ),
                                "jpeg_exif_ifd0_dimension_conflict": exif_ifd0_conflict,
                                "jpeg_icc_profile_present": icc_profile is not None,
                                "jpeg_icc_profile_bytes": (
                                    len(icc_profile) if icc_profile is not None else 0
                                ),
                                "jpeg_icc_profile_sha256": (
                                    hashlib.sha256(icc_profile).hexdigest()
                                    if icc_profile is not None
                                    else None
                                ),
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
                    _is_linked_path(path)
                    or any(
                        _file_fingerprint(observed) != _file_fingerprint(after)
                        for observed in (decode_opened, decode_finished, decoded_stat)
                    )
                ):
                    errors.append(f"JPEG fixture changed during decoding: {relative}")
                else:
                    decoded_ok = True
                    if (
                        decoded_metadata["jpeg_exif_camera_make_malformed"]
                        or decoded_metadata["jpeg_exif_camera_model_malformed"]
                    ):
                        errors.append(f"invalid EXIF camera Make/Model metadata: {relative}")
                    if (
                        decoded_metadata["jpeg_exif_datetime_original_malformed"]
                        or decoded_metadata["jpeg_exif_offset_time_original_malformed"]
                        or decoded_metadata["jpeg_exif_subsec_time_original_malformed"]
                    ):
                        errors.append(f"invalid EXIF camera exposure time metadata: {relative}")
                    if decoded_metadata["jpeg_exif_exposure_ifd_conflict"]:
                        errors.append(
                            "conflicting EXIF camera exposure metadata between IFD0 and Exif IFD: "
                            f"{relative}"
                        )
                    elif decoded_metadata["jpeg_exif_offset_without_datetime_original"]:
                        errors.append(
                            f"EXIF camera offset without original exposure time: {relative}"
                        )
                    if (
                        decoded_metadata["jpeg_exif_subsec_without_datetime_original"]
                        and not decoded_metadata["jpeg_exif_exposure_ifd_conflict"]
                    ):
                        errors.append(
                            f"EXIF camera fractional seconds without original exposure time: {relative}"
                        )
                    if decoded_metadata["jpeg_exif_ifd0_dimension_conflict"]:
                        errors.append(
                            "conflicting EXIF pixel dimensions between IFD0 and Exif IFD: "
                            f"{relative}"
                        )
                    elif decoded_metadata["jpeg_exif_dimensions_match_raster"] is False:
                        errors.append(
                            "EXIF pixel dimensions inconsistent with JPEG raster: "
                            f"{relative}"
                        )
            except ImportError:
                errors.append(f"Pillow JPEG decoder unavailable: {relative}")
            except (
                OSError,
                ValueError,
                # Pillow may raise these while walking malformed camera EXIF
                # IFDs. Reject that JPEG, keep inspecting other originals.
                EOFError,
                IndexError,
                KeyError,
                SyntaxError,
                TypeError,
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



def _valid_decoded_geometry(entry: dict[str, object]) -> bool:
    """Require actual raw/display dimensions before accepting decode evidence."""
    width = entry.get("jpeg_pixel_width")
    height = entry.get("jpeg_pixel_height")
    display_width = entry.get("jpeg_display_width")
    display_height = entry.get("jpeg_display_height")
    if any(
        type(value) is not int or value <= 0
        for value in (width, height, display_width, display_height)
    ):
        return False
    if "jpeg_exif_orientation" not in entry:
        return False
    orientation = entry["jpeg_exif_orientation"]
    if orientation is not None and (
        type(orientation) is not int or orientation not in range(1, 9)
    ):
        return False
    expected = (height, width) if orientation in (5, 6, 7, 8) else (width, height)
    return (display_width, display_height) == expected


def compare_source_manifest(
    root: Path, current: list[dict[str, object]], baseline: object
) -> list[str]:
    """Fail closed if the approved camera source set changed since inventory.

    This checks a caller-supplied baseline, not its authenticity. Store the
    baseline and its independent hash outside the fixture tree before import.
    """
    if not isinstance(baseline, dict):
        return ["baseline JPEG manifest must be a JSON object"]
    if baseline.get("root") != str(root):
        return ["baseline JPEG manifest root differs from the inspected directory"]
    if baseline.get("errors") != []:
        return ["baseline JPEG manifest has missing or nonempty error evidence"]
    source_files = baseline.get("files")
    if not isinstance(source_files, list) or not source_files:
        return ["baseline JPEG manifest must contain at least one source file"]

    expected: dict[str, tuple[int, str]] = {}
    expected_hashes: set[str] = set()
    # A previously decoded camera baseline must not be silently downgraded to
    # header-only verification in the post-import acceptance pass.
    expected_decoded: dict[str, dict[str, object]] = {}
    for entry in source_files:
        if not isinstance(entry, dict):
            return ["baseline JPEG manifest contains a non-object file entry"]
        relative, size, checksum = (
            entry.get("path"), entry.get("bytes"), entry.get("sha256")
        )
        if (
            not isinstance(relative, str)
            or not relative
            or "\\" in relative
            or relative.startswith("/")
            or any(component in ("", ".", "..") for component in relative.split("/"))
            or Path(relative).suffix.lower() not in JPEG_SUFFIXES
            or type(size) is not int
            or size < len(JPEG_SOI) + len(JPEG_EOI)
            or not isinstance(checksum, str)
            or re.fullmatch(r"[0-9a-f]{64}", checksum) is None
            or entry.get("jpeg_boundary_markers") is not True
        ):
            return ["baseline JPEG manifest contains malformed source-file evidence"]
        if relative in expected:
            return ["baseline JPEG manifest contains duplicate source-file paths"]
        # Replayed manifests must enforce the same duplicate-source rule as
        # inventory(), even if distinct filenames have been fabricated.
        if checksum in expected_hashes:
            return ["baseline JPEG manifest contains duplicate source bytes"]
        expected_hashes.add(checksum)
        expected[relative] = (size, checksum)
        if "jpeg_decodable" in entry:
            if entry["jpeg_decodable"] is not True:
                return ["baseline JPEG manifest contains unverified pixel-decode evidence"]
            if not _valid_decoded_geometry(entry):
                return ["baseline JPEG manifest contains invalid decoded geometry evidence"]
            expected_decoded[relative] = entry

    # Do not let a duplicated current path overwrite an earlier record.
    # A dict comprehension would silently discard one source observation and
    # could certify a malformed inventory against a valid saved baseline.
    actual: dict[str, dict[str, object]] = {}
    for record in current:
        if not isinstance(record, dict):
            return ["current JPEG inventory contains malformed source-file evidence"]
        relative, size, checksum = (
            record.get("path"), record.get("bytes"), record.get("sha256")
        )
        # A caller can replay a saved or corrupted inventory directly. Do
        # not certify missing/invalid measurements, a changed path, or an
        # unchecked JPEG signature merely because a dictionary lookup works.
        if (
            not isinstance(relative, str)
            or not relative
            or "\\" in relative
            or relative.startswith("/")
            or any(component in ("", ".", "..") for component in relative.split("/"))
            or Path(relative).suffix.lower() not in JPEG_SUFFIXES
            or type(size) is not int
            or size < len(JPEG_SOI) + len(JPEG_EOI)
            or not isinstance(checksum, str)
            or re.fullmatch(r"[0-9a-f]{64}", checksum) is None
            or record.get("jpeg_boundary_markers") is not True
        ):
            return ["current JPEG inventory contains malformed source-file evidence"]
        if relative in actual:
            return ["current JPEG inventory contains duplicate source-file paths"]
        actual[relative] = record
    errors: list[str] = []
    actual_hashes: dict[str, str] = {}
    for relative, record in sorted(actual.items()):
        checksum = str(record["sha256"])
        previous = actual_hashes.setdefault(checksum, relative)
        if previous != relative:
            errors.append(
                f"current JPEG inventory contains duplicate source bytes: {previous!r} / {relative!r}"
            )
    for relative in sorted(expected.keys() - actual.keys()):
        errors.append(f"source JPEG missing since baseline: {relative!r}")
    for relative in sorted(actual.keys() - expected.keys()):
        errors.append(f"source JPEG added since baseline: {relative!r}")
    for relative in sorted(actual.keys() & expected.keys()):
        record = actual[relative]
        if (record["bytes"], record["sha256"]) != expected[relative]:
            errors.append(f"source JPEG bytes changed since baseline: {relative!r}")
        if relative in expected_decoded:
            if record.get("jpeg_decodable") is not True:
                errors.append(
                    f"source JPEG pixel decoding not reverified since baseline: {relative!r}"
                )
                continue
            # Stable file bytes alone cannot reveal a decoder/library change
            # that silently alters raw-vs-display dimensions, EXIF exposure
            # provenance, or the assembled camera ICC payload. Compare only
            # fields the saved verified decoder actually emitted.
            for field in (
                "jpeg_pixel_width",
                "jpeg_pixel_height",
                "jpeg_display_width",
                "jpeg_display_height",
                "jpeg_color_mode",
                "jpeg_exif_orientation",
                "jpeg_exif_camera_make",
                "jpeg_exif_camera_model",
                "jpeg_exif_datetime_original_local",
                "jpeg_exif_offset_time_original",
                "jpeg_exif_subsec_time_original",
                # Preserve the QC/uncertainty verdict, not merely the parsed
                # values. Decoder drift that turns an unknown timezone or a
                # conflicting EXIF tag into an apparent valid measurement must
                # invalidate the approved read-only scientific baseline.
                "jpeg_exif_camera_make_malformed",
                "jpeg_exif_camera_model_malformed",
                "jpeg_exif_datetime_original_malformed",
                "jpeg_exif_offset_time_original_malformed",
                "jpeg_exif_subsec_time_original_malformed",
                "jpeg_exif_exposure_ifd_conflict",
                "jpeg_exif_offset_without_datetime_original",
                "jpeg_exif_subsec_without_datetime_original",
                "jpeg_exif_capture_timezone_unknown",
                "jpeg_exif_pixel_width",
                "jpeg_exif_pixel_height",
                "jpeg_exif_pixel_width_invalid_type",
                "jpeg_exif_pixel_height_invalid_type",
                "jpeg_exif_ifd0_dimension_conflict",
                "jpeg_exif_dimensions_match_raster",
                "jpeg_icc_profile_present",
                "jpeg_icc_profile_bytes",
                "jpeg_icc_profile_sha256",
            ):
                prior = expected_decoded[relative]
                if field in prior and (
                    field not in record
                    or type(record[field]) is not type(prior[field])
                    or record[field] != prior[field]
                ):
                    errors.append(
                        f"source JPEG decoded {field} changed since baseline: {relative!r}"
                    )
    return errors



def _unique_manifest_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject ambiguous JSON objects instead of trusting the last duplicate key."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member in baseline JPEG manifest")
        result[key] = value
    return result


def _reject_manifest_constant(value: str) -> object:
    """Scientific evidence must use standard JSON, not NaN or Infinity."""
    raise ValueError("non-finite JSON constant in baseline JPEG manifest")


def _read_baseline_manifest(path: Path) -> bytes:
    """Read only a bounded, stable regular file, never a pipe or device."""
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("baseline JPEG manifest is not a regular file")
    limit = 32 * 1024 * 1024
    if before.st_size > limit:
        raise ValueError("baseline JPEG manifest exceeds 32 MiB")
    # Nonblocking open prevents a substituted POSIX FIFO from hanging the
    # acceptance check. O_NOFOLLOW also rejects a swapped final symlink.
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or (
            _file_fingerprint(opened) != _file_fingerprint(before)
        ):
            raise ValueError("baseline JPEG manifest changed before reading")
        payload = stream.read(limit + 1)
        finished = os.fstat(stream.fileno())
    after = path.stat()
    if len(payload) > limit:
        raise ValueError("baseline JPEG manifest exceeds 32 MiB")
    if (
        len(payload) != before.st_size
        or _is_linked_path(path)
        or any(
            _file_fingerprint(observed) != _file_fingerprint(before)
            for observed in (finished, after)
        )
    ):
        raise ValueError("baseline JPEG manifest changed during reading")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Camera fixture directory (read-only)")
    parser.add_argument(
        "--verify-decode",
        action="store_true",
        help="Also require Pillow to decode every JPEG pixel stream (read-only).",
    )
    parser.add_argument(
        "--compare-manifest",
        type=Path,
        help="Compare exact source filenames, sizes and SHA-256 against a saved JSON inventory (read-only).",
    )
    parser.add_argument(
        "--expected-manifest-sha256",
        metavar="SHA256",
        help=(
            "Require baseline JSON to match an independently recorded SHA-256 "
            "(requires --compare-manifest)."
        ),
    )
    args = parser.parse_args()
    if args.expected_manifest_sha256 is not None:
        if args.compare_manifest is None:
            parser.error("--expected-manifest-sha256 requires --compare-manifest")
        if re.fullmatch(r"[0-9a-fA-F]{64}", args.expected_manifest_sha256) is None:
            parser.error(
                "--expected-manifest-sha256 must contain 64 hexadecimal digits"
            )
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
    if args.compare_manifest is not None:
        # The baseline is independent scientific evidence, not another camera
        # source. Never read a linked/junctioned manifest or a manifest inside
        # the approved original-image tree: both can silently redirect or
        # contaminate a supposedly immutable camera acceptance inventory.
        baseline_candidate = args.compare_manifest.absolute()
        if any(
            _is_linked_path(component)
            for component in (baseline_candidate, *baseline_candidate.parents)
        ):
            parser.error(
                "baseline JPEG manifest must not traverse a symbolic link or junction"
            )
        try:
            baseline_path = baseline_candidate.resolve(strict=False)
        except (OSError, RuntimeError):
            parser.error("cannot resolve baseline JPEG manifest path")
        if baseline_path.is_relative_to(root):
            parser.error(
                "baseline JPEG manifest must be stored outside the camera fixture directory"
            )
    records, errors = inventory(root, verify_decode=args.verify_decode)
    if args.compare_manifest is not None:
        try:
            baseline_bytes = _read_baseline_manifest(args.compare_manifest)
            baseline = json.loads(
                baseline_bytes,
                object_pairs_hook=_unique_manifest_object,
                parse_constant=_reject_manifest_constant,
            )
        except (OSError, ValueError, UnicodeError) as exc:
            errors.append(f"cannot read baseline JPEG manifest: {type(exc).__name__}")
        else:
            # Checking source bytes against a co-edited baseline is not independent
            # integrity evidence. Require its separately recorded digest when
            # supplied, so changing both the capture and JSON cannot pass QC.
            if (
                args.expected_manifest_sha256 is not None
                and hashlib.sha256(baseline_bytes).hexdigest()
                != args.expected_manifest_sha256.lower()
            ):
                errors.append(
                    "baseline JPEG manifest SHA-256 mismatch: saved file differs "
                    "from independently recorded digest"
                )
            else:
                errors.extend(compare_source_manifest(root, records, baseline))
    print(json.dumps({"root": str(root), "files": records, "errors": errors},
                     indent=2, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
