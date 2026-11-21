"""Verify the build's original, independently pinned provenance and offline media."""

import hashlib
import os
import re
import stat
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field
from pydantic import ValidationError as ModelError

from reefvision.domain.errors import ValidationError
from reefvision.schemas.offline_update import (
    Digest,
    MediaFileResult,
    OfflineUpdateReport,
    OfflineUpdateRequest,
)
from reefvision.storage.backups import hash_file

# Stable WiX upgrade family shared by the original published and candidate installers.
_REEFVISION_UPGRADE = UUID("5eda8ee0-2a5d-5b08-a8df-9becfc3a4351")
_MANIFEST_LIMIT = 1024 * 1024
_CAB = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*\.cab", re.ASCII | re.IGNORECASE)


class _Identity(BaseModel):
    ProductVersion: str
    ProductCode: UUID
    UpgradeCode: UUID


class _Medium(BaseModel):
    disk_id: int = Field(gt=0)
    cabinet: str
    embedded: bool


class _Msi(BaseModel):
    identity: _Identity
    media: list[_Medium] = Field(min_length=1, max_length=256)


class _File(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)
    sha256: Digest


class _Provenance(BaseModel):
    version: Annotated[str, Field(pattern=r"^\d{1,3}\.\d{1,3}\.\d{1,5}$")]
    source_commit: Annotated[str, Field(pattern=r"^[a-fA-F0-9]{40}$")]
    source_tree_clean: Literal[True]
    msi_verified: Literal[True]
    msi: _Msi
    files: list[_File] = Field(min_length=1, max_length=257)


def _regular_file(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISREG(info.st_mode) and not (
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def _read_provenance(directory: Path, expected: str) -> tuple[_Provenance, str]:
    path = directory / "build-provenance.json"
    if not _regular_file(path):
        raise ValidationError("Choose the folder containing the original build-provenance.json.")
    with path.open("rb") as stream:
        raw = stream.read(_MANIFEST_LIMIT + 1)
    if len(raw) > _MANIFEST_LIMIT:
        raise ValidationError("The installer build provenance exceeds the supported manifest size.")
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValidationError(
            "The manifest checksum differs from the value in the candidate review."
        )
    try:
        manifest = _Provenance.model_validate_json(raw.removeprefix(b"\xef\xbb\xbf"))
    except ModelError as exc:
        raise ValidationError(
            "The manifest lacks valid, verified Windows build provenance."
        ) from exc

    identity = manifest.msi.identity
    if (
        identity.UpgradeCode != _REEFVISION_UPGRADE
        or identity.ProductCode.int == 0
        or identity.ProductVersion != manifest.version
    ):
        raise ValidationError(
            "The manifest does not identify a compatible ReefVision Windows installer."
        )
    installer = f"ReefVision_{manifest.version}_x64_en-US.msi"
    disks: set[int] = set()
    cabinets: set[str] = set()
    for medium in manifest.msi.media:
        if medium.disk_id in disks:
            raise ValidationError("The manifest repeats a Windows Installer disk number.")
        disks.add(medium.disk_id)
        if not medium.cabinet and not medium.embedded:
            continue
        if medium.embedded != medium.cabinet.startswith("#") or not _CAB.fullmatch(
            medium.cabinet.removeprefix("#")
        ):
            raise ValidationError(
                "The manifest contains an invalid Windows Installer cabinet name."
            )
        if not medium.embedded:
            name = medium.cabinet.casefold()
            if name in cabinets:
                raise ValidationError("The manifest repeats an external cabinet.")
            cabinets.add(name)
    names = [member.name.casefold() for member in manifest.files]
    if len(set(names)) != len(names) or set(names) != {installer.casefold(), *cabinets}:
        raise ValidationError(
            "The manifest file list and the Windows Installer cabinet table disagree."
        )
    return manifest, installer


def _inspect_directory(request: OfflineUpdateRequest) -> OfflineUpdateReport:
    directory = Path(request.directory)
    if not directory.is_absolute() or request.directory.replace("\\", "/").startswith("//"):
        raise ValidationError("Choose an absolute folder on a local or removable drive.")
    # A native chooser can return a junction. Resolve it before considering any file.
    directory = directory.resolve(strict=True)
    if not directory.is_dir() or str(directory).replace("\\", "/").startswith("//"):
        raise ValidationError("Select a local folder containing the Windows installation media.")
    pin = request.manifest_sha256.lower()
    manifest, installer = _read_provenance(directory, pin)
    available: dict[str, Path] = {}
    with os.scandir(directory) as children:
        for entry in children:
            if Path(entry.name).suffix.lower() not in {".msi", ".cab"}:
                continue
            key = entry.name.casefold()
            if key in available or len(available) >= 257:
                raise ValidationError(
                    "The folder contains ambiguous or too many Windows installer files."
                )
            available[key] = Path(entry.path)
    results: list[MediaFileResult] = []
    total = 0
    for member in manifest.files:
        path = available.pop(member.name.casefold(), None)
        result = MediaFileResult(name=member.name, status="missing")
        if path is not None:
            try:
                if not _regular_file(path):
                    result.status = "unreadable"
                elif path.stat().st_size != member.size_bytes:
                    result.status = "changed"
                else:
                    digest, size = hash_file(path)
                    if digest == member.sha256.lower() and size == member.size_bytes:
                        result.status = "matched"
                        total += size
                    else:
                        result.status = "changed"
            except OSError:
                result.status = "unreadable"
        results.append(result)
    results.extend(
        MediaFileResult(name=p.name, status="unexpected") for p in sorted(available.values())
    )
    return OfflineUpdateReport(
        status="verified" if all(r.status == "matched" for r in results) else "incomplete",
        version=manifest.version,
        source_commit=manifest.source_commit,
        manifest_sha256=pin,
        installer=installer,
        total_verified_bytes=total,
        files=results,
    )


def inspect_offline_update(request: OfflineUpdateRequest) -> OfflineUpdateReport:
    try:
        return _inspect_directory(request)
    except (OSError, ValueError, RuntimeError) as exc:
        raise ValidationError(
            "Open the local installer folder and check that build-provenance.json is readable."
        ) from exc
