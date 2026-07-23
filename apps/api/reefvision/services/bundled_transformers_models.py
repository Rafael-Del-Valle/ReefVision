"""Install and verify bundled Transformers model snapshots in configurable cache storage."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from reefvision.config import Settings

_MARKER_FILENAME = ".reefvision-revision"
_SUPPORTED_MANIFEST_VERSIONS = {1, 2}


def _bundle_roots() -> list[Path]:
    candidates: list[Path] = []
    configured = os.environ.get("REEFVISION_BUNDLED_TRANSFORMERS_MODELS_DIR")
    if configured and not configured.isspace():
        candidates.append(Path(configured).expanduser())
    bundle_root = vars(sys).get("_MEIPASS")
    if bundle_root:
        candidates.append(Path(str(bundle_root)).resolve() / "bundled-transformers-models")
    executable = getattr(sys, "executable", None)
    if executable:
        root = Path(executable).resolve().parent
        candidates.extend(
            [
                root / "bundled-transformers-models",
                root / "_internal" / "bundled-transformers-models",
                root.parent / "bundled-transformers-models",
                root.parent.parent / "bundled-transformers-models",
            ]
        )
    candidates.append(
        Path(__file__).resolve().parents[4]
        / ".desktop"
        / "bundled-transformers-models"
    )
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(candidate.resolve(strict=False)).casefold()
        if normalized not in seen:
            seen.add(normalized)
            unique.append(candidate)
    return unique


def _load_manifest() -> tuple[Path, dict[str, Any]] | None:
    for root in _bundle_roots():
        path = root / "manifest.json"
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            payload.get("manifest_version") in _SUPPORTED_MANIFEST_VERSIONS
            and isinstance(payload.get("models"), dict)
        ):
            return root.resolve(), payload
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_relative_file(root: Path, relative_path: str) -> Path:
    relative = Path(relative_path)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValueError(f"Unsafe snapshot path: {relative_path!r}")
    candidate = (root / relative).resolve()
    candidate.relative_to(root.resolve())
    return candidate


def _snapshot_digest(files: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in sorted(files, key=lambda item: str(item["relative_path"])):
        digest.update(str(record["relative_path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(int(record["size_bytes"])).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(record["sha256"]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _validate_file_records(
    raw_record: dict[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    raw_files = raw_record.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ValueError("Bundled model manifest has no file records")
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_file in raw_files:
        if not isinstance(raw_file, dict):
            raise ValueError("Bundled model manifest contains a non-object file record")
        relative_path = str(raw_file.get("relative_path") or "")
        size_bytes = int(raw_file.get("size_bytes") or -1)
        sha256 = str(raw_file.get("sha256") or "").casefold()
        if relative_path in seen:
            raise ValueError(f"Duplicate bundled model file: {relative_path}")
        if (
            size_bytes < 0
            or len(sha256) != 64
            or any(character not in "0123456789abcdef" for character in sha256)
        ):
            raise ValueError(f"Invalid bundled model metadata: {relative_path}")
        seen.add(relative_path)
        files.append(
            {
                "relative_path": relative_path,
                "size_bytes": size_bytes,
                "sha256": sha256,
            }
        )
    expected_digest = str(raw_record.get("snapshot_sha256") or "").casefold()
    calculated_digest = _snapshot_digest(files)
    if expected_digest and expected_digest != calculated_digest:
        raise ValueError("Bundled model snapshot digest does not match its file manifest")
    return files, calculated_digest


def _verify_snapshot(
    root: Path,
    raw_record: dict[str, Any],
    *,
    allow_marker: bool,
) -> tuple[bool, str, str]:
    try:
        files, snapshot_digest = _validate_file_records(raw_record)
        expected_paths = {str(item["relative_path"]) for item in files}
        actual_paths = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and (allow_marker or path.name != _MARKER_FILENAME)
        }
        if not allow_marker:
            actual_paths.discard(_MARKER_FILENAME)
        unexpected = actual_paths - expected_paths
        missing = expected_paths - actual_paths
        if unexpected:
            details = ", ".join(sorted(unexpected)[:5])
            return False, f"Unexpected bundled files: {details}", snapshot_digest
        if missing:
            details = ", ".join(sorted(missing)[:5])
            return False, f"Missing bundled files: {details}", snapshot_digest
        for item in files:
            path = _safe_relative_file(root, str(item["relative_path"]))
            relative_path = str(item["relative_path"])
            if not path.is_file():
                return False, f"Missing bundled file: {relative_path}", snapshot_digest
            if path.stat().st_size != int(item["size_bytes"]):
                return False, f"Bundled file size mismatch: {relative_path}", snapshot_digest
            if _sha256(path) != str(item["sha256"]):
                return (
                    False,
                    f"Bundled file checksum mismatch: {relative_path}",
                    snapshot_digest,
                )
        if not (root / "config.json").is_file():
            return False, "Bundled model has no config.json", snapshot_digest
        return True, "verified", snapshot_digest
    except (OSError, TypeError, ValueError) as exc:
        return False, str(exc), ""


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _destination_root(settings: Settings) -> Path:
    return (
        settings.resolved_model_cache_dir
        / "models"
        / "provider-packs"
        / "transformers-vision"
    )


def install_bundled_transformers_models(
    settings: Settings,
) -> tuple[dict[str, Path], list[str]]:
    loaded = _load_manifest()
    if loaded is None:
        return {}, []
    bundle_root, manifest = loaded
    destination_root = _destination_root(settings)
    destination_root.mkdir(parents=True, exist_ok=True)
    installed: dict[str, Path] = {}
    index_models: dict[str, Any] = {}
    warnings: list[str] = []
    for catalog_id, raw_record in manifest["models"].items():
        if not isinstance(raw_record, dict):
            warnings.append(f"Invalid bundled Transformers record: {catalog_id}")
            continue
        relative_path = str(raw_record.get("relative_path") or "")
        try:
            source = _safe_relative_file(bundle_root, relative_path)
        except ValueError:
            warnings.append(
                f"Bundled Transformers path escapes resource root: {catalog_id}"
            )
            continue
        if not source.is_dir():
            warnings.append(
                f"Bundled Transformers model directory is missing: {catalog_id}"
            )
            continue
        source_valid, source_reason, snapshot_digest = _verify_snapshot(
            source,
            raw_record,
            allow_marker=False,
        )
        if not source_valid:
            warnings.append(
                "Bundled Transformers model failed verification "
                f"({catalog_id}): {source_reason}"
            )
            continue

        destination = destination_root.joinpath(*str(catalog_id).split("/"))
        marker = destination / _MARKER_FILENAME
        revision = str(raw_record.get("resolved_revision") or "")
        destination_valid = False
        if destination.is_dir() and marker.is_file():
            try:
                marker_matches = marker.read_text(encoding="utf-8").strip() == revision
            except OSError:
                marker_matches = False
            if marker_matches:
                destination_valid, _, destination_digest = _verify_snapshot(
                    destination,
                    raw_record,
                    allow_marker=False,
                )
                destination_valid = (
                    destination_valid and destination_digest == snapshot_digest
                )
        if not destination_valid:
            temporary = destination.with_name(destination.name + ".bundled.part")
            if temporary.exists():
                shutil.rmtree(temporary)
            temporary.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, temporary)
            copied_valid, copied_reason, copied_digest = _verify_snapshot(
                temporary,
                raw_record,
                allow_marker=False,
            )
            if not copied_valid or copied_digest != snapshot_digest:
                shutil.rmtree(temporary, ignore_errors=True)
                warnings.append(
                    "Copied Transformers model failed verification "
                    f"({catalog_id}): {copied_reason}"
                )
                continue
            (temporary / _MARKER_FILENAME).write_text(
                revision + "\n",
                encoding="utf-8",
            )
            if destination.exists():
                shutil.rmtree(destination)
            os.replace(temporary, destination)

        installed[str(catalog_id)] = destination
        index_models[str(catalog_id)] = {
            "path": str(destination),
            "provider_id": raw_record.get("provider_id"),
            "repo_id": raw_record.get("repo_id"),
            "resolved_revision": revision,
            "snapshot_sha256": snapshot_digest,
            "file_count": int(
                raw_record.get("file_count") or len(raw_record.get("files") or [])
            ),
            "total_size_bytes": int(raw_record.get("total_size_bytes") or 0),
            "verified": True,
        }

    _write_json_atomic(
        destination_root / "manifest.json",
        {
            "manifest_version": 2,
            "pack_id": manifest.get("pack_id"),
            "models": index_models,
        },
    )
    return installed, warnings


def bundled_transformers_model_record(
    settings: Settings,
    catalog_id: str,
) -> dict[str, Any] | None:
    index = _destination_root(settings) / "manifest.json"
    if not index.is_file():
        return None
    try:
        payload = json.loads(index.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    models = payload.get("models")
    if not isinstance(models, dict):
        return None
    record = models.get(catalog_id)
    if not isinstance(record, dict) or record.get("verified") is not True:
        return None
    path = Path(str(record.get("path") or "")).resolve()
    if not path.is_dir() or not (path / "config.json").is_file():
        return None
    marker = path / _MARKER_FILENAME
    try:
        marker_revision = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if marker_revision != str(record.get("resolved_revision") or ""):
        return None
    return {**record, "path": path}


def bundled_transformers_model_path(
    settings: Settings,
    catalog_id: str,
) -> Path | None:
    record = bundled_transformers_model_record(settings, catalog_id)
    return Path(record["path"]) if record is not None else None
