"""Bounded, unverified XYZ point-cloud preview (no inferred surface)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC
from math import dist, isfinite
from typing import Any

from reefvision.services.spatial_mesh_obj_v14 import MAX_VERTICES

MAX_PLY_BYTES = 256_000
MAX_PREVIEW_POINTS = 512


def parse_ascii_ply_points(
    text: str, *, colors_out: list[list[int]] | None = None
) -> list[list[float]]:
    """Read XYZ and optionally retain validated raw PLY RGB bytes."""
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
    # Stage RGB until every vertex passes validation: never leak partial colors.
    staged_colors: list[list[int]] = []
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
        if colors_out is not None and "red" in properties:
            rgb = [int(values[properties.index(c)]) for c in ("red", "green", "blue")]
            staged_colors.append(rgb)
    if colors_out is not None:
        colors_out.extend(staged_colors)
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
    preserve_axis_extrema_in_preview: bool = False,
    preserve_measured_chord_endpoints_in_preview: bool = False,
) -> dict[str, Any]:
    """Report point extents, not surface area, organism size, or branch length."""
    if not 1 <= len(points) <= MAX_VERTICES:
        raise ValueError("Point-cloud size outside preview bounds")
    if not isinstance(preserve_axis_extrema_in_preview, bool):
        raise ValueError("preserve_axis_extrema_in_preview must be a boolean")
    if not isinstance(preserve_measured_chord_endpoints_in_preview, bool):
        raise ValueError("preserve_measured_chord_endpoints_in_preview must be a boolean")
    if type(meters_per_unit) not in (int, float) or not 0 < meters_per_unit <= 1_000_000:
        raise ValueError("meters_per_unit must be a finite numeric value within bounds")
    scale = float(meters_per_unit)
    if not isfinite(scale):
        raise ValueError("meters_per_unit must be finite and within bounds")
    if calibration_method not in {"ruler", "photogrammetry_control", "instrument", "other"}:
        raise ValueError("A supported calibration_method is required")
    if not isinstance(calibration_evidence, str) or not calibration_evidence.strip():
        raise ValueError("Calibration evidence is required")
    if relative_scale_uncertainty is not None and (
        type(relative_scale_uncertainty) not in (int, float)
        or not 0 <= relative_scale_uncertainty <= 1
        or not isfinite(relative_scale_uncertainty)
    ):
        raise ValueError(
            "relative_scale_uncertainty must be a finite numeric value between 0 and 1"
        )
    vertices: list[tuple[float, float, float]] = []
    for point in points:
        if (
            not isinstance(point, (list, tuple))
            or len(point) != 3
            or any(
                type(v) not in (int, float) or abs(v) > 1_000_000_000 or not isfinite(v)
                for v in point
            )
        ):
            raise ValueError("Every point requires three bounded finite numeric coordinates")
        vertices.append((float(point[0]), float(point[1]), float(point[2])))
    # Selected point-pair chords refer to original input order, not branches.
    selected_chords: list[dict[str, Any]] = []
    selected_endpoint_indices: set[int] = set()
    seen_point_pairs: set[tuple[int, int]] = set()
    seen_endpoint_geometry: set[tuple[tuple[float, float, float], tuple[float, float, float]]] = (
        set()
    )
    repeated_selected_point_pairs = False
    repeated_selected_endpoint_geometry = False
    coincident_selected_chord_count = 0
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
            selected_endpoint_indices.update(pair)
            endpoints = [vertices[pair[0]], vertices[pair[1]]]
            chord_m = dist(*endpoints) * scale
            # Different indices can still identify identical XYZ coordinates.
            # Flag a zero-length chord instead of implying biological structure.
            chord_qc_warnings: list[str] = []
            # Reversing a chord does not make an independent measurement.
            unordered_pair = (min(pair), max(pair))
            repeated_pair = unordered_pair in seen_point_pairs
            if repeated_pair:
                chord_qc_warnings.append("repeated_point_pair")
                repeated_selected_point_pairs = True
            seen_point_pairs.add(unordered_pair)
            # Distinct source indices can refer to the same XYZ chord.
            # Compare unordered coordinates without altering ordered fingerprints.
            unordered_geometry = (min(endpoints), max(endpoints))
            if not repeated_pair and unordered_geometry in seen_endpoint_geometry:
                chord_qc_warnings.append("repeated_endpoint_geometry")
                repeated_selected_endpoint_geometry = True
            seen_endpoint_geometry.add(unordered_geometry)
            if endpoints[0] == endpoints[1]:
                chord_qc_warnings.append("coincident_endpoint_coordinates")
                coincident_selected_chord_count += 1
            selected_chords.append(
                {
                    "point_indices": list(pair),
                    "qc_warnings": chord_qc_warnings,
                    # Fingerprint endpoint geometry, not just mutable point indices.
                    # Ordered and scale-independent; not an organism identifier.
                    "endpoint_ordered_geometry_sha256": hashlib.sha256(
                        json.dumps(endpoints, separators=(",", ":")).encode("utf-8")
                    ).hexdigest(),
                    "endpoint_coordinates_in_source_frame_m": [
                        [coordinate * scale for coordinate in vertex] for vertex in endpoints
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
    # Deterministic, bounded display sample. Original indices are preserved
    # so display decimation never changes the identity of measured point pairs.
    preview_count = min(len(vertices), MAX_PREVIEW_POINTS)
    if preview_count == 1:
        preview_indices = [0]
    else:
        last_index = len(vertices) - 1
        denominator = preview_count - 1
        preview_indices = [i * last_index // denominator for i in range(preview_count)]
    # Optionally pin first-occurrence XYZ extrema to the display sample.
    # Preserve original point indices and the fixed display budget; this is
    # source-frame visualization QC, not registration or outlier removal.
    extrema_indices = sorted(
        {
            index
            for axis in range(3)
            for index in (
                min(range(len(vertices)), key=lambda i: vertices[i][axis]),
                max(range(len(vertices)), key=lambda i: vertices[i][axis]),
            )
        }
    )
    pin_chords = preserve_measured_chord_endpoints_in_preview and bool(selected_endpoint_indices)
    if (preserve_axis_extrema_in_preview or pin_chords) and len(vertices) > preview_count:
        protected = {0, len(vertices) - 1}
        if preserve_axis_extrema_in_preview:
            protected.update(extrema_indices)
        if pin_chords:
            protected.update(selected_endpoint_indices)
        # Fill remaining slots evenly across the entire source index range.
        # Taking the first N candidates biases the sample toward early rows.
        candidates = [index for index in range(len(vertices)) if index not in protected]
        slots = preview_count - len(protected)
        if slots < 0 or slots > len(candidates):
            raise ValueError("Protected point indices exceed the display budget")
        if slots == 1:
            selected = [candidates[len(candidates) // 2]]
        elif slots > 1:
            selected = [candidates[i * (len(candidates) - 1) // (slots - 1)] for i in range(slots)]
        else:
            selected = []
        preview_indices = sorted(protected | set(selected))
    omitted_chord_endpoints = sorted(selected_endpoint_indices - set(preview_indices))
    # A uniform index sample may hide the actual extent of a coral scan.
    # Compare raw source-axis extrema before scaling to avoid float rounding.
    # This is display QC, not registration or biological completeness.
    preview_omitted_axis_extrema: list[str] = []
    for axis, label in enumerate(("x", "y", "z")):
        source_values = [vertex[axis] for vertex in vertices]
        sampled_values = [vertices[index][axis] for index in preview_indices]
        if min(sampled_values) != min(source_values):
            preview_omitted_axis_extrema.append(f"{label}_min")
        if max(sampled_values) != max(source_values):
            preview_omitted_axis_extrema.append(f"{label}_max")
    preview_points = []
    for index in preview_indices:
        preview_points.append([coordinate * scale for coordinate in vertices[index]])
    return {
        "schema_version": "point-cloud-preview-0001",
        "point_count": len(vertices),
        "unique_point_count": unique_count,
        "preview_point_indices": preview_indices,
        "preview_extrema_source_indices": extrema_indices,
        "preview_sampling_strategy": (
            "uniform_index_extrema_and_chord_endpoints_preserving"
            if preserve_axis_extrema_in_preview and pin_chords
            else "uniform_index_extrema_preserving"
            if preserve_axis_extrema_in_preview
            else "uniform_index_chord_endpoints_preserving"
            if pin_chords
            else "uniform_index"
        ),
        "preview_omitted_selected_chord_endpoint_indices": omitted_chord_endpoints,
        "preview_selected_chord_endpoints_covered": not omitted_chord_endpoints,
        "preview_omitted_axis_extrema": preview_omitted_axis_extrema,
        "preview_axis_extrema_covered": not preview_omitted_axis_extrema,
        "preview_points_in_source_frame_m": preview_points,
        "selected_point_chords": selected_chords,
        "selected_point_chord_qc_summary": {
            "requested_chords": len(selected_chords),
            "distinct_source_index_pairs": len(seen_point_pairs),
            "distinct_endpoint_geometries": len(seen_endpoint_geometry),
            "coincident_endpoint_chords": coincident_selected_chord_count,
        },
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
        "qc_warnings": (
            (["duplicate_points_present"] if unique_count < len(vertices) else [])
            + (["preview_omits_axis_extrema"] if preview_omitted_axis_extrema else [])
            + (["preview_omits_selected_chord_endpoints"] if omitted_chord_endpoints else [])
            + (["repeated_selected_point_pairs"] if repeated_selected_point_pairs else [])
            + (["coincident_selected_chord_endpoints"] if coincident_selected_chord_count else [])
            + (
                ["repeated_selected_endpoint_geometry"]
                if repeated_selected_endpoint_geometry
                else []
            )
        ),
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
    point_colors: list[list[int]] = []
    if payload.ply_text is not None:
        points = parse_ascii_ply_points(payload.ply_text, colors_out=point_colors)
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
        preserve_axis_extrema_in_preview=payload.preserve_axis_extrema_in_preview,
        preserve_measured_chord_endpoints_in_preview=(
            payload.preserve_measured_chord_endpoints_in_preview
        ),
    )
    result["preview_point_colors_rgb_uint8"] = (
        [point_colors[i] for i in result["preview_point_indices"]] if point_colors else None
    )
    result["provenance"]["source_format"] = source_format
    observed_at_utc = (
        payload.observed_at_utc.astimezone(UTC).isoformat().replace("+00:00", "Z")
        if payload.observed_at_utc is not None
        else None
    )
    result["provenance"].update(
        specimen_id=payload.specimen_id,
        observation_id=payload.observation_id,
        observed_at_utc=observed_at_utc,
        coordinate_frame_id=payload.coordinate_frame_id,
        specimen_identity_verified=False,
        observation_metadata_verified=False,
    )
    # Hash the received PLY text (including RGB) separately from XYZ geometry.
    # This is not a digest of the original on-disk file or a verification mark.
    result["provenance"]["source_text_sha256"] = (
        hashlib.sha256(payload.ply_text.encode("utf-8")).hexdigest()
        if payload.ply_text is not None
        else None
    )
    return result
