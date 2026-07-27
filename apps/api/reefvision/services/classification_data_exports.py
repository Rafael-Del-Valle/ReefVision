"""Checksummed CSV, JSON, and NumPy scientific classification exports."""

from __future__ import annotations

import csv
import io
import os
import shutil
import zipfile
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from sqlalchemy.orm import Session

from reefvision import __version__
from reefvision.config import Settings
from reefvision.db.models import ArtifactRecord, Project
from reefvision.domain.errors import NotFoundError, ValidationError
from reefvision.schemas.classification_data_exports import (
    ClassificationDataExportRequest,
    ClassificationDataExportResponse,
)
from reefvision.services.classification_assignment_exports import (
    ScientificClassificationExportService,
)
from reefvision.storage.datasets import canonical_json_bytes
from reefvision.storage.projects import resolve_managed_project_path


def _text_array(values: list[str]) -> np.ndarray:
    maximum = max((len(value) for value in values), default=1)
    return np.asarray(values, dtype=f"U{maximum}")


def _canonical_text(value: Any) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_bundle(
    settings: Settings,
    *,
    relative_root: str,
    files: Mapping[str, bytes],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    output_root = resolve_managed_project_path(settings, relative_root)
    archive_path = f"{relative_root}.zip"
    archive = resolve_managed_project_path(settings, archive_path)
    temporary_root = output_root.with_name(f".{output_root.name}.{uuid4().hex[:8]}.tmp")
    temporary_archive = archive.with_name(f".{archive.name}.{uuid4().hex[:8]}.tmp")
    if output_root.exists() or archive.exists():
        raise ValidationError("The managed classification export destination already exists")
    published_root = False
    published_archive = False
    try:
        temporary_root.mkdir(parents=True, exist_ok=False)
        file_checksums: dict[str, str] = {}
        for relative_name, content in sorted(files.items()):
            destination = (temporary_root / relative_name).resolve()
            if not destination.is_relative_to(temporary_root.resolve()):
                raise ValidationError("Classification export file path escapes the export root")
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
        manifest_path = temporary_root / "manifest.json"
        manifest_path.write_bytes(manifest_bytes)
        file_checksums["manifest.json"] = sha256(manifest_bytes).hexdigest()
        archive.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(
            temporary_archive,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as bundle:
            for path in sorted(temporary_root.rglob("*")):
                if path.is_file():
                    bundle.write(path, arcname=path.relative_to(temporary_root).as_posix())
        os.replace(temporary_root, output_root)
        published_root = True
        os.replace(temporary_archive, archive)
        published_archive = True
        return {
            "output_path": relative_root,
            "archive_path": archive_path,
            "manifest_path": f"{relative_root}/manifest.json",
            "archive_sha256": _file_sha256(archive),
            "archive_size_bytes": archive.stat().st_size,
            "manifest_sha256": sha256(manifest_bytes).hexdigest(),
            "file_checksums": file_checksums,
        }
    except Exception:
        shutil.rmtree(temporary_root, ignore_errors=True)
        temporary_archive.unlink(missing_ok=True)
        if published_archive:
            archive.unlink(missing_ok=True)
        if published_root:
            shutil.rmtree(output_root, ignore_errors=True)
        raise


class ClassificationDataExportService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def export(
        self,
        project_id: str,
        request: ClassificationDataExportRequest,
    ) -> ClassificationDataExportResponse:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        scientific = ScientificClassificationExportService(
            self.session,
            self.settings,
        ).export(project_id, assignment_status=request.assignment_status)
        if not scientific.rows:
            raise ValidationError("No classification assignments are available for export")
        rows = [row.model_dump(mode="json") for row in scientific.rows]
        files: dict[str, bytes] = {}

        if "json" in request.formats:
            files["classification-assignments.json"] = canonical_json_bytes(
                scientific.model_dump(mode="json")
            )

        if "csv" in request.formats:
            csv_rows: list[dict[str, Any]] = []
            for row in rows:
                bbox = row.get("bounding_box") or [None, None, None, None]
                csv_rows.append(
                    {
                        "assignment_id": row["assignment_id"],
                        "assignment_revision": row["assignment_revision"],
                        "assignment_status": row["assignment_status"],
                        "target_kind": row["target_kind"],
                        "target_key": row["target_key"],
                        "image_id": row["image_id"],
                        "image_filename": row["image_filename"],
                        "image_group_key": row.get("image_group_key") or "",
                        "capture_timestamp": row.get("capture_timestamp") or "",
                        "annotation_id": row.get("annotation_id") or "",
                        "mask_annotation_id": row.get("mask_annotation_id") or "",
                        "fragment_key": row.get("fragment_key") or "",
                        "x_min": bbox[0] if bbox[0] is not None else "",
                        "y_min": bbox[1] if bbox[1] is not None else "",
                        "x_max": bbox[2] if bbox[2] is not None else "",
                        "y_max": bbox[3] if bbox[3] is not None else "",
                        "label_set_id": row["label_set_id"],
                        "label_set_key": row["label_set_key"],
                        "label_set_name": row["label_set_name"],
                        "cardinality": row["cardinality"],
                        "label_class_id": row["label_class_id"],
                        "label_class_name": row["label_class_name"],
                        "source_type": row["source_type"],
                        "source_model_id": row.get("source_model_id") or "",
                        "source_model_name": row.get("source_model_name") or "",
                        "source_prediction_id": row.get("source_prediction_id") or "",
                        "confidence": (
                            row["confidence"] if row.get("confidence") is not None else ""
                        ),
                        "reviewed_at": row.get("reviewed_at") or "",
                        "measurement_join_status": row["measurement_join_status"],
                        "measurement_mask_id": row.get("measurement_mask_id") or "",
                        "probabilities_json": _canonical_text(row.get("probabilities") or {}),
                        "measurements_json": _canonical_text(row.get("measurements") or {}),
                        "image_metadata_json": _canonical_text(row.get("image_metadata") or {}),
                        "provenance_json": _canonical_text(row.get("provenance") or {}),
                        "measurement_candidate_mask_ids_json": _canonical_text(
                            row.get("measurement_candidate_mask_ids") or []
                        ),
                    }
                )
            output = io.StringIO(newline="")
            writer = csv.DictWriter(output, fieldnames=list(csv_rows[0]))
            writer.writeheader()
            writer.writerows(csv_rows)
            files["classification-assignments.csv"] = output.getvalue().encode("utf-8")

        if "npz" in request.formats:
            bbox = np.full((len(rows), 4), np.nan, dtype=np.float64)
            for index, row in enumerate(rows):
                value = row.get("bounding_box")
                if value is not None:
                    bbox[index] = np.asarray(value, dtype=np.float64)
            confidence = np.asarray(
                [
                    float(row["confidence"]) if row.get("confidence") is not None else np.nan
                    for row in rows
                ],
                dtype=np.float64,
            )
            npz_output = io.BytesIO()
            np.savez_compressed(
                npz_output,
                assignment_id=_text_array([str(row["assignment_id"]) for row in rows]),
                assignment_revision=np.asarray(
                    [int(row["assignment_revision"]) for row in rows],
                    dtype=np.int64,
                ),
                target_kind=_text_array([str(row["target_kind"]) for row in rows]),
                target_key=_text_array([str(row["target_key"]) for row in rows]),
                image_id=_text_array([str(row["image_id"]) for row in rows]),
                image_filename=_text_array([str(row["image_filename"]) for row in rows]),
                annotation_id=_text_array([str(row.get("annotation_id") or "") for row in rows]),
                mask_annotation_id=_text_array(
                    [str(row.get("mask_annotation_id") or "") for row in rows]
                ),
                fragment_key=_text_array([str(row.get("fragment_key") or "") for row in rows]),
                bbox=bbox,
                label_set_key=_text_array([str(row["label_set_key"]) for row in rows]),
                label_class_id=_text_array([str(row["label_class_id"]) for row in rows]),
                label_class_name=_text_array([str(row["label_class_name"]) for row in rows]),
                source_model_id=_text_array(
                    [str(row.get("source_model_id") or "") for row in rows]
                ),
                confidence=confidence,
                measurement_join_status=_text_array(
                    [str(row["measurement_join_status"]) for row in rows]
                ),
                measurement_mask_id=_text_array(
                    [str(row.get("measurement_mask_id") or "") for row in rows]
                ),
                probabilities_json=_text_array(
                    [_canonical_text(row.get("probabilities") or {}) for row in rows]
                ),
                measurements_json=_text_array(
                    [_canonical_text(row.get("measurements") or {}) for row in rows]
                ),
                image_metadata_json=_text_array(
                    [_canonical_text(row.get("image_metadata") or {}) for row in rows]
                ),
                provenance_json=_text_array(
                    [_canonical_text(row.get("provenance") or {}) for row in rows]
                ),
            )
            files["classification-assignments.npz"] = npz_output.getvalue()

        artifact_id = str(uuid4())
        relative_root = f"{project.storage_root}/classification-exports/scientific-{artifact_id}"
        row_checksum = sha256(canonical_json_bytes(rows)).hexdigest()
        manifest = {
            "format": "reefvision-scientific-classification-export",
            "format_version": "1.0",
            "reefvision_version": __version__,
            "created_at": datetime.now(UTC).isoformat(),
            "artifact_id": artifact_id,
            "project_id": project.id,
            "project_name": project.name,
            "formats": list(request.formats),
            "parameters": request.model_dump(mode="json"),
            "row_count": scientific.row_count,
            "row_sha256": row_checksum,
            "assignment_revisions": [
                {
                    "assignment_id": row["assignment_id"],
                    "revision": row["assignment_revision"],
                    "status": row["assignment_status"],
                }
                for row in rows
            ],
            "measurement_join_summary": {
                "matched": scientific.matched_measurement_count,
                "unmatched": scientific.unmatched_measurement_count,
                "ambiguous": scientific.ambiguous_measurement_count,
            },
            "warnings": list(scientific.warnings),
        }
        write_result = _write_bundle(
            self.settings,
            relative_root=relative_root,
            files=files,
            manifest=manifest,
        )
        try:
            artifact = ArtifactRecord(
                id=artifact_id,
                project_id=project.id,
                artifact_type="scientific_classification_data_bundle",
                created_by="classification_data_export",
                reefvision_version=__version__,
                source_kind="project",
                source_id=project.id,
                source_checksum=row_checksum,
                source_annotation_revision=max(int(row["assignment_revision"]) for row in rows),
                parameters_json=request.model_dump(mode="json"),
                postprocessing_json={
                    "formats": list(request.formats),
                    "row_count": scientific.row_count,
                    "manifest_sha256": write_result["manifest_sha256"],
                },
                review_status="unreviewed",
                managed_path=write_result["archive_path"],
                checksum=write_result["archive_sha256"],
                size_bytes=write_result["archive_size_bytes"],
                metadata_json={
                    "manifest_path": write_result["manifest_path"],
                    "output_path": write_result["output_path"],
                    "file_checksums": write_result["file_checksums"],
                },
            )
            self.session.add(artifact)
            self.session.commit()
        except Exception:
            self.session.rollback()
            resolve_managed_project_path(
                self.settings,
                write_result["archive_path"],
            ).unlink(missing_ok=True)
            shutil.rmtree(
                resolve_managed_project_path(
                    self.settings,
                    write_result["output_path"],
                ),
                ignore_errors=True,
            )
            raise
        return ClassificationDataExportResponse(
            artifact_id=artifact.id,
            project_id=project.id,
            row_count=scientific.row_count,
            archive_path=write_result["archive_path"],
            manifest_path=write_result["manifest_path"],
            archive_sha256=write_result["archive_sha256"],
            archive_size_bytes=write_result["archive_size_bytes"],
            manifest_sha256=write_result["manifest_sha256"],
            formats=list(request.formats),
            matched_measurement_count=scientific.matched_measurement_count,
            unmatched_measurement_count=scientific.unmatched_measurement_count,
            ambiguous_measurement_count=scientific.ambiguous_measurement_count,
            warnings=list(scientific.warnings),
        )
