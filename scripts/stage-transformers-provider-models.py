#!/usr/bin/env python3
"""Download and stage the six official Transformers vision model repositories."""

from __future__ import annotations

import argparse
import errno
import fnmatch
import hashlib
import json
import os
import shutil
from pathlib import Path, PurePosixPath
from typing import Any

_IGNORE_PATTERNS = ("*.md", ".gitattributes")
_DOWNLOAD_STATE_NAME = ".reefvision-download-state.json"
_SNAPSHOT_MARKER_NAME = ".reefvision-snapshot.json"
_GIB = 1024**3


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected a JSON object in {path}")
    return payload


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _safe_catalog_segments(catalog_id: str) -> list[str]:
    segments = catalog_id.split("/")
    if not segments or any(
        not segment
        or segment in {".", ".."}
        or Path(segment).name != segment
        for segment in segments
    ):
        raise RuntimeError(f"Unsafe catalog id: {catalog_id!r}")
    return segments


def _safe_relative_parts(value: str) -> tuple[str, ...]:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise RuntimeError(f"Unsafe model repository path: {value!r}")
    return path.parts


def _ignored_path(relative_path: str) -> bool:
    return any(fnmatch.fnmatch(relative_path, pattern) for pattern in _IGNORE_PATTERNS)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_files(root: Path) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative.startswith(".cache/") or relative in {
            _DOWNLOAD_STATE_NAME,
            _SNAPSHOT_MARKER_NAME,
        }:
            continue
        if relative.startswith("../") or relative in {"", ".", ".."}:
            raise RuntimeError(f"Unsafe model snapshot path: {relative!r}")
        files.append(
            {
                "relative_path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    if not files:
        raise RuntimeError(f"Model snapshot is empty: {root}")
    return files


def _snapshot_sha256(files: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in files:
        digest.update(str(record["relative_path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(int(record["size_bytes"])).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(record["sha256"]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _immutable_revision(value: object, *, repo_id: str) -> str:
    revision = str(value or "").strip().casefold()
    if len(revision) != 40 or any(
        character not in "0123456789abcdef" for character in revision
    ):
        raise RuntimeError(
            f"Hugging Face did not resolve {repo_id} to an immutable 40-character commit"
        )
    return revision


def _format_bytes(value: int) -> str:
    amount = float(max(value, 0))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{amount:.2f} {unit}"
        amount /= 1024
    return f"{amount:.2f} TiB"


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _remote_files(info: object, *, repo_id: str) -> list[dict[str, Any]]:
    siblings = getattr(info, "siblings", None)
    if not siblings:
        raise RuntimeError(f"Hugging Face returned no repository files for {repo_id}")
    files: list[dict[str, Any]] = []
    for sibling in siblings:
        relative_path = str(getattr(sibling, "rfilename", "") or "").strip()
        if not relative_path or _ignored_path(relative_path):
            continue
        _safe_relative_parts(relative_path)
        raw_size = getattr(sibling, "size", None)
        size_bytes = int(raw_size) if raw_size is not None else None
        if size_bytes is not None and size_bytes < 0:
            raise RuntimeError(
                f"Hugging Face returned an invalid size for {repo_id}/{relative_path}"
            )
        files.append({"relative_path": relative_path, "size_bytes": size_bytes})
    if not files:
        raise RuntimeError(f"No packageable files remain for {repo_id}")
    return files


def _known_remote_size(files: list[dict[str, Any]]) -> int:
    return sum(
        int(record["size_bytes"])
        for record in files
        if record["size_bytes"] is not None
    )


def _snapshot_matches_remote(destination: Path, remote_files: list[dict[str, Any]]) -> bool:
    if not destination.is_dir() or not (destination / "config.json").is_file():
        return False
    try:
        local_records = _snapshot_files(destination)
    except (OSError, RuntimeError):
        return False
    expected_paths = {str(record["relative_path"]) for record in remote_files}
    local_paths = {str(record["relative_path"]) for record in local_records}
    if local_paths != expected_paths:
        return False
    for record in remote_files:
        target = destination.joinpath(
            *_safe_relative_parts(str(record["relative_path"]))
        )
        if not target.is_file():
            return False
        expected_size = record["size_bytes"]
        if expected_size is not None and target.stat().st_size != int(expected_size):
            return False
    return True


def _download_state_matches(path: Path, *, repo_id: str, revision: str) -> bool:
    state_path = path / _DOWNLOAD_STATE_NAME
    if not state_path.is_file():
        return False
    try:
        state = _load_object(state_path)
    except (OSError, json.JSONDecodeError, RuntimeError):
        return False
    return state.get("repo_id") == repo_id and state.get("resolved_revision") == revision


def _record_for_snapshot(
    *,
    catalog_id: str,
    repo_id: str,
    requested_revision: str,
    resolved_revision: str,
    provider_id: str,
    destination: Path,
    output_root: Path,
) -> dict[str, Any]:
    files = _snapshot_files(destination)
    snapshot_digest = _snapshot_sha256(files)
    record = {
        "catalog_id": catalog_id,
        "repo_id": repo_id,
        "requested_revision": requested_revision,
        "resolved_revision": resolved_revision,
        "provider_id": provider_id,
        "relative_path": destination.relative_to(output_root).as_posix(),
        "file_count": len(files),
        "total_size_bytes": sum(int(item["size_bytes"]) for item in files),
        "snapshot_sha256": snapshot_digest,
        "files": files,
    }
    _write_json_atomic(
        destination / _SNAPSHOT_MARKER_NAME,
        {
            "schema": "reefvision-transformers-snapshot-v1",
            "catalog_id": catalog_id,
            "repo_id": repo_id,
            "resolved_revision": resolved_revision,
            "snapshot_sha256": snapshot_digest,
        },
    )
    return record


def _write_manifest(
    *,
    output_root: Path,
    pack_id: str,
    records: dict[str, Any],
) -> dict[str, Any]:
    manifest = {
        "manifest_version": 2,
        "pack_id": pack_id,
        "model_count": len(records),
        "models": records,
        "total_size_bytes": sum(
            int(item["total_size_bytes"]) for item in records.values()
        ),
    }
    _write_json_atomic(output_root / "manifest.json", manifest)
    return manifest


def _assert_download_space(
    *,
    output_root: Path,
    temporary: Path,
    repo_id: str,
    remote_files: list[dict[str, Any]],
    reserve_bytes: int,
) -> None:
    known_remote_bytes = _known_remote_size(remote_files)
    partial_bytes = min(_directory_size(temporary), known_remote_bytes)
    remaining_bytes = max(known_remote_bytes - partial_bytes, 0)
    free_bytes = shutil.disk_usage(output_root).free
    required_bytes = remaining_bytes + reserve_bytes
    print(
        f"Disk preflight for {repo_id}: free {_format_bytes(free_bytes)}, "
        f"estimated remaining download {_format_bytes(remaining_bytes)}, "
        f"required post-download reserve {_format_bytes(reserve_bytes)}."
    )
    if free_bytes < required_bytes:
        raise RuntimeError(
            f"Insufficient disk space for {repo_id}. Free space is "
            f"{_format_bytes(free_bytes)}; this stage needs approximately "
            f"{_format_bytes(remaining_bytes)} more for the snapshot plus "
            f"{_format_bytes(reserve_bytes)} reserved for PyInstaller and MSI work. "
            f"Free at least {_format_bytes(required_bytes - free_bytes)} more and rerun. "
            f"The resumable partial snapshot remains at {temporary}."
        )


def stage_model_pack(
    policy_path: Path,
    output_root: Path,
    *,
    reserve_free_gib: float,
) -> dict[str, Any]:
    try:
        from huggingface_hub import model_info, snapshot_download
    except Exception as exc:
        raise RuntimeError(
            "huggingface-hub is required to stage the Transformers provider pack"
        ) from exc

    if reserve_free_gib < 0:
        raise RuntimeError("reserve_free_gib cannot be negative")
    reserve_bytes = int(reserve_free_gib * _GIB)
    policy = _load_object(policy_path)
    raw_models = policy.get("models")
    if not isinstance(raw_models, list) or len(raw_models) != 6:
        raise RuntimeError("Transformers model pack must declare exactly six models")
    output_root.mkdir(parents=True, exist_ok=True)
    records: dict[str, Any] = {}
    pack_id = str(policy.get("pack_id") or "transformers-vision")

    for raw_model in raw_models:
        if not isinstance(raw_model, dict):
            raise RuntimeError("Transformers model pack contains a non-object entry")
        catalog_id = str(raw_model.get("catalog_id") or "").strip()
        repo_id = str(raw_model.get("repo_id") or "").strip()
        revision = str(raw_model.get("revision") or "").strip()
        provider_id = str(raw_model.get("provider_id") or "").strip()
        if not catalog_id or not repo_id or not revision or not provider_id:
            raise RuntimeError("Transformers model pack entry is incomplete")
        destination = output_root.joinpath(*_safe_catalog_segments(catalog_id))
        info = model_info(repo_id, revision=revision, files_metadata=True)
        resolved_revision = _immutable_revision(info.sha, repo_id=repo_id)
        remote_files = _remote_files(info, repo_id=repo_id)

        if _snapshot_matches_remote(destination, remote_files):
            print(
                f"Reusing verified snapshot {catalog_id} from "
                f"{repo_id}@{resolved_revision}"
            )
            records[catalog_id] = _record_for_snapshot(
                catalog_id=catalog_id,
                repo_id=repo_id,
                requested_revision=revision,
                resolved_revision=resolved_revision,
                provider_id=provider_id,
                destination=destination,
                output_root=output_root,
            )
            _write_manifest(output_root=output_root, pack_id=pack_id, records=records)
            continue

        print(f"Staging {catalog_id} from {repo_id}@{resolved_revision}")
        temporary = destination.with_name(destination.name + ".part")
        if temporary.exists() and not _download_state_matches(
            temporary,
            repo_id=repo_id,
            revision=resolved_revision,
        ):
            print(f"Discarding stale partial snapshot at {temporary}")
            shutil.rmtree(temporary)
        temporary.mkdir(parents=True, exist_ok=True)
        _write_json_atomic(
            temporary / _DOWNLOAD_STATE_NAME,
            {"repo_id": repo_id, "resolved_revision": resolved_revision},
        )
        _assert_download_space(
            output_root=output_root,
            temporary=temporary,
            repo_id=repo_id,
            remote_files=remote_files,
            reserve_bytes=reserve_bytes,
        )

        try:
            snapshot_path = Path(
                snapshot_download(
                    repo_id=repo_id,
                    revision=resolved_revision,
                    local_dir=temporary,
                    ignore_patterns=_IGNORE_PATTERNS,
                    max_workers=1,
                )
            )
        except OSError as exc:
            if exc.errno != errno.ENOSPC:
                print(f"Preserving resumable partial snapshot at {temporary}")
                raise
            removed_bytes = _directory_size(temporary)
            shutil.rmtree(temporary, ignore_errors=True)
            free_after_cleanup = shutil.disk_usage(output_root).free
            raise RuntimeError(
                "The drive ran out of space while downloading "
                f"{repo_id}. ReefVision removed {_format_bytes(removed_bytes)} of "
                f"failed partial data; free space is now "
                f"{_format_bytes(free_after_cleanup)}. Free additional disk space "
                "before rerunning the package build. Completed model snapshots were preserved."
            ) from exc
        except Exception:
            print(f"Preserving resumable partial snapshot at {temporary}")
            raise

        if snapshot_path.resolve() != temporary.resolve():
            raise RuntimeError("Hugging Face staging escaped the managed temporary directory")
        shutil.rmtree(snapshot_path / ".cache", ignore_errors=True)
        (snapshot_path / _DOWNLOAD_STATE_NAME).unlink(missing_ok=True)
        if not (snapshot_path / "config.json").is_file():
            raise RuntimeError(f"Snapshot {repo_id} does not contain config.json")
        if not _snapshot_matches_remote(snapshot_path, remote_files):
            raise RuntimeError(
                f"Snapshot {repo_id} did not match the resolved repository files"
            )
        if destination.exists():
            shutil.rmtree(destination)
        os.replace(temporary, destination)
        records[catalog_id] = _record_for_snapshot(
            catalog_id=catalog_id,
            repo_id=repo_id,
            requested_revision=revision,
            resolved_revision=resolved_revision,
            provider_id=provider_id,
            destination=destination,
            output_root=output_root,
        )
        _write_manifest(output_root=output_root, pack_id=pack_id, records=records)

    manifest = _write_manifest(output_root=output_root, pack_id=pack_id, records=records)
    print(
        f"Staged {manifest['model_count']} Transformers models "
        f"({manifest['total_size_bytes'] / _GIB:.2f} GiB)."
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--reserve-free-gib",
        type=float,
        default=30.0,
        help=(
            "Free space to preserve after each remaining model download for "
            "PyInstaller, Tauri resources, WiX cabinets, and MSI output."
        ),
    )
    args = parser.parse_args()
    stage_model_pack(
        args.policy.resolve(),
        args.output.resolve(),
        reserve_free_gib=args.reserve_free_gib,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Transformers model-pack staging failed: {exc}")
        raise
