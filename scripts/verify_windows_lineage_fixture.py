"""Verify one disposable Windows lineage profile without mutating it."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = "reefvision-windows-lineage-fixtures-1"
_PROFILE_REVISIONS = {
    "validated-1.3": "b13_temporal_0001",
    "draft-1.4-0038": "0038",
    "draft-1.4-0039": "0039",
}
_KINDS = {
    "scientific_record": ("scientific_records", "content_sha256"),
    "spatial_source_asset": ("spatial_source_assets", "sha256"),
    "spatial_calibration_review": ("spatial_calibration_reviews", "evidence_sha256"),
}


class VerificationError(ValueError):
    """The fixture cannot safely or reproducibly be used for acceptance."""


def _require_dict(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise VerificationError(f"{label} must be an object")
    return value


def _require_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise VerificationError(f"{label} must be an array")
    return value


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise VerificationError(f"{label} must be a nonempty string")
    return value


def _contained_file(root: Path, relative: object, label: str) -> Path:
    raw = _require_string(relative, label)
    candidate_path = Path(raw)
    if candidate_path.is_absolute():
        raise VerificationError(f"{label} escapes fixture root")
    candidate = (root / candidate_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise VerificationError(f"{label} escapes fixture root") from exc
    if not candidate.is_file():
        raise VerificationError(f"{label} is missing or is not a file")
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _expect_hash(path: Path, expected: object, label: str) -> None:
    digest = _require_string(expected, f"{label} SHA-256")
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise VerificationError(f"{label} SHA-256 is not a lowercase hexadecimal digest")
    if _sha256(path) != digest:
        raise VerificationError(f"{label} SHA-256 mismatch")


def _read_one(
    connection: sqlite3.Connection, query: str, values: tuple[object, ...]
) -> tuple[Any, ...]:
    rows = connection.execute(query, values).fetchall()
    if len(rows) != 1:
        raise VerificationError("seeded record is missing or duplicated")
    return tuple(rows[0])


def _verify_records(
    connection: sqlite3.Connection, profile: dict[str, Any], project_id: str
) -> list[str]:
    records = _require_list(profile.get("records"), "records")
    record_ids: list[str] = []
    for raw_record in records:
        record = _require_dict(raw_record, "record")
        kind = _require_string(record.get("kind"), "record kind")
        identifier = _require_string(record.get("id"), "record id")
        expected_hash = _require_string(record.get("sha256"), "record SHA-256")
        try:
            table, digest_column = _KINDS[kind]
        except KeyError as exc:
            raise VerificationError(f"unsupported seeded record kind: {kind}") from exc
        row = _read_one(
            connection,
            f"SELECT project_id, {digest_column} FROM {table} WHERE id = ?",
            (identifier,),
        )
        if row != (project_id, expected_hash):
            raise VerificationError(f"seeded {kind} evidence does not match manifest")
        record_ids.append(identifier)
    if not record_ids:
        raise VerificationError("profile must declare at least one seeded record")
    return record_ids


def verify(manifest_path: Path, profile_name: str) -> dict[str, object]:
    manifest_file = manifest_path.resolve()
    root = manifest_file.parent.resolve()
    try:
        manifest = _require_dict(json.loads(manifest_file.read_text(encoding="utf-8")), "manifest")
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError(f"could not read fixture manifest: {exc}") from exc
    if manifest.get("schema_version") != _SCHEMA_VERSION:
        raise VerificationError("unsupported fixture manifest schema version")
    if manifest.get("fixture_kind") != "synthetic_engineering":
        raise VerificationError("fixture kind must be synthetic_engineering")
    profiles = [
        _require_dict(item, "profile")
        for item in _require_list(manifest.get("profiles"), "profiles")
    ]
    matches = [profile for profile in profiles if profile.get("name") == profile_name]
    if len(matches) != 1:
        raise VerificationError("requested profile is missing or duplicated")
    profile = matches[0]
    expected_revision = _PROFILE_REVISIONS.get(profile_name)
    if expected_revision is None:
        raise VerificationError("unsupported lineage profile")
    revision = _require_string(profile.get("revision"), "revision")
    project_id = _require_string(profile.get("project_id"), "project id")
    database = _contained_file(root, profile.get("database"), "database path")
    backup = _contained_file(root, profile.get("backup"), "backup path")
    _expect_hash(database, profile.get("database_sha256"), "database")
    _expect_hash(backup, profile.get("backup_sha256"), "backup")
    for raw_source in _require_list(profile.get("source_files"), "source_files"):
        source = _require_dict(raw_source, "source file")
        path = _contained_file(root, source.get("path"), "source file path")
        _expect_hash(path, source.get("sha256"), "source file")

    with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise VerificationError("database SQLite integrity check failed")
        actual_revision = _read_one(connection, "SELECT version_num FROM alembic_version", ())
        if revision != expected_revision or actual_revision != (revision,):
            raise VerificationError("database revision does not match manifest")
        _read_one(connection, "SELECT id FROM projects WHERE id = ?", (project_id,))
        record_ids = _verify_records(connection, profile, project_id)
    with closing(sqlite3.connect(f"{backup.as_uri()}?mode=ro", uri=True)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise VerificationError("backup SQLite integrity check failed")
        if _read_one(connection, "SELECT version_num FROM alembic_version", ()) != (revision,):
            raise VerificationError("backup revision does not match manifest")
        _read_one(connection, "SELECT id FROM projects WHERE id = ?", (project_id,))
        if _verify_records(connection, profile, project_id) != record_ids:
            raise VerificationError("backup seeded records do not match profile")
    return {
        "profile": profile_name,
        "status": "verified",
        "revision": revision,
        "project_id": project_id,
        "record_ids": record_ids,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    try:
        report = verify(args.manifest, args.profile)
    except (VerificationError, OSError, sqlite3.Error) as exc:
        parser.error(str(exc))
    json.dump(report, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
