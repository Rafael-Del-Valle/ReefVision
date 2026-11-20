"""Durable bounded structural parsing for immutable project-owned 3D originals."""

from __future__ import annotations

import base64
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from reefvision.config import Settings
from reefvision.db.models import Job
from reefvision.services import (
    spatial_mesh_glb_v14,
    spatial_mesh_obj_v14,
    spatial_mesh_ply_v14,
)
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview
from reefvision.services.spatial_point_cloud_v14 import (
    measure_point_cloud_preview,
    parse_ascii_ply_points,
)
from reefvision.services.spatial_source_assets_v14 import (
    SPATIAL_PARSE_JOB,
    SPATIAL_PARSE_SCHEMA,
    SpatialSourceAssetService,
)
from reefvision.storage.datasets import canonical_json_sha256

_STRUCTURAL_WARNINGS = ("physical_calibration_not_applied", "structural_parse_unreviewed")


def _mesh_summary(vertices: list[list[float]], faces: list[list[int]]) -> dict[str, object]:
    result = measure_mesh_preview(
        vertices=vertices,
        faces=faces,
        meters_per_unit=1.0,
        calibration_method="other",
        calibration_evidence=(
            "Background structural parse in source units; physical calibration not supplied"
        ),
        # A nominal unit scale cannot establish whether the future calibrated
        # volume will be representable. Structural receipts carry no volume.
        require_representable_enclosed_volume=False,
    )
    return {
        "source_kind_resolved": "mesh",
        "vertex_count": result["vertex_count"],
        "face_count": result["face_count"],
        "point_count": None,
        "geometry_sha256": result["provenance"]["geometry_sha256"],
        "qc_warnings": sorted(set(result["qc_warnings"]) | set(_STRUCTURAL_WARNINGS)),
    }


def _point_summary(points: list[list[float]]) -> dict[str, object]:
    result = measure_point_cloud_preview(
        points=points,
        meters_per_unit=1.0,
        calibration_method="other",
        calibration_evidence=(
            "Background structural parse in source units; physical calibration not supplied"
        ),
    )
    return {
        "source_kind_resolved": "point_cloud",
        "vertex_count": None,
        "face_count": None,
        "point_count": result["point_count"],
        "geometry_sha256": result["provenance"]["geometry_sha256"],
        "qc_warnings": sorted(set(result["qc_warnings"]) | set(_STRUCTURAL_WARNINGS)),
    }


def _parse_original(source_format: str, original: bytes) -> dict[str, object]:
    if source_format == "obj":
        text = original.decode("utf-8", errors="strict")
        vertices, faces = spatial_mesh_obj_v14.parse_obj_triangles(text)
        return _mesh_summary(vertices, faces)
    if source_format == "glb":
        encoded = base64.b64encode(original).decode("ascii")
        if len(encoded) > 350_000:
            raise ValueError("GLB exceeds the bounded structural parse limit")
        vertices, faces = spatial_mesh_glb_v14.parse_glb_triangles(encoded)
        return _mesh_summary(vertices, faces)
    if source_format == "ply":
        text = original.decode("ascii", errors="strict")
        try:
            vertices, faces = spatial_mesh_ply_v14.parse_ply_triangles(text)
        except ValueError as mesh_error:
            try:
                return _point_summary(parse_ascii_ply_points(text))
            except ValueError as point_error:
                raise ValueError(
                    "PLY failed both bounded mesh and point-cloud parsing: "
                    f"mesh={mesh_error}; point_cloud={point_error}"
                ) from point_error
        return _mesh_summary(vertices, faces)
    raise ValueError("Unsupported spatial source format")


def process_spatial_source_parse_job(
    settings: Settings,
    factory: sessionmaker[Session],
    job_id: str,
) -> bool:
    with factory() as session:
        job = session.get(Job, job_id)
        if (
            job is None
            or job.job_type != SPATIAL_PARSE_JOB
            or job.status
            not in {
                "queued",
                "running",
            }
        ):
            return False
        job.status = "running"
        job.started_at = job.started_at or datetime.now(UTC)
        job.error_message = None
        session.commit()

        request = dict(job.request_json)
        project_id = request.get("project_id")
        asset_id = request.get("spatial_source_asset_id")
        expected_sha256 = request.get("expected_source_sha256")
        source_format = request.get("source_format")
        try:
            if (
                request.get("schema_version") != SPATIAL_PARSE_SCHEMA
                or not isinstance(project_id, str)
                or not isinstance(asset_id, str)
                or not isinstance(expected_sha256, str)
                or not isinstance(source_format, str)
                or job.project_id != project_id
            ):
                raise ValueError("Spatial source parse job binding is invalid")
            service = SpatialSourceAssetService(session, settings)
            asset = service.get(project_id, asset_id)
            if (
                asset.sha256 != expected_sha256
                or asset.source_format != source_format
                or asset.managed_path != request.get("managed_path")
                or asset.size_bytes != request.get("size_bytes")
            ):
                raise ValueError("Spatial source parse job no longer matches the immutable asset")
            original = service.read_verified(project_id, asset_id)
            summary = _parse_original(source_format, original)
            result_content = {
                "schema_version": SPATIAL_PARSE_SCHEMA,
                "project_id": project_id,
                "spatial_source_asset_id": asset_id,
                "source_sha256": asset.sha256,
                "source_format": source_format,
                **summary,
                "calibration_applied": False,
                "calibration_verified": False,
                "specimen_identity_verified": False,
            }
            job.result_json = {
                **result_content,
                "content_sha256": canonical_json_sha256(result_content),
            }
            job.status = "succeeded"
            job.progress_current = 1
            job.progress_total = 1
            job.completed_at = datetime.now(UTC)
            session.commit()
            return True
        except Exception as exc:
            session.rollback()
            failed = session.get(Job, job_id)
            if failed is None:
                return False
            failed.status = "failed"
            failed.progress_current = 0
            failed.progress_total = 1
            failed.result_json = None
            failed.error_message = f"Spatial source background parse failed: {exc}"
            failed.completed_at = datetime.now(UTC)
            session.commit()
            return True
