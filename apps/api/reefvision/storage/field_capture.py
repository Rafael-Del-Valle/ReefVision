"""Local immutable field originals and bounded, content-verified batch transfer."""

from __future__ import annotations

import hashlib
import mimetypes
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import IO, BinaryIO
from uuid import uuid4
from zipfile import ZIP_STORED, BadZipFile, ZipFile

from pydantic import ValidationError as SchemaValidationError

from reefvision.config import Settings
from reefvision.domain.errors import ValidationError
from reefvision.schemas.field_capture import (
    MAX_FIELD_OBSERVATIONS,
    FieldCaptureArchiveManifest,
    FieldCaptureEntry,
    MediaKind,
)
from reefvision.storage.datasets import canonical_json_bytes, canonical_json_sha256
from reefvision.storage.images import (
    InvalidImageError,
    UnsupportedImageError,
    commit_staged_image,
    ensure_supported_extension,
    inspect_staged_image,
    safe_original_name,
    stream_to_staging,
)
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.storage.video_media import SUPPORTED_VIDEO_EXTENSIONS, inspect_video

MAX_FIELD_MEDIA_BYTES = 100 * 1024**3
MAX_FIELD_MANIFEST_BYTES = 16 * 1024**2


def field_member(sha256: str) -> str:
    return f"media/{sha256}"


def field_filename(filename: str | None) -> str:
    if not filename:
        raise ValidationError("A source filename is required")
    name = safe_original_name(filename)
    if len(name) > 255 or any(ord(character) < 32 for character in name):
        raise ValidationError("Field source filename is invalid")
    return name


def field_media_kind(filename: str) -> MediaKind:
    if Path(filename).suffix.casefold() in SUPPORTED_VIDEO_EXTENSIONS:
        return "video"
    try:
        ensure_supported_extension(filename)
    except UnsupportedImageError as exc:
        raise ValidationError("Choose a supported image or video file") from exc
    return "image"


def inspect_field_media(path: Path, kind: MediaKind, sha256: str, size: int) -> None:
    if kind == "video":
        inspect_video(path)
    else:
        try:
            inspect_staged_image(path, sha256, size)
        except (InvalidImageError, UnsupportedImageError) as exc:
            raise ValidationError(str(exc)) from exc


class FieldCaptureStorage:
    def __init__(self, settings: Settings, project_storage_root: str) -> None:
        self.settings = settings
        self.project_root = project_storage_root
        self.root = f"{project_storage_root}/field_capture"

    def _resolve(self, relative: str) -> Path:
        return resolve_managed_project_path(self.settings, relative)

    @contextmanager
    def staging(self) -> Iterator[Path]:
        path = self._resolve(f"{self.root}/staging")
        path.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=path) as temporary:
            yield Path(temporary)

    def stage_source(
        self, stream: IO[bytes], filename: str, kind: MediaKind, directory: Path
    ) -> tuple[Path, str, int]:
        path = directory / f"{uuid4()}{Path(filename).suffix.casefold()}"
        sha256, size = stream_to_staging(stream, path, max_bytes=MAX_FIELD_MEDIA_BYTES)
        if not size:
            raise ValidationError("Field source file is empty")
        inspect_field_media(path, kind, sha256, size)
        return path, sha256, size

    def verify(self, relative: str, sha256: str, size: int) -> Path:
        path = self._resolve(relative)
        if not path.is_relative_to(self._resolve(self.project_root)):
            raise ValidationError("Field source does not belong to this project storage")
        try:
            with path.open("rb") as stream:
                if (
                    path.stat().st_size != size
                    or hashlib.file_digest(stream, "sha256").hexdigest() != sha256
                ):
                    raise ValidationError(
                        "Managed field or project source differs from recorded bytes"
                    )
        except OSError as exc:
            raise ValidationError("Managed field or project source is unavailable") from exc
        return path

    def preserve(self, path: Path, entry: FieldCaptureEntry) -> str:
        # A crash between publication and the database commit leaves reusable bytes.
        # Rechecking a content-addressed target also detects on-disk corruption.
        relative = f"{self.root}/originals/{entry.kind}/{entry.sha256}"
        if self._resolve(relative).exists():
            self.verify(relative, entry.sha256, entry.size_bytes)
        else:
            commit_staged_image(path, self._resolve(relative))
        return relative

    def publish_project_original(
        self, source: Path, relative: str, sha256: str, size: int, directory: Path
    ) -> None:
        destination = self._resolve(relative)
        if destination.exists():
            self.verify(relative, sha256, size)
            return
        stage = directory / str(uuid4())
        with source.open("rb") as stream:
            actual = stream_to_staging(stream, stage, max_bytes=size)
        if actual != (sha256, size):
            raise ValidationError("Field source changed during reconciliation")
        commit_staged_image(stage, destination)

    @contextmanager
    def read_archive(
        self, stream: BinaryIO
    ) -> Iterator[tuple[FieldCaptureArchiveManifest, dict[str, Path]]]:
        with self.staging() as directory:
            try:
                with ZipFile(stream) as package:
                    entries = package.infolist()
                    names = {entry.filename: entry for entry in entries}
                    if len(entries) != len(names) or len(entries) > MAX_FIELD_OBSERVATIONS + 1:
                        raise ValidationError(
                            "Field batch archive repeats members or exceeds its entry bound"
                        )
                    manifest_info = names.get("manifest.json")
                    if manifest_info is None or manifest_info.file_size > MAX_FIELD_MANIFEST_BYTES:
                        raise ValidationError(
                            "Field batch archive manifest is missing or too large"
                        )
                    manifest = FieldCaptureArchiveManifest.model_validate_json(
                        package.read(manifest_info)
                    )
                    if (
                        canonical_json_sha256(manifest.manifest.model_dump(mode="json"))
                        != manifest.manifest_sha256
                    ):
                        raise ValidationError("Field batch manifest checksum does not match")
                    expected: dict[str, FieldCaptureEntry] = {}
                    for entry in manifest.manifest.observations:
                        if field_media_kind(entry.filename) != entry.kind:
                            raise ValidationError(
                                "Field batch filename and media kind do not agree"
                            )
                        name = field_member(entry.sha256)
                        previous = expected.setdefault(name, entry)
                        if (previous.kind, previous.size_bytes) != (entry.kind, entry.size_bytes):
                            raise ValidationError(
                                "Field batch assigns inconsistent evidence to the same media"
                            )
                    if names.keys() != {"manifest.json", *expected}:
                        raise ValidationError(
                            "Field batch archive members do not match its manifest"
                        )
                    if sum(entry.size_bytes for entry in expected.values()) > MAX_FIELD_MEDIA_BYTES:
                        raise ValidationError("Field batch exceeds the allowed expanded byte bound")
                    files: dict[str, Path] = {}
                    for name, entry in expected.items():
                        if names[name].file_size != entry.size_bytes:
                            raise ValidationError(
                                "Field batch media size does not match its manifest"
                            )
                        with package.open(name) as source:
                            path, digest, size = self.stage_source(
                                source, entry.filename, entry.kind, directory
                            )
                        if digest != entry.sha256 or size != entry.size_bytes:
                            raise ValidationError(
                                "Field batch media checksum does not match its manifest"
                            )
                        files[entry.sha256] = path
            except (BadZipFile, NotImplementedError, RuntimeError, SchemaValidationError) as exc:
                raise ValidationError("Invalid or unsupported field batch archive") from exc
            yield manifest, files

    def write_archive(
        self,
        manifest: FieldCaptureArchiveManifest,
        originals: Sequence[tuple[FieldCaptureEntry, str]],
    ) -> Path:
        directory = self._resolve(f"{self.root}/downloads")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{uuid4()}.zip"
        try:
            with ZipFile(path, "x", compression=ZIP_STORED) as package:
                package.writestr(
                    "manifest.json", canonical_json_bytes(manifest.model_dump(mode="json"))
                )
                written: set[str] = set()
                for entry, relative in originals:
                    source = self.verify(relative, entry.sha256, entry.size_bytes)
                    if entry.sha256 not in written:
                        package.write(source, field_member(entry.sha256))
                        written.add(entry.sha256)
        except Exception:
            self.remove_archive(path)
            raise
        return path

    @staticmethod
    def remove_archive(path: Path) -> None:
        path.unlink(missing_ok=True)


def video_content_type(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"
