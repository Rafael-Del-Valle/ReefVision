"""Create disposable 1.3 and draft-1.4 SQLite profiles for installed acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import runpy
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from alembic import command
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import URL, create_engine
from sqlalchemy.orm import Session

from reefvision.schemas.scientific_data import ScientificRecordCreate
from reefvision.schemas.spatial_mesh_preview_v14 import (
    MeshCalibrationReviewEvidence,
    MeshPreviewRequest,
)
from reefvision.services.scientific_data import ScientificDataService
from reefvision.services.spatial_calibration_review_v14 import (
    canonical_spatial_calibration_review_evidence,
)
from reefvision.services.spatial_mesh_surface_v14 import preview_from_request

_API = Path(__file__).resolve().parents[1] / "apps" / "api"
_PROJECT = "507af087-ff80-458f-9470-9b3bdc980a5b"
_SCIENTIFIC_RECORD = "471a1c20-7afc-4edf-b6c1-023523fef1d7"
_ASSET = "04f9c44e-d30e-494f-ab1e-9aa3b4db02e9"
_REVIEW = "be5cb2db-445f-4a15-8434-5a7d168bd22e"
_OBSERVED_AT = "2026-01-01T00:00:00Z"
_FIXED_DATETIME = datetime(2026, 1, 1, tzinfo=UTC)
_PROFILES = {
    "validated-1.3": "b13_temporal_0001",
    "draft-1.4-0038": "0038",
    "draft-1.4-0039": "0039",
}
_LEGACY = ("0038_spatial_source_assets.py", "0039_spatial_calibration_reviews.py")


class SeedRecord(TypedDict):
    kind: str
    id: str
    sha256: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed_database(database: Path, revision: str) -> tuple[list[SeedRecord], list[Path]]:
    url = URL.create("sqlite", database=str(database))
    config = Config(str(_API / "alembic.ini"))
    config.attributes["configure_logger"] = False
    config.set_main_option("sqlalchemy.url", url.render_as_string().replace("%", "%%"))
    spatial = revision in {"0038", "0039"}
    command.upgrade(config, "0037" if spatial else revision)
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO projects (id, name, slug, storage_root, default_annotation_type, "
                "created_at, updated_at) VALUES (?, 'Synthetic lineage acceptance', "
                "'lineage-acceptance', 'projects/lineage-acceptance', 'bbox', "
                "?, ?)",
                (_PROJECT, _FIXED_DATETIME, _FIXED_DATETIME),
            )
            if not spatial:
                record = ScientificRecordCreate.model_validate(
                    {
                        "variable": "water_temperature",
                        "source_kind": "observed",
                        "value": 12.0,
                        "unit": "degC",
                        "observed_at": _OBSERVED_AT,
                        "provenance": {
                            "source": "Synthetic lineage fixture",
                            "acquired_at": _OBSERVED_AT,
                        },
                    }
                )
                with Session(bind=connection) as session:
                    row = ScientificDataService(session).add_records(_PROJECT, [record])[0]
                    row.id = _SCIENTIFIC_RECORD
                    row.created_at = _FIXED_DATETIME
                    record_sha256 = row.content_sha256
                    session.commit()
                return (
                    [
                        {
                            "kind": "scientific_record",
                            "id": _SCIENTIFIC_RECORD,
                            "sha256": record_sha256,
                        }
                    ],
                    [],
                )
            with Operations.context(MigrationContext.configure(connection)):
                for filename in _LEGACY[: int(revision) - 37]:
                    runpy.run_path(str(_API / "migrations" / "legacy_spatial" / filename))[
                        "upgrade"
                    ]()
            connection.exec_driver_sql("UPDATE alembic_version SET version_num = ?", (revision,))
            media = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
            asset_path = "projects/lineage-acceptance/assets/reef.obj"
            asset = database.parent / asset_path
            asset.parent.mkdir(parents=True)
            asset.write_bytes(media)
            digest = hashlib.sha256(media).hexdigest()
            connection.exec_driver_sql(
                "INSERT INTO spatial_source_assets "
                "(id, project_id, original_filename, source_format, source_kind, managed_path, "
                "sha256, size_bytes, created_at) VALUES "
                "(?, ?, 'reef.obj', 'obj', 'mesh', ?, ?, ?, ?)",
                (_ASSET, _PROJECT, asset_path, digest, len(media), _FIXED_DATETIME),
            )
            records: list[SeedRecord] = [
                {"kind": "spatial_source_asset", "id": _ASSET, "sha256": digest}
            ]
            if revision == "0039":
                geometry = preview_from_request(
                    MeshPreviewRequest(
                        obj_text=media.decode("ascii"),
                        meters_per_unit=1.0,
                        calibration_method="other",
                        calibration_evidence="Synthetic unit scale",
                    )
                )
                evidence = MeshCalibrationReviewEvidence.model_validate(
                    {
                        "calibration_operator_id": "fixture-operator",
                        "independent_reviewer_id": "fixture-reviewer",
                        "independent_review_decision": "inconclusive",
                        "independent_review_note": "Synthetic migration fixture only",
                        "reviewed_at_utc": _OBSERVED_AT,
                        "reviewed_geometry_sha256": geometry["provenance"]["geometry_sha256"],
                        "reviewed_source_payload_sha256": digest,
                        "reviewed_spatial_source_asset_id": _ASSET,
                        "reviewed_meters_per_unit": 1.0,
                        "reviewed_calibration_method": "other",
                        "reviewed_calibration_evidence": "Synthetic unit scale",
                    }
                )
                payload, evidence_digest = canonical_spatial_calibration_review_evidence(evidence)
                connection.exec_driver_sql(
                    "INSERT INTO spatial_calibration_reviews "
                    "(id, project_id, spatial_source_asset_id, source_sha256, evidence_sha256, "
                    "evidence_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        _REVIEW,
                        _PROJECT,
                        _ASSET,
                        digest,
                        evidence_digest,
                        json.dumps(payload),
                        _FIXED_DATETIME,
                    ),
                )
                records.append(
                    {
                        "kind": "spatial_calibration_review",
                        "id": _REVIEW,
                        "sha256": evidence_digest,
                    }
                )
            return records, [asset]
    finally:
        engine.dispose()


def _backup_database(database: Path, backup: Path, revision: str) -> str:
    with (
        closing(sqlite3.connect(database)) as source,
        closing(sqlite3.connect(backup)) as destination,
    ):
        source.backup(destination)
        if destination.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise RuntimeError(f"SQLite integrity check failed: {backup.name}")
        if destination.execute("SELECT version_num FROM alembic_version").fetchall() != [
            (revision,)
        ]:
            raise RuntimeError(f"Unexpected backup revision: {backup.name}")
    return hashlib.sha256(backup.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output", type=Path, help="New directory for synthetic profiles and backups"
    )
    args = parser.parse_args()
    output = args.output.resolve()
    try:
        output.mkdir()
    except FileExistsError:
        parser.error(f"Output already exists: {output}")

    profiles = []
    for name, revision in _PROFILES.items():
        profile = output / name
        profile.mkdir()
        database = profile / "reefvision.db"
        backup = output / f"{name}.pre-upgrade.db"
        records, source_files = _seed_database(database, revision)
        backup_sha256 = _backup_database(database, backup, revision)
        profiles.append(
            {
                "name": name,
                "revision": revision,
                "project_id": _PROJECT,
                "database": database.relative_to(output).as_posix(),
                "database_sha256": _sha256(database),
                "backup": backup.relative_to(output).as_posix(),
                "backup_sha256": backup_sha256,
                "records": records,
                "source_files": [
                    {
                        "path": source.relative_to(output).as_posix(),
                        "sha256": _sha256(source),
                    }
                    for source in source_files
                ],
            }
        )
    manifest = {
        "schema_version": "reefvision-windows-lineage-fixtures-1",
        "fixture_kind": "synthetic_engineering",
        "profiles": profiles,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
