"""Offline package installation and reading the original image selected for a measurement."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from PIL import Image, ImageStat
from pydantic import ValidationError as SchemaError

from reefvision.config import Settings
from reefvision.domain.errors import ConflictError, NotFoundError, ValidationError
from reefvision.schemas.plugins import (
    MAX_MODULE_BYTES,
    PluginManifest,
    PluginPage,
    PluginRecord,
    RGBSummary,
)
from reefvision.storage.datasets import canonical_json_bytes
from reefvision.storage.projects import filesystem_io_path, resolve_managed_project_path


class PluginStorage:
    def __init__(self, settings: Settings) -> None:
        self.root = filesystem_io_path(settings.resolved_data_dir / "plugins")
        self.staging = filesystem_io_path(settings.resolved_data_dir / ".t" / "plugins")

    def _manifest(self, record_id: UUID) -> PluginManifest:
        path = self.root / str(record_id) / "manifest.json"
        try:
            manifest = PluginManifest.model_validate_json(path.read_bytes())
        except FileNotFoundError as exc:
            raise NotFoundError(
                "Install the exact referenced plugin version in Plugins and providers."
            ) from exc
        except (OSError, SchemaError) as exc:
            raise ConflictError(
                "The installed plugin metadata is unreadable. Restore its verified backup."
            ) from exc
        if manifest.record_id != record_id:
            raise ConflictError(
                "The installed plugin manifest has an inconsistent version identity."
            )
        return manifest

    def module(self, manifest: PluginManifest) -> bytes:
        path = self.root / str(manifest.record_id) / "module.wasm"
        try:
            with path.open("rb") as source:
                data = source.read(MAX_MODULE_BYTES + 1)
        except OSError as exc:
            raise ConflictError(
                "The plugin module is unavailable. Reinstall this exact package."
            ) from exc
        if (
            len(data) > MAX_MODULE_BYTES
            or hashlib.sha256(data).hexdigest() != manifest.module_sha256
        ):
            raise ConflictError("The plugin module checksum differs. Reinstall this exact package.")
        return data

    def record(self, record_id: UUID) -> PluginRecord:
        manifest = self._manifest(record_id)
        reason = None
        try:
            self.module(manifest)
        except ConflictError as exc:
            reason = str(exc)
        return PluginRecord(
            id=record_id,
            manifest=manifest,
            package_sha256=manifest.package_sha256,
            enabled=(self.root / str(record_id) / "enabled").is_file(),
            available=reason is None,
            reason=reason,
        )

    def page(self, *, limit: int, offset: int) -> PluginPage:
        records = []
        for entry in self.root.iterdir() if self.root.is_dir() else ():
            try:
                record_id = UUID(entry.name)
            except ValueError:
                continue
            try:
                records.append(self.record(record_id))
            except (NotFoundError, ConflictError):
                # A damaged manifest is retained for recovery without blocking other packages.
                continue
        records.sort(
            key=lambda v: (
                v.manifest.display_name.casefold(),
                v.manifest.plugin_id,
                tuple(map(int, v.manifest.version.split("."))),
            )
        )
        return PluginPage(items=records[offset : offset + limit], total=len(records))

    def install(self, manifest: PluginManifest, module: bytes) -> PluginRecord:
        self.root.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(parents=True, exist_ok=True)
        target = self.root / str(manifest.record_id)
        with TemporaryDirectory(dir=self.staging) as temporary:
            # Publish a complete non-empty directory with a single same-volume rename. An existing
            # version is immutable, including when two application processes install concurrently.
            staged = Path(temporary) / "package"
            staged.mkdir()
            (staged / "manifest.json").write_bytes(
                canonical_json_bytes(manifest.model_dump(mode="json"))
            )
            (staged / "module.wasm").write_bytes(module)
            try:
                staged.rename(target)
            except OSError:
                if not target.is_dir():
                    raise
                existing = self._manifest(manifest.record_id)
                if existing.package_sha256 != manifest.package_sha256:
                    raise ConflictError(
                        "A different package already uses this plugin ID and version. "
                        "Choose a new version."
                    ) from None
                try:
                    self.module(existing)
                except ConflictError:
                    # The original manifest authenticates these replacement bytes.
                    os.replace(staged / "module.wasm", target / "module.wasm")
        return self.record(manifest.record_id)

    def set_enabled(self, record_id: UUID, digest: str, enabled: bool) -> PluginRecord:
        record = self.record(record_id)
        if record.package_sha256 != digest:
            raise ConflictError("The installed package differs from the selected plugin pin.")
        if enabled and not record.available:
            raise ConflictError(record.reason or "The plugin is unavailable.")
        marker = self.root / str(record_id) / "enabled"
        if enabled:
            marker.touch(exist_ok=True)
        else:
            marker.unlink(missing_ok=True)
        return self.record(record_id)

    def enabled_module(self, record_id: UUID, digest: str) -> tuple[PluginManifest, bytes]:
        manifest = self._manifest(record_id)
        if manifest.package_sha256 != digest:
            raise ConflictError("The installed package differs from the saved plugin pin.")
        if not (self.root / str(record_id) / "enabled").is_file():
            raise ConflictError(
                "Enable the pinned plugin version in Plugins and providers before running."
            )
        return manifest, self.module(manifest)


def original_rgb_summary(settings: Settings, managed_path: str, expected_sha256: str) -> RGBSummary:
    path = filesystem_io_path(resolve_managed_project_path(settings, managed_path))
    try:
        with path.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != expected_sha256:
                raise ConflictError("The original image bytes differ from the saved pin.")
            source.seek(0)
            with Image.open(source) as image:
                if image.mode not in {"RGB", "RGBA", "L", "LA", "P"}:
                    raise ValidationError(
                        "This plugin ABI accepts 8-bit RGB, grayscale or palette images."
                    )
                rgb = image.convert("RGB")
                try:
                    red, green, blue = ImageStat.Stat(rgb).mean
                finally:
                    rgb.close()
                return RGBSummary(
                    red_mean=red,
                    green_mean=green,
                    blue_mean=blue,
                    pixel_count=image.width * image.height,
                )
    except OSError as exc:
        raise ConflictError(
            "The original image is unavailable for the pinned plugin measurement."
        ) from exc
