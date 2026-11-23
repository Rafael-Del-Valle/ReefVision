"""Bounded, unverified XYZ point-cloud preview (no inferred surface)."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC
from decimal import Decimal
from fractions import Fraction
from itertools import pairwise
from math import dist, fsum, isfinite
from re import fullmatch
from typing import Any

from reefvision.schemas.spatial_mesh_preview_v14 import MeshCalibrationReviewEvidence
from reefvision.services.spatial_mesh_obj_v14 import MAX_VERTICES
from reefvision.services.spatial_mesh_ply_v14 import (
    PlyFloat32RangeError,
    validate_ply_float32_range,
)

MAX_PLY_BYTES = 256_000
MAX_PREVIEW_POINTS = 512
# ASCII PLY numeric grammar: Python float() also accepts non-PLY underscores.
_PLY_FLOAT_TOKEN = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"


def _scale_interval_unresolved(
    nominal: float, uncertainty: float, lower: float, upper: float
) -> bool:
    """Flag rounding that falsely reports zero bounds or exact scale certainty."""
    return nominal != 0.0 and (
        (uncertainty < 1.0 and (lower == 0.0 or upper == 0.0))
        or (uncertainty > 0.0 and lower == upper)
    )


def _source_affine_dimension(vertices: list[tuple[float, float, float]]) -> int:
    """Exact imported-coordinate affine rank, not verified organism dimensions.

    Convert finite binary floats to rational values before differencing to
    avoid underflow of near-collinear/near-planar spatial predicates.
    """
    origin = tuple(Fraction(value) for value in vertices[0])
    direction: tuple[Fraction, Fraction, Fraction] | None = None
    normal: tuple[Fraction, Fraction, Fraction] | None = None
    for vertex in vertices[1:]:
        vector = (
            Fraction(vertex[0]) - origin[0],
            Fraction(vertex[1]) - origin[1],
            Fraction(vertex[2]) - origin[2],
        )
        if not any(vector):
            continue
        if direction is None:
            direction = vector
            continue
        if normal is None:
            candidate = (
                direction[1] * vector[2] - direction[2] * vector[1],
                direction[2] * vector[0] - direction[0] * vector[2],
                direction[0] * vector[1] - direction[1] * vector[0],
            )
            if any(candidate):
                normal = candidate
            continue
        if sum(normal[axis] * vector[axis] for axis in range(3)) != 0:
            return 3
    if normal is not None:
        return 2
    return 1 if direction is not None else 0


def parse_ascii_ply_points(
    text: str, *, colors_out: list[list[int]] | None = None
) -> list[list[float]]:
    """Read XYZ and optionally retain validated raw PLY RGB bytes."""
    # ASCII PLY has one byte per character. Check the scalar text before
    # attempting any UTF-8 encoding: JSON permits unpaired UTF-16 surrogates,
    # which cannot be encoded and must fail as a controlled input error.
    if not isinstance(text, str) or len(text) > MAX_PLY_BYTES:
        raise ValueError("Point-cloud PLY exceeds the 256000-byte preview limit")
    if not text.isascii():
        raise ValueError("Point-cloud PLY must contain ASCII text only")
    # splitlines()/split() treat vertical tabs and other control bytes as
    # separators. Reject them before parsing to preserve the source grammar.
    if any(
        (ord(character) < 32 and character not in "\t\n\r") or ord(character) == 127
        for character in text
    ):
        raise ValueError("Point-cloud PLY contains unsupported control characters")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "ply":
        raise ValueError("Point-cloud PLY must begin with ply")
    format_seen = False
    vertex_count: int | None = None
    properties: list[str] = []
    property_types: list[str] = []
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
            # int() accepts Python-specific underscores; PLY counts do not.
            count_token = parts[2]
            if not count_token.isdecimal() or len(count_token) > 9:
                raise ValueError("Invalid point-cloud vertex count")
            vertex_count = int(count_token)
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
            property_types.append(property_type)
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
    # Distinct source decimals must not silently become identical binary64
    # coordinates and fabricate duplicate observations or a zero axis span.
    source_decimals_by_axis: list[dict[float, Decimal]] = [{}, {}, {}]
    for row in rows:
        values = row.split()
        if len(values) != len(properties):
            raise ValueError("Point-cloud PLY vertex does not match header properties")
        tokens = [values[index] for index in xyz]
        if any(fullmatch(_PLY_FLOAT_TOKEN, token) is None for token in tokens):
            raise ValueError("Invalid point-cloud coordinate")
        try:
            parsed = [float(token) for token in tokens]
        except (ValueError, OverflowError) as exc:
            raise ValueError("Invalid point-cloud coordinate") from exc
        # A nonzero decimal that rounds to zero would silently collapse
        # reconstructed geometry. Reject it rather than claim a measured zero.
        for token, value, index in zip(tokens, parsed, xyz, strict=True):
            mantissa = token.lower().split("e", 1)[0]
            if value == 0.0 and any(digit in "123456789" for digit in mantissa):
                if property_types[index] in {"float", "float32"}:
                    raise PlyFloat32RangeError("PLY float32 value underflows declared range")
                raise ValueError("Point-cloud coordinate underflows float precision")
        for index, value in zip(xyz, parsed, strict=True):
            if property_types[index] in {"float", "float32"}:
                validate_ply_float32_range(value)
        if any(not isfinite(value) or abs(value) > 1_000_000_000 for value in parsed):
            raise ValueError("Point-cloud coordinates must be finite and bounded")
        for axis, (token, value) in enumerate(zip(tokens, parsed, strict=True)):
            exact_decimal = Decimal(token)
            previous = source_decimals_by_axis[axis].get(value)
            if previous is not None and previous != exact_decimal:
                raise ValueError(
                    "Distinct point-cloud decimal coordinates collapse at float64 precision"
                )
            source_decimals_by_axis[axis][value] = exact_decimal
        for channel in ("red", "green", "blue"):
            if channel in properties:
                token = values[properties.index(channel)]
                if (
                    not token.isascii()
                    or not token.isdecimal()
                    or len(token) > 3
                    or int(token) > 255
                ):
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
    preserve_largest_axis_gap_boundaries_in_preview: bool = False,
    preserve_largest_axis_gap_boundary_loci_in_preview: bool = False,
    preserve_distinct_xyz_loci_in_preview: bool = False,
    point_colors: list[list[int]] | None = None,
    preserve_distinct_xyz_rgb_pairs_in_preview: bool = False,
) -> dict[str, Any]:
    """Report point extents, not surface area, organism size, or branch length."""
    if not 1 <= len(points) <= MAX_VERTICES:
        raise ValueError("Point-cloud size outside preview bounds")
    if not isinstance(preserve_axis_extrema_in_preview, bool):
        raise ValueError("preserve_axis_extrema_in_preview must be a boolean")
    if not isinstance(preserve_measured_chord_endpoints_in_preview, bool):
        raise ValueError("preserve_measured_chord_endpoints_in_preview must be a boolean")
    if not isinstance(preserve_largest_axis_gap_boundaries_in_preview, bool):
        raise ValueError("preserve_largest_axis_gap_boundaries_in_preview must be a boolean")
    if not isinstance(preserve_largest_axis_gap_boundary_loci_in_preview, bool):
        raise ValueError("preserve_largest_axis_gap_boundary_loci_in_preview must be a boolean")
    if not isinstance(preserve_distinct_xyz_loci_in_preview, bool):
        raise ValueError("preserve_distinct_xyz_loci_in_preview must be a boolean")
    if not isinstance(preserve_distinct_xyz_rgb_pairs_in_preview, bool):
        raise ValueError("preserve_distinct_xyz_rgb_pairs_in_preview must be a boolean")
    # Enforce the raw uint8 RGB contract even for direct service callers that
    # do not request color-pair pinning. A malformed sensor observation must
    # never be silently treated as valid acquisition evidence.
    if point_colors is not None and (
        not isinstance(point_colors, list)
        or len(point_colors) != len(points)
        or any(
            not isinstance(rgb, (list, tuple))
            or len(rgb) != 3
            or any(type(channel) is not int or not 0 <= channel <= 255 for channel in rgb)
            for rgb in point_colors
        )
    ):
        raise ValueError("Point colors must have one uint8 RGB triplet per source row")
    if preserve_distinct_xyz_rgb_pairs_in_preview and point_colors is None:
        raise ValueError("RGB-pair preservation requires a colored PLY point cloud")
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
        # IEEE-754 signed zero is not a geometric distinction. Normalize it
        # before ordered/unordered and selected-chord geometry fingerprints;
        # exact imported PLY text retains its separate byte-level digest.
        # Keep the fixed-length coordinate tuple explicit for static typing:
        # there must be exactly three normalized axes, never a variadic tuple.
        xyz: tuple[float, float, float] = (
            0.0 if point[0] == 0.0 else float(point[0]),
            0.0 if point[1] == 0.0 else float(point[1]),
            0.0 if point[2] == 0.0 else float(point[2]),
        )
        # Calibration must not turn a nonzero source coordinate into an
        # apparently measured zero. Subnormal scales are otherwise valid, but
        # a lost coordinate also corrupts preview points, centroids, and chords.
        if any(value != 0.0 and value * scale == 0.0 for value in xyz):
            raise ValueError("Nonzero point-cloud coordinate underflows after calibration")
        vertices.append(xyz)
    # Reject a collapsed cloud-wide span before evaluating optional chords. A
    # two-point cloud can violate both contracts, and the primary extent error
    # must retain its established diagnostic while wider clouds still exercise
    # the more specific selected-chord guard below.
    source_bounds_min = [min(p[axis] for p in vertices) for axis in range(3)]
    source_bounds_max = [max(p[axis] for p in vertices) for axis in range(3)]
    dimensions = [(source_bounds_max[axis] - source_bounds_min[axis]) * scale for axis in range(3)]
    bounds_min = [value * scale for value in source_bounds_min]
    bounds_max = [value * scale for value in source_bounds_max]
    if any(
        source_bounds_max[axis] > source_bounds_min[axis]
        and (dimensions[axis] == 0.0 or bounds_min[axis] == bounds_max[axis])
        for axis in range(3)
    ):
        raise ValueError("Nonzero point-cloud axis span collapses after calibration")
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
    selected_chord_interval_underflow = False
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
            # Global cloud extents can remain resolvable while a selected pair
            # loses its smaller separation. Distinct source geometry must never
            # become an apparently zero or coincident measured chord.
            if endpoints[0] != endpoints[1] and (
                chord_m == 0.0
                or all(
                    left * scale == right * scale for left, right in zip(*endpoints, strict=True)
                )
            ):
                raise ValueError("Distinct selected chord endpoints collapse after calibration")
            # Different indices can still identify identical XYZ coordinates.
            # Flag a zero-length chord instead of implying biological structure.
            chord_qc_warnings: list[str] = []
            # A positive chord and positive lower scale factor must not
            # acquire a false zero lower distance from floating-point underflow.
            # Preserve the nominal chord and mark its interval unresolved.
            chord_interval_underflow = (
                relative_scale_uncertainty is not None
                and _scale_interval_unresolved(
                    chord_m,
                    relative_scale_uncertainty,
                    chord_m * (1 - relative_scale_uncertainty),
                    chord_m * (1 + relative_scale_uncertainty),
                )
            )
            if chord_interval_underflow:
                chord_qc_warnings.append("chord_uncertainty_interval_below_numeric_resolution")
                selected_chord_interval_underflow = True
            # An unresolved scale interval cannot supply a trustworthy
            # absolute uncertainty, even if floating point rounds it to zero.
            chord_scale_uncertainty_m = (
                chord_m * relative_scale_uncertainty
                if relative_scale_uncertainty is not None
                else None
            )
            if chord_interval_underflow:
                chord_scale_uncertainty_m = None
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
                        if relative_scale_uncertainty is not None and not chord_interval_underflow
                        else None
                    ),
                    "scale_uncertainty_m": chord_scale_uncertainty_m,
                }
            )
    # A positive calibrated extent with positive lower scale factor must not
    # claim zero lower uncertainty solely because floating-point precision
    # cannot represent the product. A truly planar axis stays [0, 0].
    dimension_scale_interval_underflow = False
    dimension_scale_intervals: list[list[float] | None] | None = None
    if relative_scale_uncertainty is not None:
        dimension_scale_intervals = []
        for dimension in dimensions:
            lower = dimension * (1 - relative_scale_uncertainty)
            upper = dimension * (1 + relative_scale_uncertainty)
            if _scale_interval_unresolved(dimension, relative_scale_uncertainty, lower, upper):
                dimension_scale_interval_underflow = True
                dimension_scale_intervals.append(None)
            else:
                dimension_scale_intervals.append([lower, upper])
    # Divide only after calibration and compensated summation: dividing a
    # positive subnormal source mean first can round it to zero even when its
    # calibrated centroid is representable. A point centroid is not a tissue
    # centroid or a verified organism position.
    centroid = [
        fsum(point[axis] * scale for point in vertices) / len(vertices) for axis in range(3)
    ]
    diagonal = dist((0.0, 0.0, 0.0), dimensions)
    # A calibrated diagonal may remain representable even when its scale-only
    # uncertainty interval is rounded to a false point interval. Do not report
    # zero-width uncertainty from limited floating-point resolution.
    diagonal_scale_interval_underflow = False
    diagonal_scale_interval: list[float] | None = None
    if relative_scale_uncertainty is not None:
        lower = diagonal * (1 - relative_scale_uncertainty)
        upper = diagonal * (1 + relative_scale_uncertainty)
        if _scale_interval_unresolved(diagonal, relative_scale_uncertainty, lower, upper):
            diagonal_scale_interval_underflow = True
        else:
            diagonal_scale_interval = [lower, upper]
    # Multiply larger extents first: multiplying two tiny axes before a
    # large third axis can underflow to zero even when the final positive
    # envelope volume is representable. This remains a bounding envelope,
    # not an estimate of biological tissue volume.
    envelope_product = 1.0
    for dimension in sorted(dimensions, reverse=True):
        envelope_product *= dimension
    envelope_volume: float | None = envelope_product
    # Three representable dimensions may still have a product too small for
    # floating point. Report this as unknown rather than falsely claiming a
    # zero-volume (planar) cloud. Keep the independently valid dimensions.
    envelope_volume_underflow = (
        all(dimension > 0.0 for dimension in dimensions) and envelope_volume == 0.0
    )
    if envelope_volume_underflow:
        envelope_volume = None
    # A positive envelope with a nonzero lower scale factor must not acquire
    # a zero lower bound solely from subnormal floating-point rounding. Treat
    # the uncertainty interval as unrepresentable rather than claiming a
    # physically possible zero-volume lower limit.
    envelope_scale_interval_underflow = False
    envelope_scale_interval: list[float] | None = None
    if relative_scale_uncertainty is not None and envelope_volume is not None:
        lower = envelope_volume * (1 - relative_scale_uncertainty) ** 3
        upper = envelope_volume * (1 + relative_scale_uncertainty) ** 3
        # Quantized positive bounds may also become identical even when
        # the caller supplied nonzero scale uncertainty. Never claim a
        # precise zero-width scale-uncertainty interval at float resolution.
        if envelope_volume > 0.0 and (
            (relative_scale_uncertainty < 1.0 and lower == 0.0)
            or (relative_scale_uncertainty > 0.0 and lower == upper)
        ):
            envelope_scale_interval_underflow = True
        else:
            envelope_scale_interval = [lower, upper]

    # A nonzero signed source-frame coordinate must not acquire a false zero
    # uncertainty bound from floating-point underflow. Preserve the other
    # representable axes, including genuine zero coordinates.
    coordinate_scale_interval_underflow = False

    def coordinate_scale_intervals(bounds: list[float]) -> list[list[float] | None] | None:
        nonlocal coordinate_scale_interval_underflow
        if relative_scale_uncertainty is None:
            return None
        intervals: list[list[float] | None] = []
        for value in bounds:
            candidates = (
                value * (1 - relative_scale_uncertainty),
                value * (1 + relative_scale_uncertainty),
            )
            if _scale_interval_unresolved(value, relative_scale_uncertainty, *candidates):
                coordinate_scale_interval_underflow = True
                intervals.append(None)
            else:
                intervals.append([min(candidates), max(candidates)])
        return intervals

    coordinate_multiplicities = Counter(vertices)
    # For each bounding-box face, distinguish repeated acquisition rows from
    # distinct observed XYZ loci supporting that extremum. This is evidence
    # about how a measured extent was obtained, not proof the extrema represent
    # biological boundaries or independent observations.
    axis_extrema_support: dict[str, dict[str, int]] = {}
    for axis, label in enumerate(("x", "y", "z")):
        minimum = source_bounds_min[axis]
        maximum = source_bounds_max[axis]
        minimum_counts = [
            count for xyz, count in coordinate_multiplicities.items() if xyz[axis] == minimum
        ]
        maximum_counts = [
            count for xyz, count in coordinate_multiplicities.items() if xyz[axis] == maximum
        ]
        axis_extrema_support[label] = {
            "minimum_source_rows": sum(minimum_counts),
            "minimum_distinct_xyz_loci": len(minimum_counts),
            "maximum_source_rows": sum(maximum_counts),
            "maximum_distinct_xyz_loci": len(maximum_counts),
        }
    unique_count = len(coordinate_multiplicities)
    duplicate_row_count = len(vertices) - unique_count
    maximum_coordinate_multiplicity = max(coordinate_multiplicities.values())
    # Raw scan rows are not independent organisms or necessarily independent
    # spatial observations. Keep the existing row-weighted centroid, but
    # contrast it with a centroid counting each distinct XYZ location once.
    # Neither is a validated tissue centroid or verified organism position.
    unique_coordinate_centroid = [
        fsum(point[axis] * scale for point in coordinate_multiplicities) / unique_count
        for axis in range(3)
    ]
    centroid_separation = dist(centroid, unique_coordinate_centroid)
    if len(set(coordinate_multiplicities.values())) == 1:
        # Equal multiplicities cannot move the mathematical centroid. Avoid
        # a false difference from independent floating-point summation paths.
        centroid_separation = 0.0
    centroid_separation_scale_interval: list[float] | None = None
    centroid_separation_interval_unresolved = False
    if relative_scale_uncertainty is not None:
        lower = centroid_separation * (1 - relative_scale_uncertainty)
        upper = centroid_separation * (1 + relative_scale_uncertainty)
        if _scale_interval_unresolved(
            centroid_separation, relative_scale_uncertainty, lower, upper
        ):
            centroid_separation_interval_unresolved = True
        else:
            centroid_separation_scale_interval = [lower, upper]
    source_affine_dimension = _source_affine_dimension(vertices)
    # Largest *axis-projected* gap between consecutive distinct observed
    # coordinate levels. This is a scan-sampling diagnostic, not an empty
    # three-dimensional region, missing coral tissue or biological branch gap.
    # Duplicated acquisition rows must not masquerade as extra coverage.
    axis_sampling_gaps: dict[str, dict[str, Any]] = {}
    sampling_gap_nominal_underflow = False
    sampling_gap_interval_unresolved = False
    multiple_tied_largest_axis_gaps = False
    for axis, label in enumerate(("x", "y", "z")):
        level_source_rows = Counter(vertex[axis] for vertex in vertices)
        level_distinct_loci = Counter(vertex[axis] for vertex in coordinate_multiplicities)
        levels = sorted(level_source_rows)
        gap_details: dict[str, Any] = {
            "distinct_source_coordinate_levels": len(levels),
            "source_endpoint_values": None,
            "gap_endpoint_support": None,
            "equally_largest_adjacent_gap_count": 0,
            "largest_adjacent_source_gap_units": None,
            "fraction_of_source_axis_span": None,
            "calibrated_gap_m": None,
            "calibrated_gap_scale_interval_m": None,
        }
        if len(levels) > 1:
            # max() keeps the lower-coordinate interval when two gaps tie.
            largest_index = max(
                range(len(levels) - 1),
                key=lambda index: levels[index + 1] - levels[index],
            )
            left = levels[largest_index]
            right = levels[largest_index + 1]
            gap = right - left
            # Report exact source-coordinate ties instead of implying that
            # the representative lower-coordinate interval is the only one.
            # This does not imply empty 3D space or biological tissue loss.
            tied_count = sum(
                levels[index + 1] - levels[index] == gap for index in range(len(levels) - 1)
            )
            gap_details["equally_largest_adjacent_gap_count"] = tied_count
            if tied_count > 1:
                multiple_tied_largest_axis_gaps = True
            gap_details["source_endpoint_values"] = [left, right]
            # Count raw acquisition rows separately from distinct observed
            # XYZ loci. Neither is an independent biological replicate nor
            # evidence of missing coral tissue.
            gap_details["gap_endpoint_support"] = {
                "lower": {
                    "source_rows": level_source_rows[left],
                    "distinct_xyz_loci": level_distinct_loci[left],
                },
                "upper": {
                    "source_rows": level_source_rows[right],
                    "distinct_xyz_loci": level_distinct_loci[right],
                },
            }
            gap_details["largest_adjacent_source_gap_units"] = gap
            gap_details["fraction_of_source_axis_span"] = gap / (levels[-1] - levels[0])
            gap_m = gap * scale
            if gap_m == 0.0:
                # Do not describe a positive gap as a measured zero.
                sampling_gap_nominal_underflow = True
            else:
                gap_details["calibrated_gap_m"] = gap_m
                if relative_scale_uncertainty is not None:
                    lower = gap_m * (1 - relative_scale_uncertainty)
                    upper = gap_m * (1 + relative_scale_uncertainty)
                    if _scale_interval_unresolved(gap_m, relative_scale_uncertainty, lower, upper):
                        sampling_gap_interval_unresolved = True
                    else:
                        gap_details["calibrated_gap_scale_interval_m"] = [lower, upper]
        axis_sampling_gaps[label] = gap_details
    # Even a tilted line or plane can span a positive axis-aligned 3D box.
    # Keep the mathematically valid envelope but explicitly prohibit readers
    # from confusing its positive volume with occupied three-dimensional space.
    positive_envelope_for_lower_dimensional_source = (
        source_affine_dimension < 3 and envelope_volume is not None and envelope_volume > 0.0
    )
    geometry_hash = hashlib.sha256(
        json.dumps(sorted(vertices), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    # Compare exact observed XYZ loci independently of acquisition row
    # multiplicity. This hash is not a registered specimen identity, and
    # calibration reviews must still bind the full source geometry hash.
    unique_coordinate_geometry_hash = hashlib.sha256(
        json.dumps(sorted(coordinate_multiplicities), separators=(",", ":")).encode("utf-8")
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
    # The full-source gap analysis above is independent of display sampling.
    # A user may explicitly retain one acquisition row at each distinct
    # boundary coordinate level of every equally largest projected gap.
    # This does not retain every 3D locus or raw acquisition row there.
    gap_boundary_indices: set[int] = set()
    if (
        preserve_largest_axis_gap_boundaries_in_preview
        or preserve_largest_axis_gap_boundary_loci_in_preview
    ):
        for axis, label in enumerate(("x", "y", "z")):
            maximum_gap = axis_sampling_gaps[label]["largest_adjacent_source_gap_units"]
            if maximum_gap is None:
                continue
            levels = sorted({vertex[axis] for vertex in vertices})
            boundary_levels = {
                level
                for lower, upper in pairwise(levels)
                if upper - lower == maximum_gap
                for level in (lower, upper)
            }
            first_index_per_level: dict[float, int] = {}
            first_index_per_locus: dict[tuple[float, float, float], int] = {}
            for index, vertex in enumerate(vertices):
                coordinate = vertex[axis]
                if coordinate not in boundary_levels:
                    continue
                if preserve_largest_axis_gap_boundaries_in_preview:
                    first_index_per_level.setdefault(coordinate, index)
                if preserve_largest_axis_gap_boundary_loci_in_preview:
                    first_index_per_locus.setdefault(vertex, index)
            gap_boundary_indices.update(first_index_per_level.values())
            gap_boundary_indices.update(first_index_per_locus.values())
    # A bounded preview can lose a rare, genuinely observed XYZ locus while
    # spending hundreds of display slots on duplicate acquisition rows.
    # Explicitly pin one original row per distinct locus when requested.
    # Retaining locations does not imply independent biological replicates,
    # complete scan coverage, or retention of every acquisition row.
    distinct_locus_indices: set[int] = set()
    if preserve_distinct_xyz_loci_in_preview:
        first_index_per_xyz: dict[tuple[float, float, float], int] = {}
        for index, vertex in enumerate(vertices):
            first_index_per_xyz.setdefault(vertex, index)
        distinct_locus_indices.update(first_index_per_xyz.values())
    # Preserve each observed XYZ/RGB combination, not just one geometric
    # location: duplicate RGB observations need not consume display slots.
    # Color is provisional acquisition evidence, not classified coral health.
    distinct_rgb_pair_indices: set[int] = set()
    if preserve_distinct_xyz_rgb_pairs_in_preview:
        assert point_colors is not None
        first_index_per_pair: dict[tuple[tuple[float, float, float], tuple[int, ...]], int] = {}
        for index, (vertex, rgb) in enumerate(zip(vertices, point_colors, strict=True)):
            first_index_per_pair.setdefault((vertex, tuple(rgb)), index)
        distinct_rgb_pair_indices.update(first_index_per_pair.values())
    if (
        preserve_axis_extrema_in_preview
        or pin_chords
        or preserve_largest_axis_gap_boundaries_in_preview
        or preserve_largest_axis_gap_boundary_loci_in_preview
        or preserve_distinct_xyz_loci_in_preview
        or preserve_distinct_xyz_rgb_pairs_in_preview
    ) and len(vertices) > preview_count:
        # Complete distinct-locus retention has priority over the otherwise
        # conventional last acquisition row. With exactly 512 unique XYZ loci
        # and a duplicate final row, pinning that duplicate first would reject
        # a scientifically feasible 512-locus preview as "over budget".
        protected = (
            distinct_locus_indices | distinct_rgb_pair_indices
            if preserve_distinct_xyz_loci_in_preview or preserve_distinct_xyz_rgb_pairs_in_preview
            else {0, len(vertices) - 1}
        )
        if preserve_axis_extrema_in_preview:
            protected.update(extrema_indices)
        if pin_chords:
            protected.update(selected_endpoint_indices)
        protected.update(gap_boundary_indices)
        if len(protected) > preview_count:
            raise ValueError("Protected point indices exceed the display budget")
        # First acquisition row is already the first occurrence of one XYZ
        # locus. Preserve the last row when a display slot remains, but never
        # sacrifice a distinct observed locus to retain a duplicate endpoint.
        if (
            preserve_distinct_xyz_loci_in_preview or preserve_distinct_xyz_rgb_pairs_in_preview
        ) and len(protected) < preview_count:
            protected.add(len(vertices) - 1)
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
    # Display decimation can hide distinct imported XYZ loci even when it
    # preserves the bounding extrema. This is visualization completeness,
    # not a biological sampling or tissue-coverage estimate.
    preview_unique_coordinate_count = len({vertices[index] for index in preview_indices})
    preview_unique_coordinate_coverage_fraction = preview_unique_coordinate_count / unique_count
    preview_source_acquisition_endpoint_support = {
        "first_row_displayed": 0 in preview_indices,
        "last_row_displayed": len(vertices) - 1 in preview_indices,
    }
    # An exact display-sample fingerprint binds source-row indices and raw
    # normalized XYZ locations. Changing preview sampling can change this
    # digest without changing the full source cloud. It is NOT a biological
    # identity, registration, or calibration verification.
    preview_sample_geometry_sha256 = hashlib.sha256(
        json.dumps(
            [[index, *vertices[index]] for index in preview_indices],
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
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
    # Even when a bounded preview retains the source-axis extrema, it may
    # hide an endpoint of the largest observed scan-coordinate gap. Disclose
    # the display omission separately from the full-cloud measurement. A
    # missing endpoint is not evidence of missing coral tissue.
    preview_largest_axis_gap_endpoint_support: dict[str, dict[str, bool] | None] = {}
    for axis, label in enumerate(("x", "y", "z")):
        endpoints = axis_sampling_gaps[label]["source_endpoint_values"]
        sampled_levels = {vertices[index][axis] for index in preview_indices}
        preview_largest_axis_gap_endpoint_support[label] = (
            {
                "lower": endpoints[0] in sampled_levels,
                "upper": endpoints[1] in sampled_levels,
            }
            if endpoints is not None
            else None
        )
    # When multiple source-coordinate intervals tie for the largest gap,
    # checking only the representative lowest-coordinate pair can hide an
    # omitted boundary elsewhere in the display. Count every maximal interval
    # using distinct source levels (not duplicated acquisition rows).
    preview_largest_axis_gap_interval_coverage: dict[str, dict[str, int] | None] = {}
    preview_largest_axis_gap_boundary_locus_support: dict[str, dict[str, int | float] | None] = {}
    for axis, label in enumerate(("x", "y", "z")):
        maximum_gap = axis_sampling_gaps[label]["largest_adjacent_source_gap_units"]
        if maximum_gap is None:
            preview_largest_axis_gap_interval_coverage[label] = None
            preview_largest_axis_gap_boundary_locus_support[label] = None
            continue
        source_levels = sorted({vertex[axis] for vertex in vertices})
        sampled_levels = {vertices[index][axis] for index in preview_indices}
        full = partial = hidden = 0
        largest_gap_boundary_levels: set[float] = set()
        for lower, upper in pairwise(source_levels):
            if upper - lower != maximum_gap:
                continue
            largest_gap_boundary_levels.update((lower, upper))
            visible_count = int(lower in sampled_levels) + int(upper in sampled_levels)
            if visible_count == 2:
                full += 1
            elif visible_count == 1:
                partial += 1
            else:
                hidden += 1
        preview_largest_axis_gap_interval_coverage[label] = {
            "total_intervals": full + partial + hidden,
            "fully_displayed_intervals": full,
            "partially_displayed_intervals": partial,
            "hidden_intervals": hidden,
        }
        # Axis-level presence alone can conceal omitted, distinct 3D
        # acquisitions at the same projected gap boundary. Union all tied
        # boundary coordinate levels; do not count duplicated scan rows as
        # independent XYZ loci or infer biological completeness.
        # Raw acquisition rows must not be conflated with independent XYZ
        # locations: decimation can remove repeat observations while retaining
        # every distinct coordinate at a projected gap boundary.
        source_boundary_rows = sum(
            vertex[axis] in largest_gap_boundary_levels for vertex in vertices
        )
        preview_boundary_rows = sum(
            vertices[index][axis] in largest_gap_boundary_levels for index in preview_indices
        )
        source_boundary_loci = {
            vertex for vertex in vertices if vertex[axis] in largest_gap_boundary_levels
        }
        preview_boundary_loci = {
            vertices[index]
            for index in preview_indices
            if vertices[index][axis] in largest_gap_boundary_levels
        }
        preview_largest_axis_gap_boundary_locus_support[label] = {
            "source_acquisition_rows": source_boundary_rows,
            "preview_acquisition_rows": preview_boundary_rows,
            "fraction_of_source_rows_displayed": preview_boundary_rows / source_boundary_rows,
            "source_distinct_xyz_loci": len(source_boundary_loci),
            "preview_distinct_xyz_loci": len(preview_boundary_loci),
            "fraction_of_source_loci_displayed": (
                len(preview_boundary_loci) / len(source_boundary_loci)
            ),
        }
    preview_omitted_largest_gap_boundary_axes = [
        label
        for label, coverage in preview_largest_axis_gap_interval_coverage.items()
        if coverage is not None
        and coverage["fully_displayed_intervals"] != coverage["total_intervals"]
    ]
    preview_omitted_largest_gap_boundary_locus_axes = [
        label
        for label, support in preview_largest_axis_gap_boundary_locus_support.items()
        if support is not None
        and support["preview_distinct_xyz_loci"] < support["source_distinct_xyz_loci"]
    ]
    preview_omitted_largest_gap_boundary_acquisition_axes = [
        label
        for label, support in preview_largest_axis_gap_boundary_locus_support.items()
        if support is not None
        and support["preview_acquisition_rows"] < support["source_acquisition_rows"]
    ]
    preview_points = []
    for index in preview_indices:
        preview_points.append([coordinate * scale for coordinate in vertices[index]])
    # Compare the display sample's row-weighted centroid with the complete
    # acquisition's row-weighted centroid. This diagnoses preview sampling
    # displacement, NOT organism movement, tissue geometry or registration.
    # Reuse the full-source result when every acquisition row is displayed to
    # avoid numerical differences caused only by summation order.
    preview_row_centroid = (
        centroid
        if len(preview_indices) == len(vertices)
        else [
            fsum(vertices[index][axis] * scale for index in preview_indices) / len(preview_indices)
            for axis in range(3)
        ]
    )
    # Signed displacement of the displayed *sample* relative to all source
    # acquisition rows, in the source coordinate frame. Direction matters for
    # visualization bias, but is never evidence of organism motion or spatial
    # registration. A complete or single-locus sample has no sampling offset.
    preview_minus_source_centroid_offset = (
        [0.0, 0.0, 0.0]
        if len(preview_indices) == len(vertices) or unique_count == 1
        else [preview_row_centroid[axis] - centroid[axis] for axis in range(3)]
    )
    preview_centroid_separation = dist(centroid, preview_row_centroid)
    if unique_count == 1:
        preview_centroid_separation = 0.0
    # Signed per-axis sampling displacement has the same shared calibration
    # scale uncertainty as its magnitude, but negative components reverse
    # interval endpoints. A zero offset remains a genuine [0, 0] interval.
    # This is scale-only uncertainty, not sampling or registration uncertainty.
    preview_centroid_offset_scale_intervals: list[list[float] | None] | None = None
    preview_centroid_offset_interval_unresolved = False
    if relative_scale_uncertainty is not None:
        preview_centroid_offset_scale_intervals = []
        for offset in preview_minus_source_centroid_offset:
            offset_bound_candidates = (
                offset * (1 - relative_scale_uncertainty),
                offset * (1 + relative_scale_uncertainty),
            )
            offset_lower, offset_upper = (
                min(offset_bound_candidates),
                max(offset_bound_candidates),
            )
            if _scale_interval_unresolved(
                offset, relative_scale_uncertainty, offset_lower, offset_upper
            ):
                preview_centroid_offset_interval_unresolved = True
                preview_centroid_offset_scale_intervals.append(None)
            else:
                preview_centroid_offset_scale_intervals.append([offset_lower, offset_upper])
    preview_centroid_scale_interval: list[float] | None = None
    preview_centroid_interval_unresolved = False
    if relative_scale_uncertainty is not None:
        lower = preview_centroid_separation * (1 - relative_scale_uncertainty)
        upper = preview_centroid_separation * (1 + relative_scale_uncertainty)
        if _scale_interval_unresolved(
            preview_centroid_separation, relative_scale_uncertainty, lower, upper
        ):
            preview_centroid_interval_unresolved = True
        else:
            preview_centroid_scale_interval = [lower, upper]
    # The dimensionless fraction is valid only for a nonzero source envelope.
    # Shared scale uncertainty cancels; reconstruction and sampling uncertainty
    # are not evaluated by this ratio.
    preview_centroid_separation_fraction = (
        preview_centroid_separation / diagonal if diagonal > 0.0 else None
    )
    # Fingerprint every normalized, ordered XYZ/RGB acquisition row, including
    # color observations omitted from the 512-point preview. This supplements
    # geometry-only and exact-import-text hashes; it is not color calibration.
    source_ordered_xyz_rgb_sha256: str | None = None
    source_unordered_xyz_rgb_multiset_sha256: str | None = None
    if point_colors is not None:
        ordered_rgb_rows = [[*xyz, *rgb] for xyz, rgb in zip(vertices, point_colors, strict=True)]
        source_ordered_xyz_rgb_sha256 = hashlib.sha256(
            json.dumps(ordered_rgb_rows, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        # A sorted *multiset* retains repeated acquisition rows but ignores
        # arbitrary exporter row ordering. Unlike geometry-only provenance it
        # also detects changes in the observed RGB associated with each XYZ.
        # Equality is compatible acquisition evidence, not specimen re-ID.
        source_unordered_xyz_rgb_multiset_sha256 = hashlib.sha256(
            json.dumps(sorted(ordered_rgb_rows), separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    return {
        "schema_version": "point-cloud-preview-0001",
        "point_count": len(vertices),
        "unique_point_count": unique_count,
        "duplicate_point_row_count": duplicate_row_count,
        # Sampling redundancy is acquisition QC, not tissue coverage or identity.
        "duplicate_point_row_fraction": duplicate_row_count / len(vertices),
        "maximum_coordinate_multiplicity": maximum_coordinate_multiplicity,
        "source_affine_dimension": source_affine_dimension,
        "preview_point_indices": preview_indices,
        "preview_sample_geometry_sha256": preview_sample_geometry_sha256,
        "preview_unique_coordinate_count": preview_unique_coordinate_count,
        "preview_unique_coordinate_coverage_fraction": (
            preview_unique_coordinate_coverage_fraction
        ),
        "preview_source_acquisition_endpoint_support": (
            preview_source_acquisition_endpoint_support
        ),
        "preview_extrema_source_indices": extrema_indices,
        "preview_sampling_strategy": (
            (
                "uniform_index_extrema_and_chord_endpoints_preserving"
                if preserve_axis_extrema_in_preview and pin_chords
                else "uniform_index_extrema_preserving"
                if preserve_axis_extrema_in_preview
                else "uniform_index_chord_endpoints_preserving"
                if pin_chords
                else "uniform_index"
            )
            + (
                "_largest_gap_boundaries_preserving"
                if preserve_largest_axis_gap_boundaries_in_preview
                else ""
            )
            + (
                "_largest_gap_boundary_loci_preserving"
                if preserve_largest_axis_gap_boundary_loci_in_preview
                else ""
            )
            + ("_distinct_xyz_loci_preserving" if preserve_distinct_xyz_loci_in_preview else "")
            + (
                "_distinct_xyz_rgb_pairs_preserving"
                if preserve_distinct_xyz_rgb_pairs_in_preview
                else ""
            )
        ),
        "preview_largest_axis_gap_boundary_loci_preservation_requested": (
            preserve_largest_axis_gap_boundary_loci_in_preview
        ),
        "preview_largest_axis_gap_boundaries_preservation_requested": (
            preserve_largest_axis_gap_boundaries_in_preview
        ),
        "preview_distinct_xyz_loci_preservation_requested": preserve_distinct_xyz_loci_in_preview,
        "preview_distinct_xyz_rgb_pairs_preservation_requested": (
            preserve_distinct_xyz_rgb_pairs_in_preview
        ),
        "preview_omitted_selected_chord_endpoint_indices": omitted_chord_endpoints,
        "preview_selected_chord_endpoints_covered": not omitted_chord_endpoints,
        "preview_omitted_axis_extrema": preview_omitted_axis_extrema,
        "preview_axis_extrema_covered": not preview_omitted_axis_extrema,
        # Representative boundary visibility remains available for legacy
        # consumers; the interval coverage and warning consider *all* ties.
        "preview_largest_axis_gap_endpoint_support": preview_largest_axis_gap_endpoint_support,
        "preview_largest_axis_gap_interval_coverage": preview_largest_axis_gap_interval_coverage,
        "preview_largest_axis_gap_boundary_locus_support": (
            preview_largest_axis_gap_boundary_locus_support
        ),
        "preview_omitted_largest_gap_boundary_axes": preview_omitted_largest_gap_boundary_axes,
        "preview_omitted_largest_gap_boundary_locus_axes": (
            preview_omitted_largest_gap_boundary_locus_axes
        ),
        "preview_omitted_largest_gap_boundary_acquisition_axes": (
            preview_omitted_largest_gap_boundary_acquisition_axes
        ),
        "preview_points_in_source_frame_m": preview_points,
        "preview_point_scale_intervals_m": (
            [coordinate_scale_intervals(point) for point in preview_points]
            if relative_scale_uncertainty is not None
            else None
        ),
        "selected_point_chords": selected_chords,
        "selected_point_chord_qc_summary": {
            "requested_chords": len(selected_chords),
            "distinct_source_index_pairs": len(seen_point_pairs),
            "distinct_endpoint_geometries": len(seen_endpoint_geometry),
            "coincident_endpoint_chords": coincident_selected_chord_count,
        },
        "axis_aligned_dimensions_m": dimensions,
        "axis_extrema_support": axis_extrema_support,
        "axis_largest_adjacent_coordinate_gaps": axis_sampling_gaps,
        "axis_aligned_dimension_scale_interval_m": dimension_scale_intervals,
        "axis_aligned_min_in_source_frame_m": bounds_min,
        "axis_aligned_max_in_source_frame_m": bounds_max,
        "axis_aligned_min_in_source_frame_scale_interval_m": coordinate_scale_intervals(bounds_min),
        "axis_aligned_max_in_source_frame_scale_interval_m": coordinate_scale_intervals(bounds_max),
        "axis_aligned_bounding_box_diagonal_m": diagonal,
        "axis_aligned_bounding_box_diagonal_scale_interval_m": diagonal_scale_interval,
        "axis_aligned_bounding_box_envelope_volume_m3": envelope_volume,
        "axis_aligned_bounding_box_envelope_volume_scale_interval_m3": (envelope_scale_interval),
        # Match the per-axis scale intervals: an unresolved positive
        # uncertainty is unknown, never a physically exact zero. Keep genuine
        # zero dimensions and zero caller uncertainty as zero.
        "axis_aligned_dimension_scale_uncertainty_m": (
            [
                None if interval is None else value * relative_scale_uncertainty
                for value, interval in zip(dimensions, dimension_scale_intervals, strict=True)
            ]
            if relative_scale_uncertainty is not None and dimension_scale_intervals is not None
            else None
        ),
        "axis_aligned_bounding_box_diagonal_scale_uncertainty_m": (
            diagonal * relative_scale_uncertainty
            if relative_scale_uncertainty is not None and not diagonal_scale_interval_underflow
            else None
        ),
        "arithmetic_centroid_in_source_frame_m": centroid,
        "arithmetic_centroid_in_source_frame_scale_interval_m": coordinate_scale_intervals(
            centroid
        ),
        "preview_row_centroid_in_source_frame_m": preview_row_centroid,
        "preview_row_centroid_in_source_frame_scale_interval_m": coordinate_scale_intervals(
            preview_row_centroid
        ),
        "preview_minus_source_row_centroid_offset_m": preview_minus_source_centroid_offset,
        "preview_minus_source_row_centroid_offset_scale_interval_m": (
            preview_centroid_offset_scale_intervals
        ),
        "preview_vs_source_row_centroid_separation_m": preview_centroid_separation,
        "preview_vs_source_row_centroid_separation_scale_interval_m": (
            preview_centroid_scale_interval
        ),
        "preview_vs_source_row_centroid_separation_fraction_of_bbox_diagonal": (
            preview_centroid_separation_fraction
        ),
        "unique_coordinate_centroid_in_source_frame_m": unique_coordinate_centroid,
        "unique_coordinate_centroid_in_source_frame_scale_interval_m": (
            coordinate_scale_intervals(unique_coordinate_centroid)
        ),
        "row_vs_unique_coordinate_centroid_separation_m": centroid_separation,
        "row_vs_unique_coordinate_centroid_separation_scale_interval_m": (
            centroid_separation_scale_interval
        ),
        "surface_area_m2": None,
        "branch_length_m": None,
        "qc_warnings": (
            (["duplicate_points_present"] if duplicate_row_count else [])
            + (
                ["nonuniform_duplicate_coordinates_can_bias_row_centroid"]
                if duplicate_row_count and len(set(coordinate_multiplicities.values())) > 1
                else []
            )
            + (
                ["centroid_separation_uncertainty_interval_below_numeric_resolution"]
                if centroid_separation_interval_unresolved
                else []
            )
            + (
                ["preview_centroid_separation_uncertainty_interval_below_numeric_resolution"]
                if preview_centroid_interval_unresolved
                else []
            )
            + (
                ["preview_centroid_offset_uncertainty_interval_below_numeric_resolution"]
                if preview_centroid_offset_interval_unresolved
                else []
            )
            + (
                ["dimension_uncertainty_interval_below_numeric_resolution"]
                if dimension_scale_interval_underflow
                else []
            )
            + (
                ["coordinate_uncertainty_interval_below_numeric_resolution"]
                if coordinate_scale_interval_underflow
                else []
            )
            + (
                ["diagonal_uncertainty_interval_below_numeric_resolution"]
                if diagonal_scale_interval_underflow
                else []
            )
            + (["envelope_volume_below_numeric_resolution"] if envelope_volume_underflow else [])
            + (
                ["envelope_uncertainty_interval_below_numeric_resolution"]
                if envelope_scale_interval_underflow
                else []
            )
            + (
                ["preview_omits_unique_coordinate_loci"]
                if preview_unique_coordinate_count < unique_count
                else []
            )
            + (
                ["preview_omits_acquisition_endpoint_row"]
                if not all(preview_source_acquisition_endpoint_support.values())
                else []
            )
            + (["preview_omits_axis_extrema"] if preview_omitted_axis_extrema else [])
            + (
                ["preview_omits_largest_axis_gap_endpoint"]
                if preview_omitted_largest_gap_boundary_axes
                else []
            )
            + (
                ["preview_omits_largest_axis_gap_boundary_xyz_loci"]
                if preview_omitted_largest_gap_boundary_locus_axes
                else []
            )
            + (
                ["preview_omits_largest_axis_gap_boundary_acquisition_rows"]
                if preview_omitted_largest_gap_boundary_acquisition_axes
                else []
            )
            + (
                ["axis_sampling_multiple_equally_largest_gaps"]
                if multiple_tied_largest_axis_gaps
                else []
            )
            + (
                ["axis_sampling_gap_below_numeric_resolution"]
                if sampling_gap_nominal_underflow
                else []
            )
            + (
                ["axis_sampling_gap_uncertainty_interval_below_numeric_resolution"]
                if sampling_gap_interval_unresolved
                else []
            )
            + (["preview_omits_selected_chord_endpoints"] if omitted_chord_endpoints else [])
            + (
                ["selected_chord_uncertainty_interval_below_numeric_resolution"]
                if selected_chord_interval_underflow
                else []
            )
            + (["repeated_selected_point_pairs"] if repeated_selected_point_pairs else [])
            + (["coincident_selected_chord_endpoints"] if coincident_selected_chord_count else [])
            + (
                ["repeated_selected_endpoint_geometry"]
                if repeated_selected_endpoint_geometry
                else []
            )
            + (
                ["source_point_cloud_affine_dimension_below_3"]
                if source_affine_dimension < 3
                else []
            )
            + (
                ["positive_bounding_envelope_for_lower_dimensional_source"]
                if positive_envelope_for_lower_dimensional_source
                else []
            )
        ),
        "measurement_status": "caller_supplied_unverified",
        "provenance": {
            "geometry_sha256": geometry_hash,
            "unique_coordinate_geometry_sha256": unique_coordinate_geometry_hash,
            "ordered_geometry_sha256": hashlib.sha256(
                json.dumps(vertices, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "source_label": source_label,
            "source_ordered_xyz_rgb_sha256": source_ordered_xyz_rgb_sha256,
            "source_ordered_xyz_rgb_canonicalization": (
                "ordered_normalized_float64_xyz_uint8_rgb_compact_json_utf8_v1"
                if point_colors is not None
                else None
            ),
            "source_unordered_xyz_rgb_multiset_sha256": (source_unordered_xyz_rgb_multiset_sha256),
            "source_unordered_xyz_rgb_multiset_canonicalization": (
                "sorted_multiset_normalized_float64_xyz_uint8_rgb_compact_json_utf8_v1"
                if point_colors is not None
                else None
            ),
            "meters_per_mesh_unit": scale,
            "calibration_method": calibration_method,
            "calibration_evidence": calibration_evidence.strip(),
            "calibration_verified": False,
            "relative_scale_uncertainty": relative_scale_uncertainty,
            "coordinate_registration_verified": False,
            # A raw point-cloud service call has no identity-review evidence;
            # higher-level request metadata must not promote it implicitly.
            "specimen_identity_verified": False,
        },
    }


def preview_point_cloud_from_request(payload: Any) -> dict[str, Any]:
    point_colors: list[list[int]] = []
    if payload.ply_text is not None:
        # Validate the ASCII source before encoding it for provenance. Escaped
        # lone UTF-16 surrogates must fail as a controlled parser error, never
        # escape as UnicodeEncodeError before the standalone/workflow guards.
        points = parse_ascii_ply_points(payload.ply_text, colors_out=point_colors)
        source_bytes = payload.ply_text.encode("ascii")
        source_format = "ply_ascii_point_cloud"
    else:
        points = payload.points
        source_bytes = None
        source_format = "xyz_points"
    # Valid ASCII has identical byte-for-byte UTF-8 and ASCII digests. Preserve
    # the exact submitted PLY (including comments/RGB) in source provenance.
    source_sha256 = hashlib.sha256(source_bytes).hexdigest() if source_bytes is not None else None
    expected_sha256 = payload.expected_source_payload_sha256
    if expected_sha256 is not None and source_sha256 != expected_sha256:
        raise ValueError(
            "Imported point-cloud source SHA-256 does not match expected source payload"
        )
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
        preserve_largest_axis_gap_boundaries_in_preview=(
            payload.preserve_largest_axis_gap_boundaries_in_preview
        ),
        preserve_largest_axis_gap_boundary_loci_in_preview=(
            payload.preserve_largest_axis_gap_boundary_loci_in_preview
        ),
        preserve_distinct_xyz_loci_in_preview=payload.preserve_distinct_xyz_loci_in_preview,
        point_colors=point_colors if point_colors else None,
        preserve_distinct_xyz_rgb_pairs_in_preview=(
            payload.preserve_distinct_xyz_rgb_pairs_in_preview
        ),
    )
    result["preview_point_colors_rgb_uint8"] = (
        [point_colors[i] for i in result["preview_point_indices"]] if point_colors else None
    )
    # Colored PLY points may contain several observed RGB values at the same
    # XYZ location. Geometry-only display preservation can hide a rare color
    # observation; never equate an XYZ-complete preview with RGB completeness
    # or interpret RGB variation as independently verified coral condition.
    if point_colors:
        source_pairs = {
            (tuple(point), tuple(rgb)) for point, rgb in zip(points, point_colors, strict=True)
        }
        preview_pairs = {
            (tuple(points[index]), tuple(point_colors[index]))
            for index in result["preview_point_indices"]
        }
        # Count raw RGB triplet coverage independently of XYZ/RGB pairing.
        # A display can omit a source color even when sampled channel extrema
        # look complete; missing raw colors are NOT evidence of coral condition.
        source_rgb_triplets = {tuple(rgb) for rgb in point_colors}
        preview_rgb_triplets = {
            tuple(point_colors[index]) for index in result["preview_point_indices"]
        }
        # Repeated acquisition rows are not additional distinct XYZ/RGB
        # observations. Report their multiplicity without deciding whether
        # independent sensor acquisitions or biological replicates occurred.
        repeated_source_pair_rows = len(points) - len(source_pairs)
        repeated_preview_pair_rows = len(result["preview_point_indices"]) - len(preview_pairs)
        # Pair coverage alone obscures sampling bias: a preview can retain
        # every distinct XYZ/RGB observation while changing its frequency.
        # Compare full acquisition-row and displayed-row distributions using
        # integer cross-products, avoiding floating-point equality artifacts.
        source_pair_counts: dict[tuple[tuple[float, ...], tuple[int, ...]], int] = {}
        source_rgb_counts: dict[tuple[int, ...], int] = {}
        for point, rgb in zip(points, point_colors, strict=True):
            pair = (tuple(point), tuple(rgb))
            source_pair_counts[pair] = source_pair_counts.get(pair, 0) + 1
            color = tuple(rgb)
            source_rgb_counts[color] = source_rgb_counts.get(color, 0) + 1
        preview_pair_counts: dict[tuple[tuple[float, ...], tuple[int, ...]], int] = {}
        preview_rgb_counts: dict[tuple[int, ...], int] = {}
        for index in result["preview_point_indices"]:
            pair = (tuple(points[index]), tuple(point_colors[index]))
            preview_pair_counts[pair] = preview_pair_counts.get(pair, 0) + 1
            color = tuple(point_colors[index])
            preview_rgb_counts[color] = preview_rgb_counts.get(color, 0) + 1
        represented_source_rows = sum(source_pair_counts[pair] for pair in preview_pairs)
        displayed_row_count = len(result["preview_point_indices"])
        frequency_shift_numerator = sum(
            abs(source_count * displayed_row_count - preview_pair_counts.get(pair, 0) * len(points))
            for pair, source_count in source_pair_counts.items()
        )
        # Preserve a reduced exact rational witness alongside the float:
        # scans with rare observations can round a small nonzero shift in
        # floating-point output; researchers can audit the count-based result.
        frequency_total_variation_exact = Fraction(
            frequency_shift_numerator, 2 * len(points) * displayed_row_count
        )
        frequency_total_variation = float(frequency_total_variation_exact)
        # A distinct XYZ/RGB observation may be undersampled even when its raw
        # RGB triplet remains frequency-balanced across other XYZ coordinates.
        # Audit color-frequency shift separately; neither is a tissue metric.
        rgb_frequency_shift_numerator = sum(
            abs(source_count * displayed_row_count - preview_rgb_counts.get(color, 0) * len(points))
            for color, source_count in source_rgb_counts.items()
        )
        rgb_frequency_total_variation_exact = Fraction(
            rgb_frequency_shift_numerator, 2 * len(points) * displayed_row_count
        )
        # Marginalizing XYZ/RGB pairs to RGB triplets cannot increase total
        # variation. This exact nonnegative gap detects spatial sampling bias
        # invisible to a color-only histogram; it is not an additive estimate
        # of anatomical change, tissue condition, or spatial registration.
        xyz_rgb_vs_rgb_marginal_tv_gap = (
            frequency_total_variation_exact - rgb_frequency_total_variation_exact
        )
        palettes: dict[tuple[float, ...], set[tuple[int, ...]]] = {}
        for point, rgb in zip(points, point_colors, strict=True):
            palettes.setdefault(tuple(point), set()).add(tuple(rgb))
        differing_color_loci = sum(len(colors) > 1 for colors in palettes.values())
        # A preview can show a coordinate yet omit one of its independently
        # observed RGB values. Count that loss separately from total pair
        # retention, without interpreting it as a biological color change.
        preview_palettes: dict[tuple[float, ...], set[tuple[int, ...]]] = {}
        for index in result["preview_point_indices"]:
            preview_palettes.setdefault(tuple(points[index]), set()).add(tuple(point_colors[index]))
        incomplete_multi_color_loci = sum(
            1
            for locus, colors in palettes.items()
            if len(colors) > 1 and not colors.issubset(preview_palettes.get(locus, set()))
        )
        # Raw sensor-channel minima/maxima provide a bounded-preview loss
        # diagnostic. These ranges are neither calibrated colors nor coral
        # condition metrics; compare against all validated source RGB rows.
        rgb_channels = ("red", "green", "blue")
        source_rgb_ranges = {
            channel: [
                min(rgb[axis] for rgb in point_colors),
                max(rgb[axis] for rgb in point_colors),
            ]
            for axis, channel in enumerate(rgb_channels)
        }
        sampled_rgb = [point_colors[i] for i in result["preview_point_indices"]]
        preview_rgb_ranges = {
            channel: [
                min(rgb[axis] for rgb in sampled_rgb),
                max(rgb[axis] for rgb in sampled_rgb),
            ]
            for axis, channel in enumerate(rgb_channels)
        }
        omitted_rgb_channel_extrema = [
            f"{channel}_{bound}"
            for channel in rgb_channels
            for offset, bound in enumerate(("min", "max"))
            if preview_rgb_ranges[channel][offset] != source_rgb_ranges[channel][offset]
        ]
        result["preview_rgb_variant_support"] = {
            "source_rgb_channel_ranges_uint8": source_rgb_ranges,
            "preview_rgb_channel_ranges_uint8": preview_rgb_ranges,
            "preview_omitted_source_rgb_channel_extrema": omitted_rgb_channel_extrema,
            "source_distinct_xyz_rgb_pairs": len(source_pairs),
            "source_repeated_xyz_rgb_observation_rows": repeated_source_pair_rows,
            "source_repeated_xyz_rgb_observation_fraction": (
                repeated_source_pair_rows / len(points)
            ),
            "preview_distinct_xyz_rgb_pairs": len(preview_pairs),
            "source_distinct_rgb_triplets": len(source_rgb_triplets),
            "preview_distinct_rgb_triplets": len(preview_rgb_triplets),
            "fraction_of_source_rgb_triplets_displayed": (
                len(preview_rgb_triplets) / len(source_rgb_triplets)
            ),
            "preview_omitted_distinct_rgb_triplets": (
                len(source_rgb_triplets) - len(preview_rgb_triplets)
            ),
            "preview_vs_source_rgb_triplet_total_variation": float(
                rgb_frequency_total_variation_exact
            ),
            "preview_vs_source_rgb_triplet_total_variation_exact_fraction": [
                rgb_frequency_total_variation_exact.numerator,
                rgb_frequency_total_variation_exact.denominator,
            ],
            "preview_xyz_rgb_vs_rgb_marginal_tv_gap": float(
                xyz_rgb_vs_rgb_marginal_tv_gap
            ),
            "preview_xyz_rgb_vs_rgb_marginal_tv_gap_exact_fraction": [
                xyz_rgb_vs_rgb_marginal_tv_gap.numerator,
                xyz_rgb_vs_rgb_marginal_tv_gap.denominator,
            ],
            "preview_repeated_xyz_rgb_observation_rows": repeated_preview_pair_rows,
            "fraction_of_source_xyz_rgb_pairs_displayed": (len(preview_pairs) / len(source_pairs)),
            "source_xyz_rgb_observation_rows_represented_in_preview": represented_source_rows,
            "fraction_of_source_xyz_rgb_observation_rows_represented_in_preview": (
                represented_source_rows / len(points)
            ),
            "preview_vs_source_xyz_rgb_observation_total_variation": frequency_total_variation,
            "preview_vs_source_xyz_rgb_observation_total_variation_exact_fraction": [
                frequency_total_variation_exact.numerator,
                frequency_total_variation_exact.denominator,
            ],
            "source_xyz_loci_with_multiple_rgb_values": differing_color_loci,
            "multi_rgb_xyz_loci_with_complete_preview": (
                differing_color_loci - incomplete_multi_color_loci
            ),
            "multi_rgb_xyz_loci_with_incomplete_preview": incomplete_multi_color_loci,
            # Bind color and source acquisition row to the displayed sample;
            # the existing geometry-only sample fingerprint remains unchanged.
            "preview_sample_xyz_rgb_sha256": hashlib.sha256(
                json.dumps(
                    [
                        [index, *points[index], *point_colors[index]]
                        for index in result["preview_point_indices"]
                    ],
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        }
        if repeated_source_pair_rows:
            result["qc_warnings"].append("source_contains_repeated_xyz_rgb_observations")
        if frequency_shift_numerator:
            result["qc_warnings"].append(
                "preview_shifts_xyz_rgb_observation_frequency_distribution"
            )
        if differing_color_loci:
            result["qc_warnings"].append("source_xyz_loci_have_multiple_rgb_values")
        if len(preview_pairs) != len(source_pairs):
            result["qc_warnings"].append("preview_omits_distinct_xyz_rgb_observations")
        if incomplete_multi_color_loci:
            result["qc_warnings"].append("preview_omits_multi_rgb_locus_variants")
        if omitted_rgb_channel_extrema:
            result["qc_warnings"].append("preview_omits_rgb_channel_extrema")
        if len(preview_rgb_triplets) < len(source_rgb_triplets):
            result["qc_warnings"].append("preview_omits_distinct_rgb_triplets")
        if rgb_frequency_shift_numerator:
            result["qc_warnings"].append("preview_shifts_rgb_triplet_frequency_distribution")
        if xyz_rgb_vs_rgb_marginal_tv_gap > 0:
            result["qc_warnings"].append("preview_xyz_rgb_tv_exceeds_rgb_marginal_tv")
    else:
        result["preview_rgb_variant_support"] = None
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
    # Hash the submitted UTF-8 PLY text (including RGB/comments) separately
    # from parsed XYZ geometry. This is not proof of original on-disk bytes.
    result["provenance"].update(
        source_text_sha256=source_sha256,
        source_payload_sha256=source_sha256,
        source_payload_size_bytes=len(source_bytes) if source_bytes is not None else None,
        source_payload_integrity_checked=expected_sha256 is not None,
    )
    review = payload.calibration_review
    if review is not None:
        # Reject post-validation mutation of review attribution and scientific QC.
        review = MeshCalibrationReviewEvidence.model_validate(review.model_dump(mode="python"))
        # Review evidence is bound to the exact observation and calibration,
        # not a claim of verified physical scale or authenticated identity.
        if review.reviewed_geometry_sha256 != result["provenance"]["geometry_sha256"]:
            raise ValueError("Point-cloud calibration review does not match source geometry")
        if (
            review.reviewed_source_payload_sha256 is not None
            and review.reviewed_source_payload_sha256 != source_sha256
        ):
            raise ValueError("Point-cloud calibration review does not match imported source bytes")
        if source_sha256 is not None and review.reviewed_source_payload_sha256 is None:
            result["qc_warnings"].append("independent_calibration_review_source_bytes_unbound")
        if (
            review.reviewed_coordinate_frame_id is not None
            and review.reviewed_coordinate_frame_id != payload.coordinate_frame_id
        ):
            raise ValueError(
                "Point-cloud calibration review does not match source coordinate frame"
            )
        if payload.coordinate_frame_id is not None and review.reviewed_coordinate_frame_id is None:
            result["qc_warnings"].append("independent_calibration_review_coordinate_frame_unbound")
        if (
            review.reviewed_specimen_id != payload.specimen_id
            or review.reviewed_observation_id != payload.observation_id
            or review.reviewed_observed_at_utc != payload.observed_at_utc
        ):
            raise ValueError("Point-cloud calibration review does not match source observation")
        if (
            review.reviewed_meters_per_unit != payload.meters_per_unit
            or review.reviewed_calibration_method != payload.calibration_method
            or review.reviewed_calibration_evidence.strip() != payload.calibration_evidence.strip()
            or review.reviewed_relative_scale_uncertainty != payload.relative_scale_uncertainty
        ):
            raise ValueError("Point-cloud calibration review does not match calibration inputs")
        if payload.observed_at_utc is not None and review.reviewed_at_utc < payload.observed_at_utc:
            raise ValueError("Point-cloud calibration review predates source observation")
        result["provenance"]["calibration_review_evidence"] = review.model_dump(mode="json")
        result["qc_warnings"].append("independent_calibration_review_not_verification")
        if review.independent_review_decision == "disputes_scale":
            result["qc_warnings"].append("independent_calibration_review_disputes_scale")
        elif review.independent_review_decision == "inconclusive":
            result["qc_warnings"].append("independent_calibration_review_inconclusive")
    return result
