"""Bounded, unverified XYZ point-cloud preview (no inferred surface)."""

from __future__ import annotations

import hashlib
import json
from math import dist, isfinite
from typing import Any

from reefvision.services.spatial_mesh_obj_v14 import MAX_VERTICES

MAX_PLY_BYTES = 256_000


def parse_ascii_ply_points(text: str) -> list[list[float]]:
    """Read vertex-only ASCII PLY 1.0 XYZ coordinates; reject mesh/unknown records."""
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_PLY_BYTES:
        raise ValueError("Point-cloud PLY exceeds the 256000-byte preview limit")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "ply":
        raise ValueError("Point-cloud PLY must begin with ply")
    format_seen = False
    vertex_count: int | None = None
    properties: list[str] = []
    header_end: int | None = None
    for position, raw in enumerate(lines[1:], 1):
        if position > 128:
            raise ValueError("Point-cloud PLY header exceeds 128 lines")
        parts = raw.strip().split()
        if not parts:
            continue
        if parts[0] in {"comment", "obj_info"}:
            continue
        if parts[0] == "end_header":
            if len(parts) != 1:
                raise ValueError("Malformed PLY end_header")
            header_end = position
            break
        if parts[0] == "format":
            if format_seen or parts != ["format", "ascii", "1.0"]:
                raise ValueError("Only ASCII PLY 1.0 point clouds are supported")
            format_seen = True
        elif parts[0] == "element":
            if vertex_count is not None or len(parts) != 3 or parts[1] != "vertex":
                raise ValueError("Point-cloud PLY must have one vertex-only element")
            try:
                vertex_count = int(parts[2])
            except ValueError as exc:
                raise ValueError("Invalid point-cloud vertex count") from exc
            if not 1 <= vertex_count <= MAX_VERTICES:
                raise ValueError("Point-cloud vertex count outside preview bounds")
        elif parts[0] == "property":
            if (
                vertex_count is None
                or len(parts) != 3
                or parts[1] not in {"float", "double", "float32", "float64"}
                or parts[2] not in {"x", "y", "z"}
                or parts[2] in properties
            ):
                raise ValueError("Point-cloud PLY requires unique floating XYZ properties")
            properties.append(parts[2])
        else:
            raise ValueError("Unsupported point-cloud PLY header directive")
    if (
        not format_seen
        or vertex_count is None
        or header_end is None
        or set(properties) != {"x", "y", "z"}
        or len(properties) != 3
    ):
        raise ValueError("Incomplete point-cloud PLY header")
    rows = lines[header_end + 1 :]
    if len(rows) != vertex_count:
        raise ValueError("Point-cloud PLY body length does not match vertex count")
    xyz = [properties.index(axis) for axis in ("x", "y", "z")]
    points: list[list[float]] = []
    for row in rows:
        values = row.split()
        if len(values) != 3:
            raise ValueError("Point-cloud PLY vertex must have three values")
        try:
            parsed = [float(value) for value in values]
        except ValueError as exc:
            raise ValueError("Invalid point-cloud coordinate") from exc
        points.append([parsed[index] for index in xyz])
    return points


def measure_point_cloud_preview(
    *,
    points: list[list[float]],
    meters_per_unit: float,
    calibration_method: str,
    calibration_evidence: str,
    relative_scale_uncertainty: float | None = None,
    source_label: str | None = None,
) -> dict[str, Any]:
    """Report point extents, not surface area, organism size, or branch length."""
    if not 1 <= len(points) <= MAX_VERTICES:
        raise ValueError("Point-cloud size outside preview bounds")
    scale = float(meters_per_unit)
    if not isfinite(scale) or not 0 < scale <= 1_000_000:
        raise ValueError("meters_per_unit must be finite and within bounds")
    if calibration_method not in {"ruler", "photogrammetry_control", "instrument", "other"}:
        raise ValueError("A supported calibration_method is required")
    if not isinstance(calibration_evidence, str) or not calibration_evidence.strip():
        raise ValueError("Calibration evidence is required")
    if relative_scale_uncertainty is not None and (
        not isfinite(relative_scale_uncertainty)
        or not 0 <= relative_scale_uncertainty <= 1
    ):
        raise ValueError("relative_scale_uncertainty must be between 0 and 1")
    vertices: list[tuple[float, float, float]] = []
    for point in points:
        if (
            len(point) != 3
            or any(not isfinite(float(v)) or abs(float(v)) > 1_000_000_000 for v in point)
        ):
            raise ValueError("Every point requires three bounded finite coordinates")
        vertices.append((float(point[0]), float(point[1]), float(point[2])))
    dimensions = [
        (max(p[axis] for p in vertices) - min(p[axis] for p in vertices)) * scale
        for axis in range(3)
    ]
    centroid = [sum(p[axis] for p in vertices) / len(vertices) * scale for axis in range(3)]
    diagonal = dist((0.0, 0.0, 0.0), dimensions)
    unique_count = len(set(vertices))
    geometry_hash = hashlib.sha256(
        json.dumps(sorted(vertices), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": "point-cloud-preview-0001",
        "point_count": len(vertices),
        "unique_point_count": unique_count,
        "axis_aligned_dimensions_m": dimensions,
        "axis_aligned_bounding_box_diagonal_m": diagonal,
        "axis_aligned_dimension_scale_uncertainty_m": (
            [value * relative_scale_uncertainty for value in dimensions]
            if relative_scale_uncertainty is not None
            else None
        ),
        "axis_aligned_bounding_box_diagonal_scale_uncertainty_m": (
            diagonal * relative_scale_uncertainty
            if relative_scale_uncertainty is not None
            else None
        ),
        "arithmetic_centroid_in_source_frame_m": centroid,
        "surface_area_m2": None,
        "branch_length_m": None,
        "qc_warnings": (["duplicate_points_present"] if unique_count < len(vertices) else []),
        "measurement_status": "caller_supplied_unverified",
        "provenance": {
            "geometry_sha256": geometry_hash,
            "source_label": source_label,
            "meters_per_mesh_unit": scale,
            "calibration_method": calibration_method,
            "calibration_evidence": calibration_evidence.strip(),
            "calibration_verified": False,
            "relative_scale_uncertainty": relative_scale_uncertainty,
            "coordinate_registration_verified": False,
        },
    }


def preview_point_cloud_from_request(payload: Any) -> dict[str, Any]:
    if payload.ply_text is not None:
        points = parse_ascii_ply_points(payload.ply_text)
        source_format = "ply_ascii_point_cloud"
    else:
        points = payload.points
        source_format = "xyz_points"
    result = measure_point_cloud_preview(
        points=points,
        meters_per_unit=payload.meters_per_unit,
        calibration_method=payload.calibration_method,
        calibration_evidence=payload.calibration_evidence,
        relative_scale_uncertainty=payload.relative_scale_uncertainty,
        source_label=payload.source_label,
    )
    result["provenance"]["source_format"] = source_format
    return result
