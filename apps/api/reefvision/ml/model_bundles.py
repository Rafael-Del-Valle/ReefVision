"""Safe extraction and inspection helpers for managed multi-file model bundles."""

from __future__ import annotations

import json
import os
import shutil
import zipfile
from pathlib import Path
from uuid import uuid4

from reefvision.domain.errors import ValidationError

MAX_BUNDLE_MEMBERS = 4096
MAX_BUNDLE_UNCOMPRESSED_BYTES = 20 * 1024 * 1024 * 1024


def _validated_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    if not members:
        raise ValidationError("The model bundle is empty")
    if len(members) > MAX_BUNDLE_MEMBERS:
        raise ValidationError("The model bundle contains too many files")
    total_size = 0
    for member in members:
        path = Path(member.filename.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise ValidationError("The model bundle contains an unsafe path")
        if member.is_dir():
            continue
        total_size += member.file_size
        if total_size > MAX_BUNDLE_UNCOMPRESSED_BYTES:
            raise ValidationError("The model bundle expands beyond the supported size limit")
    return members


def inspect_transformers_bundle(bundle_path: Path) -> tuple[dict[str, object], str | None]:
    """Validate a Transformers-style zip and return config plus its optional root prefix."""

    if bundle_path.suffix.lower() != ".zip" or not bundle_path.is_file():
        raise ValidationError("Transformers model providers require a managed .zip model bundle")
    try:
        with zipfile.ZipFile(bundle_path) as archive:
            members = _validated_members(archive)
            files = {
                member.filename.replace("\\", "/") for member in members if not member.is_dir()
            }
            roots: list[str | None] = [None]
            roots.extend(
                sorted(
                    {
                        name.split("/", 1)[0]
                        for name in files
                        if "/" in name and name.split("/", 1)[0]
                    }
                )
            )
            config_name: str | None = None
            selected_root: str | None = None
            for root in roots:
                candidate = "config.json" if root is None else f"{root}/config.json"
                if candidate in files:
                    config_name = candidate
                    selected_root = root
                    break
            if config_name is None:
                raise ValidationError("The model bundle is missing config.json")
            processor_name = (
                "preprocessor_config.json"
                if selected_root is None
                else f"{selected_root}/preprocessor_config.json"
            )
            if processor_name not in files:
                raise ValidationError("The model bundle is missing preprocessor_config.json")
            weight_candidates = [
                name
                for name in files
                if (selected_root is None or name.startswith(f"{selected_root}/"))
                and Path(name).suffix.lower() in {".safetensors", ".bin"}
            ]
            if not weight_candidates:
                raise ValidationError(
                    "The model bundle is missing Transformers model weights (.safetensors or .bin)"
                )
            with archive.open(config_name) as source:
                raw = json.load(source)
            if not isinstance(raw, dict):
                raise ValidationError("The model bundle config.json must contain an object")
            return raw, selected_root
    except zipfile.BadZipFile as exc:
        raise ValidationError("The model bundle is not a valid ZIP archive") from exc


def extracted_transformers_bundle(bundle_path: Path) -> Path:
    """Extract a validated immutable bundle beside the managed archive and reuse it."""

    _, root_prefix = inspect_transformers_bundle(bundle_path)
    extraction_root = bundle_path.parent / f".{bundle_path.stem}.bundle"
    marker = extraction_root / ".reefvision-ready"
    if marker.is_file():
        model_root = extraction_root if root_prefix is None else extraction_root / root_prefix
        if (model_root / "config.json").is_file():
            return model_root

    temporary = bundle_path.parent / f".{bundle_path.stem}.bundle-{uuid4().hex}.part"
    shutil.rmtree(temporary, ignore_errors=True)
    try:
        temporary.mkdir(parents=True, exist_ok=False)
        with zipfile.ZipFile(bundle_path) as archive:
            members = _validated_members(archive)
            root_resolved = temporary.resolve()
            for member in members:
                destination = (temporary / member.filename.replace("\\", "/")).resolve()
                try:
                    destination.relative_to(root_resolved)
                except ValueError as exc:
                    raise ValidationError("The model bundle contains an unsafe path") from exc
                if member.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
        (temporary / ".reefvision-ready").write_text("ready\n", encoding="utf-8")
        if extraction_root.exists():
            shutil.rmtree(extraction_root)
        os.replace(temporary, extraction_root)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    model_root = extraction_root if root_prefix is None else extraction_root / root_prefix
    if not (model_root / "config.json").is_file():
        shutil.rmtree(extraction_root, ignore_errors=True)
        raise ValidationError("The extracted model bundle is incomplete")
    return model_root
