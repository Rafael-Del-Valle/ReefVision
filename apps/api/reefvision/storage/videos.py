"""Managed video ingestion, frame access, tracker configuration, and export writes."""

from __future__ import annotations

import os
import shutil
import zipfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, BinaryIO
from uuid import uuid4

import yaml  # type: ignore[import-untyped]

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.storage.datasets import canonical_json_bytes
from reefvision.storage.projects import resolve_managed_project_path


@dataclass(frozen=True, slots=True)
class StagedVideoUpload:
    managed_path: str
    destination: Path
    temporary: Path
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class VideoProbe:
    width_px: int
    height_px: int
    frame_count: int
    fps: float
    duration_seconds: float
    codec: str | None


@dataclass(frozen=True, slots=True)
class VideoExportWriteResult:
    output_path: str
    archive_path: str
    manifest_path: str
    archive_sha256: str
    archive_size_bytes: int
    manifest_sha256: str
    file_checksums: dict[str, str]


TRACKER_DEFAULTS: dict[str, dict[str, bool | int | float | str]] = {
    "bytetrack": {
        "tracker_type": "bytetrack",
        "track_high_thresh": 0.25,
        "track_low_thresh": 0.1,
        "new_track_thresh": 0.25,
        "track_buffer": 30,
        "match_thresh": 0.8,
        "fuse_score": True,
    },
    "botsort": {
        "tracker_type": "botsort",
        "track_high_thresh": 0.25,
        "track_low_thresh": 0.1,
        "new_track_thresh": 0.25,
        "track_buffer": 30,
        "match_thresh": 0.8,
        "fuse_score": True,
        "gmc_method": "sparseOptFlow",
        "proximity_thresh": 0.5,
        "appearance_thresh": 0.8,
        "with_reid": False,
        "model": "auto",
    },
}


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stage_video_upload(
    settings: Settings,
    *,
    project_storage_root: str,
    video_id: str,
    suffix: str,
    stream: BinaryIO,
    maximum_bytes: int,
) -> StagedVideoUpload:
    managed_path = f"{project_storage_root}/videos/{video_id}{suffix}"
    destination = resolve_managed_project_path(settings, managed_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex[:8]}.upload")
    digest = sha256()
    size = 0
    try:
        with temporary.open("xb") as output:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(chunk)
                if size > maximum_bytes:
                    raise ValidationError("Video exceeds the configured upload limit")
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    if size == 0:
        temporary.unlink(missing_ok=True)
        raise ValidationError("The uploaded video is empty")
    return StagedVideoUpload(
        managed_path=managed_path,
        destination=destination,
        temporary=temporary,
        sha256=digest.hexdigest(),
        size_bytes=size,
    )


def commit_video_upload(staged: StagedVideoUpload) -> None:
    os.replace(staged.temporary, staged.destination)


def cleanup_video_upload(staged: StagedVideoUpload, *, include_destination: bool) -> None:
    staged.temporary.unlink(missing_ok=True)
    if include_destination:
        staged.destination.unlink(missing_ok=True)


def probe_video(path: Path) -> VideoProbe:
    try:
        import cv2
    except Exception as exc:
        raise ValidationError("OpenCV is required to inspect imported videos") from exc
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValidationError("The uploaded video could not be opened")
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        fourcc = int(capture.get(cv2.CAP_PROP_FOURCC) or 0)
    finally:
        capture.release()
    if width <= 0 or height <= 0 or frame_count <= 0 or fps <= 0:
        raise ValidationError("The uploaded video metadata is incomplete")
    codec = "".join(chr((fourcc >> (8 * index)) & 0xFF) for index in range(4)).strip("\x00 ")
    return VideoProbe(
        width_px=width,
        height_px=height,
        frame_count=frame_count,
        fps=fps,
        duration_seconds=frame_count / fps,
        codec=codec or None,
    )


def read_video_frame_jpeg(path: Path, frame_index: int, *, quality: int = 92) -> bytes:
    try:
        import cv2
    except Exception as exc:
        raise ValidationError("Video frame access requires OpenCV") from exc
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValidationError("The managed video could not be opened")
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
        if not ok:
            raise ValidationError(f"Video frame {frame_index} could not be decoded")
        encoded, buffer = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), quality],
        )
        if not encoded:
            raise ValidationError(f"Video frame {frame_index} could not be encoded")
        return bytes(buffer)
    finally:
        capture.release()


def remove_managed_video(settings: Settings, managed_path: str) -> None:
    resolve_managed_project_path(settings, managed_path).unlink(missing_ok=True)


@contextmanager
def tracker_config_workspace(
    settings: Settings,
    *,
    project_storage_root: str,
    job_id: str,
    tracker: str,
    options: Mapping[str, bool | int | float | str],
) -> Iterator[Path]:
    defaults = TRACKER_DEFAULTS.get(tracker)
    if defaults is None:
        raise ValidationError("Supported video trackers are ByteTrack and BoT-SORT")
    relative_root = f"{project_storage_root}/tmp/video-tracking/{job_id}"
    root = resolve_managed_project_path(settings, relative_root)
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=False)
    config_path = root / f"{tracker}.yaml"
    configuration = {**defaults, **dict(options), "tracker_type": tracker}
    try:
        temporary = config_path.with_suffix(".yaml.tmp")
        temporary.write_text(
            yaml.safe_dump(configuration, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, config_path)
        yield config_path
    finally:
        shutil.rmtree(root, ignore_errors=True)
        parent = root.parent
        with suppress(OSError):
            parent.rmdir()


def write_video_data_export(
    settings: Settings,
    *,
    relative_root: str,
    files: Mapping[str, bytes],
    manifest: dict[str, Any],
) -> VideoExportWriteResult:
    output_root = resolve_managed_project_path(settings, relative_root)
    archive_path = f"{relative_root}.zip"
    archive = resolve_managed_project_path(settings, archive_path)
    temporary_root = output_root.with_name(f".{output_root.name}.{uuid4().hex[:8]}.tmp")
    temporary_archive = archive.with_name(f".{archive.name}.{uuid4().hex[:8]}.tmp")
    if output_root.exists() or archive.exists():
        raise ValidationError("The managed video export destination already exists")
    published_root = False
    published_archive = False
    try:
        temporary_root.mkdir(parents=True, exist_ok=False)
        file_checksums: dict[str, str] = {}
        for relative_name, content in sorted(files.items()):
            destination = (temporary_root / relative_name).resolve()
            if not destination.is_relative_to(temporary_root.resolve()):
                raise ValidationError("Video export file path escapes the export root")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
            file_checksums[relative_name] = sha256(content).hexdigest()
        complete_manifest = {
            **manifest,
            "files": [
                {
                    "path": name,
                    "sha256": checksum,
                    "size_bytes": len(files[name]),
                }
                for name, checksum in sorted(file_checksums.items())
            ],
        }
        manifest_bytes = canonical_json_bytes(complete_manifest)
        (temporary_root / "manifest.json").write_bytes(manifest_bytes)
        manifest_sha256 = sha256(manifest_bytes).hexdigest()
        temporary_archive.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(
            temporary_archive,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as bundle:
            for item in sorted(temporary_root.rglob("*")):
                if item.is_file():
                    bundle.write(item, arcname=item.relative_to(temporary_root).as_posix())
        temporary_root.replace(output_root)
        published_root = True
        os.replace(temporary_archive, archive)
        published_archive = True
        return VideoExportWriteResult(
            output_path=relative_root,
            archive_path=archive_path,
            manifest_path=f"{relative_root}/manifest.json",
            archive_sha256=_file_sha256(archive),
            archive_size_bytes=archive.stat().st_size,
            manifest_sha256=manifest_sha256,
            file_checksums=file_checksums,
        )
    except Exception:
        shutil.rmtree(temporary_root, ignore_errors=True)
        temporary_archive.unlink(missing_ok=True)
        if published_root:
            shutil.rmtree(output_root, ignore_errors=True)
        if published_archive:
            archive.unlink(missing_ok=True)
        raise


def remove_video_export(
    settings: Settings,
    *,
    output_path: str,
    archive_path: str,
) -> None:
    shutil.rmtree(resolve_managed_project_path(settings, output_path), ignore_errors=True)
    resolve_managed_project_path(settings, archive_path).unlink(missing_ok=True)
