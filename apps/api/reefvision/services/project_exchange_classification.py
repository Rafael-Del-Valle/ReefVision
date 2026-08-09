"""Restore remapped classification dataset materializations from project exchange media."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from uuid import uuid4

from reefvision.domain.errors import ValidationError
from reefvision.storage.datasets import canonical_json_sha256

MAX_CLASSIFICATION_ARCHIVE_MEMBERS = 100_000
MAX_CLASSIFICATION_ARCHIVE_UNCOMPRESSED_BYTES = 100 * 1024**3
MANIFEST_FILENAME = "reefvision-classification-manifest.json"


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name.replace("\\", "/"))
    return bool(name) and not path.is_absolute() and ".." not in path.parts


def restore_classification_dataset_materialization(
    *,
    archive_path: Path,
    output_path: Path,
    manifest_json: dict[str, object],
    manifest_sha256: str,
    sample_count: int,
) -> None:
    """Safely rebuild an imported classification dataset around remapped identifiers.

    The packaged archive is first treated as an untrusted transport container. Sample files are
    extracted into a temporary directory, the internal manifest is replaced by the already-
    remapped database manifest, and a new ZIP is created from that reconstructed directory.
    """

    if canonical_json_sha256(manifest_json) != manifest_sha256:
        raise ValidationError("Imported classification dataset manifest checksum is inconsistent")
    samples = manifest_json.get("samples")
    if not isinstance(samples, list) or len(samples) != sample_count:
        raise ValidationError("Imported classification dataset sample count is inconsistent")

    temporary_output = output_path.parent / f".{output_path.name}-{uuid4().hex}.part"
    temporary_archive = archive_path.with_suffix(archive_path.suffix + ".rebuild.part")
    shutil.rmtree(temporary_output, ignore_errors=True)
    temporary_archive.unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(archive_path, "r") as source:
            infos = source.infolist()
            if len(infos) > MAX_CLASSIFICATION_ARCHIVE_MEMBERS:
                raise ValidationError("Classification dataset archive contains too many files")
            if (
                sum(item.file_size for item in infos)
                > MAX_CLASSIFICATION_ARCHIVE_UNCOMPRESSED_BYTES
            ):
                raise ValidationError(
                    "Classification dataset archive expands beyond the supported size limit"
                )
            if any(not _safe_member(item.filename) for item in infos):
                raise ValidationError("Classification dataset archive contains unsafe paths")

            root = temporary_output.resolve()
            temporary_output.mkdir(parents=True, exist_ok=False)
            for info in infos:
                if info.is_dir() or info.filename == MANIFEST_FILENAME:
                    continue
                destination = (temporary_output / info.filename.replace("\\", "/")).resolve()
                try:
                    destination.relative_to(root)
                except ValueError as exc:
                    raise ValidationError(
                        "Classification dataset archive contains an unsafe extraction path"
                    ) from exc
                destination.parent.mkdir(parents=True, exist_ok=True)
                with source.open(info) as input_stream, destination.open("wb") as output:
                    shutil.copyfileobj(input_stream, output, length=1024 * 1024)

        for raw_sample in samples:
            if not isinstance(raw_sample, dict):
                raise ValidationError("Classification dataset sample manifest is invalid")
            relative_sample = str(raw_sample.get("sample_path") or "")
            if not _safe_member(relative_sample):
                raise ValidationError("Classification dataset sample path is unsafe")
            sample_path = (temporary_output / relative_sample).resolve()
            try:
                sample_path.relative_to(temporary_output.resolve())
            except ValueError as exc:
                raise ValidationError("Classification dataset sample path escapes its root") from exc
            if not sample_path.is_file():
                raise ValidationError(
                    f"Classification dataset archive is missing sample: {relative_sample}"
                )

        manifest_path = temporary_output / MANIFEST_FILENAME
        manifest_path.write_text(
            json.dumps(manifest_json, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(
            temporary_archive,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as rebuilt:
            for path in sorted(temporary_output.rglob("*")):
                if path.is_file():
                    rebuilt.write(path, path.relative_to(temporary_output).as_posix())

        shutil.rmtree(output_path, ignore_errors=True)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_output.replace(output_path)
        temporary_archive.replace(archive_path)
    except Exception:
        shutil.rmtree(temporary_output, ignore_errors=True)
        temporary_archive.unlink(missing_ok=True)
        raise
