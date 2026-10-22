"""Bounded, unverified XYZ point-cloud preview (no inferred surface)."""

from __future__ import annotations

import hashlib
import json
from math import dist, isfinite
from typing import Any

from reefvision.services.spatial_mesh_obj_v14 import MAX_VERTICES

MAX_PLY_BYTES = 256_000


def parse_ascii_ply_points(text: str) -> list[list[float]]:
    """Read vertex-only ASCII PLY 1.0 XYZ or XYZ+RGB; discard validated color."""
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
            if vertex_count is None or len(parts) != 3 or parts[2] in properties:
                raise ValueError("Point-cloud PLY requires unique vertex properties")
            property_type, property_name = parts[1:]
            if property_name in {"x", "y", "z"}:
                if property_type not in {"float", "double", "float32", "float64"}:
                    raise ValueError("Point-cloud XYZ properties must be floating point")
            elif property_name in {"red", "green", "blue"}:
                if property_type not in {"uchar", "uint8"}:
                    raise ValueError("Point-cloud RGB properties must be unsigned bytes")
            else:
                raise ValueError("Unsupported point-cloud PLY property")
            properties.append(property_name)
        else:
            raise ValueError("Unsupported point-cloud PLY header directive")
    allowed_properties = (
        {"x", "y", "z"},
        {"x", "y", "z", "red", "green", "blue"},
    )
    if (
        not format_seen
        or vertex_count is None
        or header_end is None
        or set(properties) not in allowed_properties
    ):
        raise ValueError("Incomplete point-cloud PLY header")
    rows = lines[header_end + 1 :]
    if len(rows) != vertex_count:
        raise ValueError("Point-cloud PLY body length does not match vertex count")
    xyz = [properties.index(axis) for axis in ("x", "y", "z")]
    points: list[list[float]] = []
    for row in rows:
        values = row.split()
        if len(values) != len(properties):
            raise ValueError("Point-cloud PLY vertex does not match header properties")
        try:
            parsed = [float(values[index]) for index in xyz]
        except ValueError as exc:
            raise ValueError("Invalid point-cloud coordinate") from exc
        if any(not isfinite(value) or abs(value) > 1_000_000_000 for value in parsed):
            raise ValueError("Point-cloud coordinates must be finite and bounded")
        for channel in ("red", "green", "blue"):
            if channel in properties:
                token = values[properties.index(channel)]
                if not token.isascii() or not token.isdecimal() or int(token) > 255:
                    raise ValueError("Point-cloud RGB channels must be 0-255 integers")
        points.append(parsed)
    return points


def measure_point_cloud_preview(
    *,
    points: list[list[float]],
    meters_per_unit: float,
    calibration_method: str,
    calibration_evidence: str,
    relative_scale_uncertainty: float | None = None,
    source_label: str | None = None,
    point_index_pairs: list[list[int]] | None = None,
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
        not isfinite(relative_scale_uncertainty) or not 0 <= relative_scale_uncertainty <= 1
    ):
        raise ValueError("relative_scale_uncertainty must be between 0 and 1")
    vertices: list[tuple[float, float, float]] = []
    for point in points:
        if len(point) != 3 or any(
            not isfinite(float(v)) or abs(float(v)) > 1_000_000_000 for v in point
        ):
            raise ValueError("Every point requires three bounded finite coordinates")
        vertices.append((float(point[0]), float(point[1]), float(point[2])))
    # Selected point-pair chords refer to original input order, not branches.
    selected_chords: list[dict[str, Any]] = []
    if point_index_pairs is not None:
        if not isinstance(point_index_pairs, list) or len(point_index_pairs) > 32:
            raise ValueError("At most 32 point-index pairs are supported")
        for pair in point_index_pairs:
            if (
                not isinstance(pair, (list, tuple))
                or len(pair) != 2
                or any(type(index) is not int for index in pair)
                or any(index < 0 or index >= len(vertices) for index in pair)
                or pair[0] == pair[1]
            ):
                raise ValueError("Point pair requires two distinct in-range integer indices")
            endpoints = [vertices[pair[0]], vertices[pair[1]]]
            chord_m = dist(*endpoints) * scale
            selected_chords.append(
                {
                    "point_indices": list(pair),
                    # Fingerprint endpoint geometry, not just mutable point indices.
                    # Ordered and scale-independent; not an organism identifier.
                    "endpoint_ordered_geometry_sha256": hashlib.sha256(
                        json.dumps(endpoints, separators=(",", ":")).encode("utf-8")
                    ).hexdigest(),
                    "endpoint_coordinates_in_source_frame_m": [
                        [coordinate * scale for coordinate in vertex]
                        for vertex in endpoints
                    ],
                    "chord_distance_m": chord_m,
                    "chord_distance_scale_interval_m": (
                        [
                            chord_m * (1 - relative_scale_uncertainty),
                            chord_m * (1 + relative_scale_uncertainty),
                        ]
                        if relative_scale_uncertainty is not None
                        else None
                    ),
                    "scale_uncertainty_m": (
                        chord_m * relative_scale_uncertainty
                        if relative_scale_uncertainty is not None
                        else None
                    ),
                }
            )
    dimensions = [
        (max(p[axis] for p in vertices) - min(p[axis] for p in vertices)) * scale
        for axis in range(3)
    ]
    bounds_min = [min(p[axis] for p in vertices) * scale for axis in range(3)]
    bounds_max = [max(p[axis] for p in vertices) * scale for axis in range(3)]
    centroid = [sum(p[axis] for p in vertices) / len(vertices) * scale for axis in range(3)]
    diagonal = dist((0.0, 0.0, 0.0), dimensions)
    envelope_volume = dimensions[0] * dimensions[1] * dimensions[2]
    envelope_scale_interval = (
        [
            envelope_volume * (1 - relative_scale_uncertainty) ** 3,
            envelope_volume * (1 + relative_scale_uncertainty) ** 3,
        ]
        if relative_scale_uncertainty is not None
        else None
    )

    def coordinate_scale_intervals(bounds: list[float]) -> list[list[float]] | None:
        if relative_scale_uncertainty is None:
            return None
        intervals: list[list[float]] = []
        for value in bounds:
            candidates = (
                value * (1 - relative_scale_uncertainty),
                value * (1 + relative_scale_uncertainty),
            )
            intervals.append([min(candidates), max(candidates)])
        return intervals

    unique_count = len(set(vertices))
    geometry_hash = hashlib.sha256(
        json.dumps(sorted(vertices), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": "point-cloud-preview-0001",
        "point_count": len(vertices),
        "unique_point_count": unique_count,
        "selected_point_chords": selected_chords,
        "axis_aligned_dimensions_m": dimensions,
        "axis_aligned_min_in_source_frame_m": bounds_min,
        "axis_aligned_max_in_source_frame_m": bounds_max,
        "axis_aligned_min_in_source_frame_scale_interval_m": coordinate_scale_intervals(bounds_min),
        "axis_aligned_max_in_source_frame_scale_interval_m": coordinate_scale_intervals(bounds_max),
        "axis_aligned_bounding_box_diagonal_m": diagonal,
        "axis_aligned_bounding_box_envelope_volume_m3": envelope_volume,
        "axis_aligned_bounding_box_envelope_volume_scale_interval_m3": (envelope_scale_interval),
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
        "arithmetic_centroid_in_source_frame_scale_interval_m": coordinate_scale_intervals(
            centroid
        ),
        "surface_area_m2": None,
        "branch_length_m": None,
        "qc_warnings": (["duplicate_points_present"] if unique_count < len(vertices) else []),
        "measurement_status": "caller_supplied_unverified",
        "provenance": {
            "geometry_sha256": geometry_hash,
            "ordered_geometry_sha256": hashlib.sha256(
                json.dumps(vertices, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
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
        point_index_pairs=payload.point_index_pairs,
    )
    result["provenance"]["source_format"] = source_format
    # Hash the received PLY text (including RGB) separately from XYZ geometry.
    # This is not a digest of the original on-disk file or a verification mark.
    result["provenance"]["source_text_sha256"] = (
        hashlib.sha256(payload.ply_text.encode("utf-8")).hexdigest()
        if payload.ply_text is not None
        else None
    )
    return result
