"""Bounded, explicitly unverified mesh surface measurement preview."""

from __future__ import annotations

import base64
import hashlib
import json
from collections import Counter
from datetime import UTC
from fractions import Fraction
from heapq import heappop, heappush
from itertools import pairwise
from math import dist, fsum, isfinite
from typing import Any

from reefvision.schemas.spatial_mesh_preview_v14 import MeshCalibrationReviewEvidence
from reefvision.services import (
    spatial_mesh_boundary_v14,
    spatial_mesh_glb_v14,
    spatial_mesh_measurements,
    spatial_mesh_obj_v14,
    spatial_mesh_paths_v14,
    spatial_mesh_ply_v14,
    spatial_mesh_volume_v14,
)

MAX_PREVIEW_TRIANGLES = 512

_TracePoint = tuple[float, float, float]


def _collinear_edge_union(edges: set[frozenset[_TracePoint]]) -> tuple[int, Fraction]:
    """Count overlapping pairs and measure their geometric union.

    Exact binary64 rational line keys avoid tolerance-dependent welding.
    Only positive-length overlaps are merged; endpoint contact is unchanged.
    Lengths use Euclidean binary64 distances, summed before rounding.
    """
    lines: dict[
        tuple[Fraction, ...],
        list[tuple[Fraction, Fraction, _TracePoint, _TracePoint]],
    ] = {}
    for edge in edges:
        first, last = min(edge), max(edge)
        start = tuple(Fraction(value) for value in first)
        end = tuple(Fraction(value) for value in last)
        delta = tuple(b - a for a, b in zip(start, end, strict=True))
        pivot = next(index for index, value in enumerate(delta) if value)
        direction = tuple(value / delta[pivot] for value in delta)
        intercept = tuple(
            value - slope * start[pivot] for value, slope in zip(start, direction, strict=True)
        )
        lines.setdefault(direction + intercept, []).append((start[pivot], end[pivot], first, last))
    count = 0
    total = Fraction(0)
    for intervals in lines.values():
        active: list[Fraction] = []
        merged_upper: Fraction | None = None
        merged_first: _TracePoint | None = None
        merged_last: _TracePoint | None = None
        for lower, upper, first, last in sorted(intervals):
            while active and active[0] <= lower:
                heappop(active)
            count += len(active)
            heappush(active, upper)
            if merged_upper is None or lower >= merged_upper:
                if merged_first is not None and merged_last is not None:
                    total += Fraction(dist(merged_first, merged_last))
                merged_first, merged_last, merged_upper = first, last, upper
            elif upper > merged_upper:
                merged_last, merged_upper = last, upper
        if merged_first is not None and merged_last is not None:
            total += Fraction(dist(merged_first, merged_last))
    return count, total


def _collinear_union_measurement(
    source_total: Fraction, scale: float, relative_scale_uncertainty: float | None
) -> dict[str, Any]:
    """Keep corrected geometry distinct from exact endpoint graph measurements."""
    calibrated = source_total * Fraction(scale)
    nominal = float(calibrated)
    warnings: list[str] = []
    interval = None
    if calibrated > 0 and nominal == 0:
        warnings.append("surface_trace_collinear_union_length_underflow")
    elif relative_scale_uncertainty is not None:
        uncertainty = Fraction(relative_scale_uncertainty)
        lower = float(calibrated * (1 - uncertainty))
        upper = float(calibrated * (1 + uncertainty))
        if calibrated > 0 and (
            (uncertainty < 1 and lower == 0) or (uncertainty > 0 and lower == upper)
        ):
            warnings.append("surface_trace_collinear_union_interval_unrepresentable")
        else:
            interval = [lower, upper]
    return {
        "method": "exact_source_line_positive_overlap_union",
        "source_length_mesh_units": float(source_total),
        "length_m": None if calibrated > 0 and nominal == 0 else nominal,
        "length_scale_only_interval_m": interval,
        "biological_validation_status": "not_verified_anatomical_centerline",
        "human_review_verified": False,
        "qc_warnings": warnings,
    }


def _trace_endpoint_chains(
    adjacency: dict[_TracePoint, set[_TracePoint]],
    edge_lengths: dict[frozenset[_TracePoint], Fraction],
    scale: float,
    relative_scale_uncertainty: float | None,
) -> list[dict[str, Any]]:
    """Partition exact selected edges into geometric chains, not anatomy."""
    remaining = set(edge_lengths)
    chains: list[dict[str, Any]] = []

    def consume(start: _TracePoint, following: _TracePoint) -> None:
        path = [start, following]
        remaining.remove(frozenset((start, following)))
        while len(adjacency[path[-1]]) == 2:
            previous, current = path[-2:]
            next_point = next(point for point in adjacency[current] if point != previous)
            edge = frozenset((current, next_point))
            if edge not in remaining:
                break
            remaining.remove(edge)
            path.append(next_point)
        segment_lengths = [edge_lengths[frozenset(pair)] for pair in pairwise(path)]
        source_length = sum(segment_lengths, Fraction(0))
        # Describe sampling along the canonical chain, not anatomical resolution.
        longest_edge = max(segment_lengths)
        longest_edge_offset = segment_lengths.index(longest_edge)
        longest_edge_fraction = float(longest_edge / source_length)
        # Locate half of the selected chain's arc length before calibration.
        # Exact rational interpolation avoids overflow in coordinate sums and
        # loss of a short segment when accumulating widely differing lengths.
        remaining_to_midpoint = source_length / 2
        midpoint_edge_offset = 0
        for edge_offset, segment_length in enumerate(segment_lengths):
            if remaining_to_midpoint <= segment_length:
                midpoint_edge_offset = edge_offset
                break
            remaining_to_midpoint -= segment_length
        midpoint_start = path[midpoint_edge_offset]
        midpoint_end = path[midpoint_edge_offset + 1]
        midpoint_fraction = remaining_to_midpoint / segment_lengths[midpoint_edge_offset]
        source_midpoint = [
            float(Fraction(first) + midpoint_fraction * (Fraction(last) - Fraction(first)))
            for first, last in zip(midpoint_start, midpoint_end, strict=True)
        ]
        # Integrate position along the selected polyline, weighting each
        # edge by its source length rather than weighting sampled vertices.
        weighted_coordinates = [Fraction(0) for _ in range(3)]
        for (first, last), length in zip(pairwise(path), segment_lengths, strict=True):
            for axis in range(3):
                endpoint_sum = Fraction(first[axis]) + Fraction(last[axis])
                weighted_coordinates[axis] += length * endpoint_sum
        source_arc_centroid = [float(value / (2 * source_length)) for value in weighted_coordinates]
        calibrated = source_length * Fraction(scale)
        nominal = float(calibrated)
        warnings: list[str] = []
        interval = None
        if nominal == 0:
            warnings.append("surface_trace_chain_length_underflow")
        elif relative_scale_uncertainty is not None:
            uncertainty = Fraction(relative_scale_uncertainty)
            lower = float(calibrated * (1 - uncertainty))
            upper = float(calibrated * (1 + uncertainty))
            if (uncertainty < 1 and lower == 0) or (uncertainty > 0 and lower == upper):
                warnings.append("surface_trace_chain_interval_unrepresentable")
            else:
                interval = [lower, upper]
        # Straightness belongs to this canonical geometric chain, not the
        # original trace or an anatomical branch. A closed chain has no
        # distinct endpoints. Compute before calibration to avoid scale loss.
        chord = Fraction(dist(path[0], path[-1]))
        calibrated_chord = chord * Fraction(scale)
        chord_m = float(calibrated_chord)
        chord_interval = None
        if chord > 0 and chord_m == 0:
            warnings.append("surface_trace_chain_chord_underflow")
        elif relative_scale_uncertainty is not None:
            uncertainty = Fraction(relative_scale_uncertainty)
            lower = float(calibrated_chord * (1 - uncertainty))
            upper = float(calibrated_chord * (1 + uncertainty))
            if chord > 0 and (
                (uncertainty < 1 and lower == 0) or (uncertainty > 0 and lower == upper)
            ):
                warnings.append("surface_trace_chain_chord_interval_unrepresentable")
            else:
                chord_interval = [lower, upper]
        straightness = None
        if path[0] != path[-1]:
            straightness = float(min(Fraction(1), chord / source_length))
            if straightness == 0:
                straightness = None
                warnings.append("surface_trace_chain_straightness_underflow")
        # Bind review evidence to the ordered source geometry, not calibration,
        # vertex IDs or selection order. Normalize signed zero for the digest.
        source_waypoints = [[0.0 if value == 0 else value for value in point] for point in path]
        chain_hash = hashlib.sha256(
            json.dumps(source_waypoints, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        chains.append(
            {
                "source_waypoints_mesh_units": source_waypoints,
                "source_chain_geometry_sha256": chain_hash,
                "source_chain_geometry_canonicalization": "ordered_float64_xyz_compact_json_v1",
                "endpoint_graph_degrees": [len(adjacency[path[0]]), len(adjacency[path[-1]])],
                "edge_count": len(path) - 1,
                "is_closed": path[0] == path[-1],
                "source_arc_midpoint_mesh_units": source_midpoint,
                "source_arc_centroid_mesh_units": source_arc_centroid,
                "source_longest_edge_chain_offset": longest_edge_offset,
                "source_longest_edge_arc_fraction": longest_edge_fraction,
                "source_arc_midpoint_chain_edge_offset": midpoint_edge_offset,
                "source_arc_midpoint_edge_fraction": {
                    "numerator": str(midpoint_fraction.numerator),
                    "denominator": str(midpoint_fraction.denominator),
                },
                "source_endpoint_chord_mesh_units": float(chord),
                "endpoint_chord_length_m": None if chord > 0 and chord_m == 0 else chord_m,
                "endpoint_chord_length_scale_only_interval_m": chord_interval,
                "endpoint_straightness_ratio": straightness,
                "source_length_mesh_units": float(source_length),
                "length_m": nominal if nominal > 0 else None,
                "length_scale_only_interval_m": interval,
                "biological_validation_status": "not_verified_anatomical_centerline",
                "human_review_verified": False,
                "qc_warnings": warnings,
            }
        )

    # Start with terminals and junctions; then consume remaining degree-two
    # cycles. Sorted source coordinates make orientation and order independent
    # of input trace direction, selection order and duplicate vertex IDs.
    for start in sorted(adjacency):
        if len(adjacency[start]) != 2:
            for following in sorted(adjacency[start]):
                if frozenset((start, following)) in remaining:
                    consume(start, following)
    for start in sorted(adjacency):
        for following in sorted(adjacency[start]):
            if frozenset((start, following)) in remaining:
                consume(start, following)
    return chains


def _trace_endpoint_components(
    adjacency: dict[_TracePoint, set[_TracePoint]],
    chains: list[dict[str, Any]],
    edge_lengths: dict[frozenset[_TracePoint], Fraction],
    scale: float,
    relative_scale_uncertainty: float | None,
    *,
    has_collinear_overlaps: bool,
) -> list[dict[str, Any]]:
    """Inventory connected endpoint components without implying biological identity."""
    components: list[dict[str, Any]] = []
    component_by_point: dict[_TracePoint, int] = {}
    for start in sorted(adjacency):
        if start in component_by_point:
            continue
        index = len(components)
        component_by_point[start] = index
        frontier = [start]
        vertex_count = degree_sum = terminal_count = junction_count = 0
        source_length = Fraction(0)
        component_edges: list[tuple[_TracePoint, _TracePoint]] = []
        landmarks: list[tuple[_TracePoint, int]] = []
        bounds_min = list(start)
        bounds_max = list(start)
        while frontier:
            point = frontier.pop()
            neighbors = adjacency[point]
            degree = len(neighbors)
            vertex_count += 1
            for axis, value in enumerate(point):
                bounds_min[axis] = min(bounds_min[axis], value)
                bounds_max[axis] = max(bounds_max[axis], value)
            degree_sum += degree
            terminal_count += int(degree == 1)
            junction_count += int(degree >= 3)
            if degree != 2:
                landmarks.append((point, degree))
            for neighbor in neighbors:
                # Count each undirected edge once, before any calibrated rounding.
                if point < neighbor:
                    source_length += edge_lengths[frozenset((point, neighbor))]
                    component_edges.append((point, neighbor))
                if neighbor not in component_by_point:
                    component_by_point[neighbor] = index
                    frontier.append(neighbor)
        edge_count = degree_sum // 2
        calibrated = source_length * Fraction(scale)
        nominal = float(calibrated)
        warnings: list[str] = []
        interval = None
        if nominal == 0:
            warnings.append("surface_trace_component_length_underflow")
        elif relative_scale_uncertainty is not None:
            uncertainty = Fraction(relative_scale_uncertainty)
            lower = float(calibrated * (1 - uncertainty))
            upper = float(calibrated * (1 + uncertainty))
            if (uncertainty < 1 and lower == 0) or (uncertainty > 0 and lower == upper):
                warnings.append("surface_trace_component_interval_unrepresentable")
            else:
                interval = [lower, upper]
        # Measure axis spans from source-coordinate differences, not from
        # rounded calibrated positions. Zero spans are genuinely zero.
        spans_m: list[float | None] = []
        span_intervals_m: list[list[float] | None] = []
        span_underflow = span_interval_loss = False
        for minimum, maximum in zip(bounds_min, bounds_max, strict=True):
            span = (Fraction(maximum) - Fraction(minimum)) * Fraction(scale)
            span_m = float(span)
            span_interval = None
            if span > 0 and span_m == 0:
                span_underflow = True
                spans_m.append(None)
            else:
                spans_m.append(span_m)
                if relative_scale_uncertainty is not None:
                    uncertainty = Fraction(relative_scale_uncertainty)
                    lower = float(span * (1 - uncertainty))
                    upper = float(span * (1 + uncertainty))
                    if span > 0 and (
                        (uncertainty < 1 and lower == 0) or (uncertainty > 0 and lower == upper)
                    ):
                        span_interval_loss = True
                    else:
                        span_interval = [lower, upper]
            span_intervals_m.append(span_interval)
        if span_underflow:
            warnings.append("surface_trace_component_axis_span_underflow")
        if span_interval_loss:
            warnings.append("surface_trace_component_axis_span_interval_unrepresentable")
        # Localize positive-length overlap without welding endpoint components.
        # The global overlap count also includes pairs in different components.
        within_overlap_count = 0
        corrected_source_length = source_length
        if has_collinear_overlaps:
            within_overlap_count, corrected_source_length = _collinear_edge_union(
                {frozenset(edge) for edge in component_edges}
            )
        corrected_component = _collinear_union_measurement(
            corrected_source_length, scale, relative_scale_uncertainty
        )
        # Fingerprint the selected endpoint pairs, not the traversal order,
        # chain partition, calibration, or biological identity.
        canonical_edges = [
            [[0.0 if value == 0 else value for value in point] for point in edge]
            for edge in sorted(component_edges)
        ]
        component_hash = hashlib.sha256(
            json.dumps(canonical_edges, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        components.append(
            {
                "source_min_vertex_mesh_units": [0.0 if value == 0 else value for value in start],
                "source_axis_aligned_bounds_mesh_units": {
                    "minimum": [0.0 if value == 0 else value for value in bounds_min],
                    "maximum": [0.0 if value == 0 else value for value in bounds_max],
                },
                "axis_aligned_spans_m": spans_m,
                "axis_aligned_span_scale_only_intervals_m": span_intervals_m,
                "source_component_geometry_sha256": component_hash,
                "source_component_geometry_canonicalization": "sorted_float64_xyz_edges_json_v1",
                "vertex_count": vertex_count,
                "distinct_nonzero_edge_count": edge_count,
                "degree_one_vertex_count": terminal_count,
                "degree_three_or_more_vertex_count": junction_count,
                "cycle_rank": edge_count - vertex_count + 1,
                "unequal_collinear_overlap_pair_count": within_overlap_count,
                "collinear_overlap_corrected_union": corrected_component,
                "source_endpoint_graph_landmarks": [
                    {
                        "source_vertex_mesh_units": [
                            0.0 if value == 0 else value for value in point
                        ],
                        "degree": degree,
                    }
                    for point, degree in sorted(landmarks)
                ],
                "chain_indices": [],
                "source_length_mesh_units": float(source_length),
                "length_m": nominal if nominal > 0 else None,
                "length_scale_only_interval_m": interval,
                "qc_warnings": warnings,
                "biological_validation_status": "not_verified_anatomical_centerline",
                "human_review_verified": False,
            }
        )
    for index, chain in enumerate(chains):
        first = chain["source_waypoints_mesh_units"][0]
        component_index = component_by_point[(first[0], first[1], first[2])]
        components[component_index]["chain_indices"].append(index)
    return components


def _surface_volume_ratio_per_m(area_m2: float, volume_m3: float | None) -> float | None:
    """Provisional A/V in inverse meters; undefined for rejected or zero volume."""
    if volume_m3 is None or volume_m3 <= 0 or area_m2 <= 0:
        return None
    ratio = area_m2 / volume_m3
    return ratio if isfinite(ratio) else None


def _inverse_scale_interval_per_m(
    ratio_per_m: float | None, uncertainty: float | None
) -> list[float] | None:
    """Exact scale-only A/V bounds; 100% uncertainty has no finite upper bound."""
    if ratio_per_m is None or uncertainty is None or uncertainty >= 1:
        return None
    bounds = [ratio_per_m / (1 + uncertainty), ratio_per_m / (1 - uncertainty)]
    if not all(isfinite(bound) for bound in bounds):
        return None
    # Positive but sub-resolution calibration error can round both bounds to
    # the same inverse-length value. Never represent that as exact precision.
    if uncertainty > 0 and bounds[0] >= bounds[1]:
        return None
    return bounds


def _cubic_volume_scale_interval_m3(
    volume_m3: float | None, uncertainty: float | None
) -> list[float] | None:
    """Scale-only bounds; withhold numerically unrepresentable positive limits."""
    if volume_m3 is None or uncertainty is None:
        return None
    bounds = [
        volume_m3 * (1 - uncertainty) ** 3,
        volume_m3 * (1 + uncertainty) ** 3,
    ]
    # At 100% uncertainty a zero lower bound is mathematically valid. Below
    # 100%, a computed zero from a positive nominal volume is numerical loss,
    # not a claim that the lower bound is physically zero.
    if not all(isfinite(bound) for bound in bounds):
        return None
    if volume_m3 > 0 and (
        (uncertainty < 1 and bounds[0] == 0) or (uncertainty > 0 and bounds[0] == bounds[1])
    ):
        return None
    return bounds


def _quadratic_area_scale_interval_m2(
    area_m2: float, uncertainty: float | None
) -> list[float] | None:
    """Withhold positive area bounds lost to underflow or binary64 rounding."""
    if uncertainty is None:
        return None
    bounds = [
        area_m2 * (1 - uncertainty) ** 2,
        area_m2 * (1 + uncertainty) ** 2,
    ]
    if not all(isfinite(bound) for bound in bounds):
        return None
    # A zero lower limit is physically valid at 100% relative scale error
    # or for a true zero-area surface, but not from floating-point underflow.
    if area_m2 > 0 and (
        (uncertainty < 1 and bounds[0] == 0) or (uncertainty > 0 and bounds[0] == bounds[1])
    ):
        return None
    return bounds


def _sample_mesh_display_geometry(
    points: list[tuple[float, float, float]],
    faces: list[list[int]],
    scale: float,
    preserve_axis_extrema: bool = False,
    largest_face_index: int | None = None,
    patch_representative_faces: list[int] | None = None,
) -> dict[str, Any]:
    """Bounded render-only triangle sample; scientific metrics use all faces."""
    count = min(len(faces), MAX_PREVIEW_TRIANGLES)
    last = len(faces) - 1
    face_indices = [0] if count == 1 else [index * last // (count - 1) for index in range(count)]
    if (preserve_axis_extrema or patch_representative_faces is not None) and count < len(faces):
        # In patch-only mode, prioritize the largest reconstructed patches.
        # Arbitrary first/last face indices must not displace a larger patch
        # when the source contains more disconnected patches than display slots.
        # Combined extrema+patch mode deliberately reserves extrema first.
        protected = {0, last} if preserve_axis_extrema else set()
        if preserve_axis_extrema:
            # Source-axis extrema and the area-dominant face aid visual
            # interpretation but are not specimen landmarks or tissue coverage.
            referenced = sorted({index for face in faces for index in face})
            extremal_vertices: set[int] = set()
            for axis in range(3):
                extremal_vertices.add(
                    min(referenced, key=lambda index: (points[index][axis], index))
                )
                extremal_vertices.add(
                    max(referenced, key=lambda index: (points[index][axis], -index))
                )
            if largest_face_index is not None:
                protected.add(largest_face_index)
            for vertex_index in sorted(extremal_vertices):
                protected.add(
                    next(index for index, face in enumerate(faces) if vertex_index in face)
                )
        if patch_representative_faces is not None:
            # Area-ranked edge-connected patches receive one display face each
            # while capacity remains. More than 512 patches cannot all fit;
            # downstream QC explicitly reports any still-omitted patches.
            for face_index in patch_representative_faces:
                if len(protected) >= count:
                    break
                protected.add(face_index)
        remaining = [index for index in range(len(faces)) if index not in protected]
        slots = count - len(protected)
        if slots == 1:
            sampled = [remaining[len(remaining) // 2]]
        elif slots > 1:
            sampled = [remaining[i * (len(remaining) - 1) // (slots - 1)] for i in range(slots)]
        else:
            sampled = []
        face_indices = sorted(protected | set(sampled))
    vertex_indices: list[int] = []
    local_indices: dict[int, int] = {}
    display_faces: list[list[int]] = []
    for face_index in face_indices:
        display_face: list[int] = []
        for source_index in faces[face_index]:
            if source_index not in local_indices:
                local_indices[source_index] = len(vertex_indices)
                vertex_indices.append(source_index)
            display_face.append(local_indices[source_index])
        display_faces.append(display_face)
    return {
        "preview_face_indices": face_indices,
        "preview_vertex_indices": vertex_indices,
        "preview_faces_local_indices": display_faces,
        "preview_vertices_in_source_frame_m": [
            [coordinate * scale for coordinate in points[index]] for index in vertex_indices
        ],
        "preview_is_decimated": count < len(faces),
        "preview_sampling_strategy": {
            (False, False): "uniform_face_index",
            (True, False): "uniform_face_index_extrema_preserving",
            (False, True): "uniform_face_index_patch_preserving",
            (True, True): "uniform_face_index_extrema_patch_preserving",
        }[(preserve_axis_extrema, patch_representative_faces is not None)],
        "preview_face_count": count,
        "preview_face_fraction": count / len(faces),
        # Render-only sampling coverage, not biological area coverage.
    }


def measure_mesh_preview(
    *,
    vertices: list[list[float]],
    faces: list[list[int]],
    meters_per_unit: float,
    calibration_method: str,
    calibration_evidence: str,
    relative_scale_uncertainty: float | None = None,
    source_label: str | None = None,
    surface_path_vertex_pairs: list[list[int]] | None = None,
    surface_trace_vertex_paths: list[list[int]] | None = None,
    preserve_axis_extrema_in_preview: bool = False,
    preserve_edge_connected_patches_in_preview: bool = False,
) -> dict[str, Any]:
    if (
        not 3 <= len(vertices) <= spatial_mesh_obj_v14.MAX_VERTICES
        or not 1 <= len(faces) <= spatial_mesh_obj_v14.MAX_FACES
    ):
        raise ValueError("Mesh preview vertex/face count is outside supported bounds")
    if type(meters_per_unit) not in (int, float):
        raise ValueError("meters_per_unit must be a real numeric value")
    try:
        scale = float(meters_per_unit)
    except OverflowError as exc:
        raise ValueError("meters_per_unit must be finite, positive, and within bounds") from exc
    if not isfinite(scale) or not 0 < scale <= 1_000_000:
        raise ValueError("meters_per_unit must be finite, positive, and within bounds")
    if calibration_method not in {
        "ruler",
        "photogrammetry_control",
        "instrument",
        "other",
    }:
        raise ValueError("A supported calibration_method is required")
    if not isinstance(calibration_evidence, str) or not calibration_evidence.strip():
        raise ValueError("Calibration evidence must be provided")
    if relative_scale_uncertainty is not None and (
        type(relative_scale_uncertainty) not in (int, float)
        or not 0 <= relative_scale_uncertainty <= 1
        or not isfinite(relative_scale_uncertainty)
    ):
        raise ValueError("relative_scale_uncertainty must be between 0 and 1")
    if type(preserve_axis_extrema_in_preview) is not bool:
        raise ValueError("preserve_axis_extrema_in_preview must be a boolean")
    if type(preserve_edge_connected_patches_in_preview) is not bool:
        raise ValueError("preserve_edge_connected_patches_in_preview must be a boolean")

    points: list[tuple[float, float, float]] = []
    for vertex in vertices:
        if (
            not isinstance(vertex, (list, tuple))
            or len(vertex) != 3
            or any(
                type(value) not in (int, float) or abs(value) > 1_000_000_000 or not isfinite(value)
                for value in vertex
            )
        ):
            raise ValueError("Each vertex must contain three bounded finite coordinates")
        points.append((float(vertex[0]), float(vertex[1]), float(vertex[2])))
    edges: Counter[tuple[int, int]] = Counter()
    edge_faces: dict[tuple[int, int], list[tuple[int, bool]]] = {}
    parents = list(range(len(faces)))

    def root(face_index: int) -> int:
        while parents[face_index] != face_index:
            parents[face_index] = parents[parents[face_index]]
            face_index = parents[face_index]
        return face_index

    seen_faces: set[tuple[int, int, int]] = set()
    seen_geometry_faces: set[tuple[tuple[float, float, float], ...]] = set()
    raw_area = 0.0
    face_areas: list[float] = []
    degenerate = 0
    for face_index, face in enumerate(faces):
        if (
            len(face) != 3
            or any(type(index) is not int for index in face)
            or any(index < 0 or index >= len(points) for index in face)
            or len(set(face)) != 3
        ):
            raise ValueError("Every face must reference three distinct existing vertices")
        ordered = sorted(face)
        key = (ordered[0], ordered[1], ordered[2])
        if key in seen_faces:
            raise ValueError("Duplicate triangles would double-count surface area")
        seen_faces.add(key)
        # Different vertex indices may refer to identical XYZ positions. Such
        # triangles would still double-count reconstructed surface area.
        geometry_key = tuple(sorted(points[index] for index in face))
        if geometry_key in seen_geometry_faces:
            raise ValueError("Duplicate triangle geometry would double-count surface area")
        seen_geometry_faces.add(geometry_key)
        area = spatial_mesh_measurements.triangle_area(
            points[face[0]], points[face[1]], points[face[2]]
        )
        if not isfinite(area):
            raise ValueError("Mesh triangle area overflowed")
        degenerate += area == 0
        raw_area += area
        face_areas.append(area)
        for a, b in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            edge = (min(a, b), max(a, b))
            edges[edge] += 1
            incidents = edge_faces.setdefault(edge, [])
            if incidents:
                parents[root(face_index)] = root(incidents[0][0])
            incidents.append((face_index, a < b))
    # Accumulate all nonnegative triangle areas with compensated summation.
    # Display sampling and tessellation QC must not redefine the full mesh area.
    try:
        raw_area = fsum(face_areas)
    except OverflowError as exc:
        raise ValueError("Mesh triangle area overflowed") from exc
    area_m2 = raw_area * scale * scale
    if not isfinite(area_m2):
        raise ValueError("Calibrated area overflowed")
    # A representable positive source area can collapse to exactly zero when
    # the caller's meter scale is extremely small. Reject that calibration
    # rather than publishing a false zero-area scientific observation.
    if raw_area > 0 and area_m2 == 0:
        raise ValueError("Calibrated mesh surface area underflowed to zero")
    # These describe mesh tessellation concentration, not independent
    # biological observations or a calibrated reconstruction error model.
    area_shares = [area / raw_area for area in face_areas] if raw_area > 0 else []
    # A positive source triangle can be too small relative to another to
    # express its area share in binary64. A displayed zero is then a
    # numerical precision limit, not evidence of zero reconstructed surface.
    face_area_fraction_underflow = raw_area > 0 and any(
        area > 0 and share == 0 for area, share in zip(face_areas, area_shares, strict=True)
    )
    largest_triangle_area_fraction = max(area_shares) if area_shares else None
    area_share_squares = fsum(share * share for share in area_shares)
    area_weighted_effective_triangle_count = (
        1.0 / area_share_squares if area_share_squares > 0 else None
    )
    referenced_indices = {index for face in faces for index in face}
    referenced_points = [points[index] for index in sorted(referenced_indices)]
    unreferenced_vertex_count = len(points) - len(referenced_points)
    # Fit the future renderer to ALL referenced vertices, not the decimated
    # triangle sample. Coordinates remain in unregistered imported source axes.
    preview_min_m = [min(point[axis] for point in referenced_points) * scale for axis in range(3)]
    preview_max_m = [max(point[axis] for point in referenced_points) * scale for axis in range(3)]
    preview_camera_target_m = [
        (minimum + maximum) / 2
        for minimum, maximum in zip(preview_min_m, preview_max_m, strict=True)
    ]
    preview_camera_radius_m = dist(preview_min_m, preview_max_m) / 2
    source_dimensions = [
        max(p[axis] for p in referenced_points) - min(p[axis] for p in referenced_points)
        for axis in range(3)
    ]
    dimensions = [dimension * scale for dimension in source_dimensions]
    # A genuine source-coordinate extent can vanish after calibration even
    # when another axis keeps the total triangular area representable. Do not
    # report a falsely planar reconstructed mesh or collapse the render bounds.
    if any(
        span > 0 and (dimensions[axis] == 0.0 or preview_min_m[axis] == preview_max_m[axis])
        for axis, span in enumerate(source_dimensions)
    ):
        raise ValueError("Nonzero mesh axis span collapses after calibration")
    # A scale-invariant reconstruction shape diagnostic. Use source units to
    # avoid squaring a potentially underflowed calibrated bounding diagonal.
    # Global-axis bounds are orientation-sensitive and include gaps between
    # disconnected patches: this is NOT a biological condition or growth score.
    source_diagonal = dist((0.0, 0.0, 0.0), source_dimensions)
    source_diagonal_squared = source_diagonal * source_diagonal
    # A nonzero diagonal can still square to zero in floating-point arithmetic.
    # Withhold the descriptor instead of dividing by zero or inventing precision.
    shape_ratio = raw_area / source_diagonal_squared if source_diagonal_squared > 0 else None
    boundary = sum(count == 1 for count in edges.values())
    nonmanifold = sum(count > 2 for count in edges.values())
    # Group by shared edges, never by shared vertices alone. Sort patches by
    # their first face so that exported results are reproducible across runs.
    patch_area_terms: dict[int, list[float]] = {}
    patch_first_face: dict[int, int] = {}
    patch_face_counts: dict[int, int] = {}
    patch_degenerate_faces: Counter[int] = Counter()
    patch_vertex_indices: dict[int, set[int]] = {}
    patch_face_indices: dict[int, list[int]] = {}
    patch_triangles: dict[int, list[list[tuple[float, float, float]]]] = {}
    patch_faces: dict[int, list[list[int]]] = {}
    for face_index, face_area in enumerate(face_areas):
        patch = root(face_index)
        patch_area_terms.setdefault(patch, []).append(face_area)
        patch_face_counts[patch] = patch_face_counts.get(patch, 0) + 1
        if face_area == 0:
            patch_degenerate_faces[patch] += 1
        patch_vertex_indices.setdefault(patch, set()).update(faces[face_index])
        patch_face_indices.setdefault(patch, []).append(face_index)
        patch_triangles.setdefault(patch, []).append(
            sorted(points[index] for index in faces[face_index])
        )
        patch_faces.setdefault(patch, []).append(faces[face_index])
        patch_first_face.setdefault(patch, face_index)
    # Preserve contributions smaller than the ULP of a large triangle. The
    # complete mesh already uses fsum; per-patch areas must use the same
    # arithmetic or patch totals, coverage and fractions can contradict it.
    patch_area_mesh_units = {patch: fsum(areas) for patch, areas in patch_area_terms.items()}
    ordered_patches = sorted(patch_area_mesh_units, key=patch_first_face.__getitem__)
    # Separate edge-connected patches can still touch at source vertices. Such
    # a union is not a regular closed surface, even if every patch is closed.
    # Retain individual patch volumes but withhold a misleading global total.
    vertex_patch_owners: dict[int, int] = {}
    vertex_touching_patch_vertices: set[int] = set()
    for patch in ordered_patches:
        for vertex_index in patch_vertex_indices[patch]:
            if vertex_index in vertex_patch_owners:
                vertex_touching_patch_vertices.add(vertex_index)
            else:
                vertex_patch_owners[vertex_index] = patch
    # Importers may duplicate an identical coordinate under different vertex
    # indices. Index-only topology then makes physically touching surfaces look
    # disjoint. Compare exact source-frame positions without guessing a spatial
    # tolerance or merging the scientific geometry.
    coordinate_patches: dict[tuple[float, float, float], set[int]] = {}
    coordinate_indices: dict[tuple[float, float, float], set[int]] = {}
    for patch in ordered_patches:
        for vertex_index in patch_vertex_indices[patch]:
            coordinate = points[vertex_index]
            coordinate_patches.setdefault(coordinate, set()).add(patch)
            coordinate_indices.setdefault(coordinate, set()).add(vertex_index)
    coincident_patch_coordinates = {
        coordinate
        for coordinate, patches in coordinate_patches.items()
        if len(patches) > 1 and len(coordinate_indices[coordinate]) > 1
    }
    # Edge incidents belong to one edge-connected patch. Report topology QC
    # per patch so a defective surface is not hidden by an aggregate count.
    patch_edge_counts: Counter[int] = Counter()
    patch_boundary_edges: Counter[int] = Counter()
    patch_nonmanifold_edges: Counter[int] = Counter()
    patch_winding_edges: Counter[int] = Counter()
    patch_boundary_length_terms: dict[int, list[float]] = {}
    patch_boundary_graph_edges: dict[int, list[tuple[int, int]]] = {}
    for (a, b), incidents in edge_faces.items():
        patch = root(incidents[0][0])
        patch_edge_counts[patch] += 1
        if len(incidents) == 1:
            patch_boundary_edges[patch] += 1
            patch_boundary_graph_edges.setdefault(patch, []).append((a, b))
            patch_boundary_length_terms.setdefault(patch, []).append(dist(points[a], points[b]))
        elif len(incidents) > 2:
            patch_nonmanifold_edges[patch] += 1
        elif incidents[0][1] == incidents[1][1]:
            patch_winding_edges[patch] += 1
    # Combinatorial Euler characteristic V - E + F, per edge-connected patch.
    # Even a closed patch can have singular vertices or self-intersections;
    # this diagnostic is not a genus estimate or biological completeness proof.
    patch_euler_characteristics = [
        len(patch_vertex_indices[patch]) - patch_edge_counts[patch] + patch_face_counts[patch]
        for patch in ordered_patches
    ]
    patch_boundary_edge_counts = [patch_boundary_edges[patch] for patch in ordered_patches]
    # Boundary cycles describe indexed surface topology, not biological holes.
    # A pinched/branching boundary graph is not counted as a closed loop.
    patch_boundary_components = [
        spatial_mesh_boundary_v14.boundary_component_counts(
            patch_boundary_graph_edges.get(patch, [])
        )
        for patch in ordered_patches
    ]
    patch_boundary_loop_counts = [loops for loops, _ in patch_boundary_components]
    patch_noncycle_boundary_counts = [noncycles for _, noncycles in patch_boundary_components]
    patch_boundary_component_lengths = [
        spatial_mesh_boundary_v14.boundary_component_lengths(
            patch_boundary_graph_edges.get(patch, []), points
        )
        for patch in ordered_patches
    ]
    patch_boundary_loop_perimeters_m = [
        [length * scale for length in cycles] for cycles, _ in patch_boundary_component_lengths
    ]
    patch_noncycle_boundary_component_lengths_m = [
        [length * scale for length in noncycles]
        for _, noncycles in patch_boundary_component_lengths
    ]
    boundary_loop_perimeters_m = [
        length for patch in patch_boundary_loop_perimeters_m for length in patch
    ]
    noncycle_boundary_component_lengths_m = [
        length for patch in patch_noncycle_boundary_component_lengths_m for length in patch
    ]
    patch_nonmanifold_edge_counts = [patch_nonmanifold_edges[patch] for patch in ordered_patches]
    patch_winding_edge_counts = [patch_winding_edges[patch] for patch in ordered_patches]
    # Retain sub-ULP source-edge lengths when a large edge shares a patch,
    # and reconcile the total over disconnected patches without order loss.
    patch_boundary_lengths_m = [
        fsum(patch_boundary_length_terms.get(patch, [])) * scale for patch in ordered_patches
    ]
    boundary_length_m = fsum(patch_boundary_lengths_m)
    # Only report provisional enclosed volume for closed, consistently wound,
    # nondegenerate edge-connected patches. This is not a biological volume:
    # self-intersections and reconstruction completeness remain unverified.
    patch_volumes_m3: list[float | None] = []
    volume_qc_warnings: set[str] = set()
    for patch in ordered_patches:
        if (
            patch_boundary_edges[patch]
            or patch_nonmanifold_edges[patch]
            or patch_winding_edges[patch]
            or patch_degenerate_faces[patch]
        ):
            patch_volumes_m3.append(None)
            volume_qc_warnings.add("enclosed_volume_requires_closed_oriented_nondegenerate_patch")
            continue
        try:
            source_volume_underflowed = False
            try:
                raw_volume = abs(
                    spatial_mesh_volume_v14.signed_enclosed_volume_mesh_units(
                        points, patch_faces[patch]
                    )
                )
            except ValueError as exc:
                if str(exc) != "Enclosed mesh volume underflowed numeric precision":
                    raise
                if scale <= 1:
                    raise
                # The source volume is genuinely positive but too small for
                # binary64. A larger calibration scale may recover it below.
                raw_volume = 0.0
                source_volume_underflowed = True
            # Scaling first with scale**3 can underflow even when the
            # calibrated result is representable. Multiply in stages.
            calibrated_volume = raw_volume * scale * scale * scale
            # Conversely, the source-unit tetrahedron sum can underflow
            # before a large (>1) calibration scale is applied. Recover only
            # this zero-source-volume case by re-evaluating in calibrated
            # coordinates; retain a QC warning and provisional status.
            if raw_volume == 0 and scale > 1:
                patch_indices = sorted(patch_vertex_indices[patch])
                local_index = {source: index for index, source in enumerate(patch_indices)}
                # Preserve the fixed XYZ tuple type for the strict typed
                # volume kernel rather than producing variable-length tuples.
                calibrated_points = [
                    (
                        points[source][0] * scale,
                        points[source][1] * scale,
                        points[source][2] * scale,
                    )
                    for source in patch_indices
                ]
                calibrated_faces = [
                    [local_index[source] for source in face] for face in patch_faces[patch]
                ]
                recovered_volume = abs(
                    spatial_mesh_volume_v14.signed_enclosed_volume_mesh_units(
                        calibrated_points, calibrated_faces
                    )
                )
                if recovered_volume > 0:
                    calibrated_volume = recovered_volume
                    volume_qc_warnings.add("enclosed_volume_source_unit_numeric_recovery")
                elif source_volume_underflowed:
                    raise ValueError("Enclosed mesh volume underflowed numeric precision")
        except ValueError as exc:
            if str(exc) == "Enclosed mesh volume underflowed numeric precision":
                # Do not report a zero or missing volume for known positive
                # geometry solely because floating-point precision was lost.
                raise
            calibrated_volume = float("inf")
            raw_volume = float("inf")
        except OverflowError:
            calibrated_volume = float("inf")
            raw_volume = float("inf")
        if not isfinite(calibrated_volume):
            patch_volumes_m3.append(None)
            volume_qc_warnings.add("enclosed_volume_numeric_overflow")
        elif calibrated_volume == 0:
            patch_volumes_m3.append(None)
            volume_qc_warnings.add("enclosed_volume_zero_or_underflow")
        else:
            patch_volumes_m3.append(calibrated_volume)
    all_patches_have_volume = all(volume is not None for volume in patch_volumes_m3)
    enclosed_volume_m3 = (
        fsum(volume for volume in patch_volumes_m3 if volume is not None)
        if (
            all_patches_have_volume
            and not vertex_touching_patch_vertices
            and not coincident_patch_coordinates
        )
        else None
    )
    if vertex_touching_patch_vertices:
        volume_qc_warnings.add("enclosed_volume_vertex_touching_patches")
    if coincident_patch_coordinates:
        volume_qc_warnings.add("enclosed_volume_coincident_patch_coordinates")
    if enclosed_volume_m3 is not None and not isfinite(enclosed_volume_m3):
        enclosed_volume_m3 = None
        volume_qc_warnings.add("enclosed_volume_numeric_overflow")
    patch_areas_m2: list[float] = []
    for patch in ordered_patches:
        source_patch_area = patch_area_mesh_units[patch]
        calibrated_patch_area = source_patch_area * scale * scale
        # A positive small patch can underflow even when the aggregate mesh
        # area is representable. Never label a real patch as zero-area tissue.
        if source_patch_area > 0 and calibrated_patch_area == 0:
            raise ValueError("Calibrated mesh patch surface area underflowed to zero")
        patch_areas_m2.append(calibrated_patch_area)
    # Fractions are dimensionless, independent of common calibration scale,
    # and use the complete reconstruction rather than sampled display faces.
    # Patch order is the first source-face index; ties retain that order.
    patch_area_fractions = (
        [patch_area_mesh_units[patch] / raw_area for patch in ordered_patches]
        if raw_area > 0
        else None
    )
    # Preserve the existing numeric fractions for backward compatibility,
    # but disclose when a positive patch has rounded to a zero share.
    patch_area_fraction_underflow = patch_area_fractions is not None and any(
        patch_area_mesh_units[patch] > 0 and fraction == 0
        for patch, fraction in zip(ordered_patches, patch_area_fractions, strict=True)
    )
    largest_patch_index = (
        max(range(len(ordered_patches)), key=lambda index: patch_area_fractions[index])
        if patch_area_fractions is not None
        else None
    )
    # A dimensionless surface concentration diagnostic. This is an effective
    # number of geometric patches, never an estimate of coral colony count.
    patch_area_concentration = (
        fsum(fraction * fraction for fraction in patch_area_fractions)
        if patch_area_fractions is not None
        else None
    )
    effective_patch_count = 1.0 / patch_area_concentration if patch_area_concentration else None
    # A/V is a geometric inverse-length descriptor, not biomass or coral health.
    # Withhold the aggregate ratio whenever aggregate enclosed volume is rejected;
    # eligible per-patch ratios remain available as provisional evidence.
    surface_volume_ratio_per_m = _surface_volume_ratio_per_m(area_m2, enclosed_volume_m3)
    patch_surface_volume_ratios_per_m = [
        _surface_volume_ratio_per_m(area, volume)
        for area, volume in zip(patch_areas_m2, patch_volumes_m3, strict=True)
    ]
    # Extents use only vertices belonging to each edge-connected patch.
    # These are global-axis bounds, not branch lengths or organism identities.
    patch_source_dimensions = [
        [
            max(points[index][axis] for index in patch_vertex_indices[patch])
            - min(points[index][axis] for index in patch_vertex_indices[patch])
            for axis in range(3)
        ]
        for patch in ordered_patches
    ]
    patch_dimensions_m = [
        [dimension * scale for dimension in dimensions] for dimensions in patch_source_dimensions
    ]
    # A disconnected small patch may lose its local span even while a larger
    # patch preserves the whole-mesh bounds and area. Never publish false
    # zero local dimensions as measured biological structure.
    if any(
        original > 0 and calibrated == 0.0
        for source_dims, calibrated_dims in zip(
            patch_source_dimensions, patch_dimensions_m, strict=True
        )
        for original, calibrated in zip(source_dims, calibrated_dims, strict=True)
    ):
        raise ValueError("Nonzero mesh patch axis span collapses after calibration")
    # Normalize triangle areas before multiplying by vertex positions.
    # Area * coordinate can underflow to zero even when the source area and
    # surface centroid are both representable (e.g. 1e-220 * 1e-110).
    # Compensated vertex and face sums preserve signed-coordinate cancellation.
    # These are provisional source-frame positions, not biological identities.

    def area_weighted_centroid_m(face_indices: list[int], total_area: float) -> list[float] | None:
        if total_area == 0:
            return None
        return [
            fsum(
                (face_areas[index] / total_area)
                * (fsum(points[vertex][axis] for vertex in faces[index]) / 3)
                for index in face_indices
            )
            * scale
            for axis in range(3)
        ]

    patch_centroids_m = [
        area_weighted_centroid_m(patch_face_indices[patch], patch_area_mesh_units[patch])
        for patch in ordered_patches
    ]
    centroid_m = area_weighted_centroid_m(list(range(len(faces))), raw_area)
    # Only common multiplicative scale error is represented. No registration,
    # origin, reconstruction, or positioning uncertainty is estimated.
    patch_centroid_uncertainties_m = (
        [
            (
                [abs(value) * relative_scale_uncertainty for value in centroid]
                if centroid is not None
                else None
            )
            for centroid in patch_centroids_m
        ]
        if relative_scale_uncertainty is not None
        else None
    )
    centroid_uncertainty_m = (
        [abs(value) * relative_scale_uncertainty for value in centroid_m]
        if centroid_m is not None and relative_scale_uncertainty is not None
        else None
    )
    # Exact geometry fingerprints ignore source vertex/face numbering and winding.
    # They are not biological identities or evidence of registration between scans.
    patch_geometry_hashes = [
        hashlib.sha256(
            json.dumps(sorted(patch_triangles[patch]), separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        for patch in ordered_patches
    ]
    edge_connected_patch_count = len(ordered_patches)
    inconsistent_winding_edge_count = sum(
        len(incidents) == 2 and incidents[0][1] == incidents[1][1]
        for incidents in edge_faces.values()
    )
    geometry_hash = hashlib.sha256(
        json.dumps(
            {"vertices": points, "faces": faces}, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    # Display sampling can underrepresent large triangles; expose its area
    # coverage without treating sampled faces as scientific measurements.
    largest_triangle_face_index = (
        max(range(len(face_areas)), key=face_areas.__getitem__) if raw_area > 0 else None
    )
    display_geometry = _sample_mesh_display_geometry(
        points,
        faces,
        scale,
        preserve_axis_extrema_in_preview,
        largest_face_index=largest_triangle_face_index,
        patch_representative_faces=(
            [
                max(patch_face_indices[patch], key=face_areas.__getitem__)
                for patch in sorted(
                    ordered_patches,
                    key=lambda patch: (-patch_area_mesh_units[patch], patch_first_face[patch]),
                )
            ]
            if preserve_edge_connected_patches_in_preview
            else None
        ),
    )
    preview_largest_triangle_displayed = (
        largest_triangle_face_index in display_geometry["preview_face_indices"]
        if largest_triangle_face_index is not None
        else None
    )
    sampled_raw_area = fsum(face_areas[index] for index in display_geometry["preview_face_indices"])
    # The camera frame uses all source faces, whereas the renderer only
    # displays a bounded sample. Detect when the displayed vertices omit a
    # source-axis extremum (for example, an unsampled coral-tip reconstruction).
    # Compare raw source coordinates, not scaled floats, so tiny calibration
    # factors cannot turn a real omission into an apparent equality.
    sampled_points = [points[index] for index in display_geometry["preview_vertex_indices"]]
    sampled_bounds_min_m = [
        min(point[axis] for point in sampled_points) * scale for axis in range(3)
    ]
    sampled_bounds_max_m = [
        max(point[axis] for point in sampled_points) * scale for axis in range(3)
    ]
    omitted_extremum_sides: list[str] = []
    for axis, axis_name in enumerate(("x", "y", "z")):
        if min(point[axis] for point in sampled_points) > min(
            point[axis] for point in referenced_points
        ):
            omitted_extremum_sides.append(f"{axis_name}_min")
        if max(point[axis] for point in sampled_points) < max(
            point[axis] for point in referenced_points
        ):
            omitted_extremum_sides.append(f"{axis_name}_max")
    # A uniform face-index sample can exclude an entire disconnected surface
    # patch, even if its full-mesh area is large. Record per-patch display
    # coverage without altering scientific measurements or source topology.
    sampled_patch_face_counts: Counter[int] = Counter()
    sampled_patch_face_areas: dict[int, list[float]] = {}
    for face_index in display_geometry["preview_face_indices"]:
        patch = root(face_index)
        sampled_patch_face_counts[patch] += 1
        sampled_patch_face_areas.setdefault(patch, []).append(face_areas[face_index])
    preview_patch_face_counts = [sampled_patch_face_counts[patch] for patch in ordered_patches]
    preview_omitted_patch_indices = [
        index for index, count in enumerate(preview_patch_face_counts) if count == 0
    ]
    preview_partially_sampled_patch_indices = [
        index
        for index, patch in enumerate(ordered_patches)
        if 0 < preview_patch_face_counts[index] < patch_face_counts[patch]
    ]
    # A bounded view can show a patch but still hide some of its faces.
    # Account for those faces separately from completely invisible patches,
    # without subtracting nearly equal total and sampled floating-point areas.
    sampled_face_indices = set(display_geometry["preview_face_indices"])
    preview_partially_sampled_missing_raw_area = fsum(
        face_areas[face_index]
        for face_index in range(len(faces))
        if face_index not in sampled_face_indices
        and sampled_patch_face_counts[root(face_index)] > 0
    )
    # Area in wholly invisible patches is more informative than their face
    # count; this is reconstructed mesh area, never measured tissue coverage.
    omitted_patch_raw_area = fsum(
        patch_area_mesh_units[ordered_patches[index]] for index in preview_omitted_patch_indices
    )
    # A finite full-mesh area does not guarantee that a tiny hidden patch's
    # calibrated area is representable. Withhold a false zero when it underflows.
    omitted_patch_area_m2 = omitted_patch_raw_area * scale * scale
    omitted_patch_area_representable = omitted_patch_raw_area == 0 or omitted_patch_area_m2 > 0
    # Keep partially sampled patches distinct from wholly omitted patches.
    # A positive source-area omission can underflow under extreme scale inputs;
    # missing measurement must never be represented as zero observed omission.
    partial_missing_area_m2 = preview_partially_sampled_missing_raw_area * scale * scale
    partial_missing_area_representable = (
        preview_partially_sampled_missing_raw_area == 0 or partial_missing_area_m2 > 0
    )
    preview_patch_area_coverage_fractions = [
        min(1.0, fsum(sampled_patch_face_areas.get(patch, [])) / patch_area_mesh_units[patch])
        if patch_area_mesh_units[patch] > 0
        else None
        for patch in ordered_patches
    ]
    area_scale_interval_m2 = _quadratic_area_scale_interval_m2(area_m2, relative_scale_uncertainty)
    patch_area_scale_intervals_m2 = (
        [
            _quadratic_area_scale_interval_m2(area, relative_scale_uncertainty)
            for area in patch_areas_m2
        ]
        if relative_scale_uncertainty is not None
        else None
    )
    partial_missing_area_scale_interval_m2 = (
        _quadratic_area_scale_interval_m2(partial_missing_area_m2, relative_scale_uncertainty)
        if partial_missing_area_representable
        else None
    )
    omitted_patch_area_scale_interval_m2 = (
        _quadratic_area_scale_interval_m2(omitted_patch_area_m2, relative_scale_uncertainty)
        if omitted_patch_area_representable
        else None
    )
    if relative_scale_uncertainty is not None and (
        (area_m2 > 0 and area_scale_interval_m2 is None)
        or (
            patch_area_scale_intervals_m2 is not None
            and any(
                area > 0 and interval is None
                for area, interval in zip(
                    patch_areas_m2, patch_area_scale_intervals_m2, strict=True
                )
            )
        )
        or (partial_missing_area_m2 > 0 and partial_missing_area_scale_interval_m2 is None)
        or (
            preview_partially_sampled_missing_raw_area > 0
            and not partial_missing_area_representable
        )
        or (omitted_patch_area_m2 > 0 and omitted_patch_area_scale_interval_m2 is None)
    ):
        volume_qc_warnings.add("surface_area_scale_interval_numeric_unrepresentable")
    volume_scale_interval_m3 = _cubic_volume_scale_interval_m3(
        enclosed_volume_m3, relative_scale_uncertainty
    )
    patch_volume_scale_intervals_m3 = (
        [
            _cubic_volume_scale_interval_m3(volume, relative_scale_uncertainty)
            for volume in patch_volumes_m3
        ]
        if relative_scale_uncertainty is not None
        else None
    )
    if relative_scale_uncertainty is not None and (
        (enclosed_volume_m3 is not None and volume_scale_interval_m3 is None)
        or (
            patch_volume_scale_intervals_m3 is not None
            and any(
                volume is not None and interval is None
                for volume, interval in zip(
                    patch_volumes_m3, patch_volume_scale_intervals_m3, strict=True
                )
            )
        )
    ):
        volume_qc_warnings.add("enclosed_volume_scale_interval_numeric_unrepresentable")
    ratio_scale_interval_per_m = _inverse_scale_interval_per_m(
        surface_volume_ratio_per_m, relative_scale_uncertainty
    )
    patch_ratio_scale_intervals_per_m = (
        [
            _inverse_scale_interval_per_m(ratio, relative_scale_uncertainty)
            for ratio in patch_surface_volume_ratios_per_m
        ]
        if relative_scale_uncertainty is not None
        else None
    )
    # An absent interval at 100% is a mathematically unbounded upper limit,
    # not a floating-point error. Unknown error and rejected volumes are
    # likewise not numeric interval failures.
    if (
        relative_scale_uncertainty is not None
        and 0 < relative_scale_uncertainty < 1
        and (
            (surface_volume_ratio_per_m is not None and ratio_scale_interval_per_m is None)
            or (
                patch_ratio_scale_intervals_per_m is not None
                and any(
                    ratio is not None and interval is None
                    for ratio, interval in zip(
                        patch_surface_volume_ratios_per_m,
                        patch_ratio_scale_intervals_per_m,
                        strict=True,
                    )
                )
            )
        )
    ):
        volume_qc_warnings.add("surface_volume_ratio_scale_interval_numeric_unrepresentable")
    surface_edge_traces = spatial_mesh_paths_v14.mesh_surface_edge_traces(
        points, faces, surface_trace_vertex_paths, scale, relative_scale_uncertainty
    )
    # Root-to-tip selections can share a trunk. Summing their lengths would
    # double-count that geometry, even across split-index mesh seams.
    trace_edge_sets: list[set[frozenset[tuple[float, float, float]]]] = []
    shared_trace_edge_pairs: list[dict[str, Any]] = []
    traversal_counts: Counter[frozenset[tuple[float, float, float]]] = Counter()
    for path in surface_trace_vertex_paths or []:
        path_counts = Counter(
            frozenset((points[first], points[second]))
            for first, second in pairwise(path)
            if points[first] != points[second]
        )
        traversal_counts.update(path_counts)
        trace_edges = set(path_counts)
        for earlier_index, earlier_edges in enumerate(trace_edge_sets):
            shared_count = len(earlier_edges.intersection(trace_edges))
            if shared_count:
                shared_trace_edge_pairs.append(
                    {
                        "trace_indices": [earlier_index, len(trace_edge_sets)],
                        "shared_distinct_geometric_edge_count": shared_count,
                    }
                )
        trace_edge_sets.append(trace_edges)
    exact_edge_union = None
    trace_union_qc_warnings: list[str] = []
    if trace_edge_sets:
        # Count each nonzero exact endpoint-pair once, even within a trace.
        # Unequal, partially overlapping segments are NOT geometrically merged.
        edge_lengths = {edge: Fraction(dist(min(edge), max(edge))) for edge in traversal_counts}
        source_total = sum(edge_lengths.values(), Fraction(0))
        redundant_source_total = sum(
            (length * (traversal_counts[edge] - 1) for edge, length in edge_lengths.items()),
            Fraction(0),
        )
        traversal_count = sum(traversal_counts.values())
        trace_membership_count = sum(len(edges) for edges in trace_edge_sets)
        calibrated_total = source_total * Fraction(scale)
        length_m = float(calibrated_total)
        union_warnings: list[str] = []
        unequal_overlap_count, collinear_source_total = _collinear_edge_union(set(traversal_counts))
        if unequal_overlap_count:
            union_warnings.append("surface_trace_unequal_collinear_edges_overlap")
        interval = None
        if calibrated_total > 0 and length_m == 0:
            union_warnings.append("surface_trace_exact_edge_union_length_underflow")
        elif relative_scale_uncertainty is not None:
            uncertainty = Fraction(relative_scale_uncertainty)
            lower = float(calibrated_total * (1 - uncertainty))
            upper = float(calibrated_total * (1 + uncertainty))
            if calibrated_total > 0 and (
                (uncertainty < 1 and lower == 0) or (uncertainty > 0 and lower == upper)
            ):
                union_warnings.append("surface_trace_exact_edge_union_interval_unrepresentable")
            else:
                interval = [lower, upper]
        # This graph connects only exact coincident endpoints of selected
        # nonzero edges. Interior crossings and partial overlaps are not
        # split, and these graph degrees are not anatomical landmarks.
        adjacency: dict[tuple[float, float, float], set[tuple[float, float, float]]] = {}
        for geometric_edge in traversal_counts:
            endpoint_a, endpoint_b = min(geometric_edge), max(geometric_edge)
            adjacency.setdefault(endpoint_a, set()).add(endpoint_b)
            adjacency.setdefault(endpoint_b, set()).add(endpoint_a)
        chains = _trace_endpoint_chains(adjacency, edge_lengths, scale, relative_scale_uncertainty)
        components = _trace_endpoint_components(
            adjacency,
            chains,
            edge_lengths,
            scale,
            relative_scale_uncertainty,
            has_collinear_overlaps=unequal_overlap_count > 0,
        )
        component_count = len(components)
        cross_component_overlap_count = unequal_overlap_count - sum(
            component["unequal_collinear_overlap_pair_count"] for component in components
        )
        # Local corrected lengths cannot be added when separate endpoint
        # components share positive-length geometric support.
        if cross_component_overlap_count:
            union_warnings.append("surface_trace_cross_component_collinear_overlap")
        topology = {
            "method": "exact_nonzero_edge_endpoint_graph",
            "vertex_count": len(adjacency),
            "connected_component_count": component_count,
            "degree_one_vertex_count": sum(len(neighbors) == 1 for neighbors in adjacency.values()),
            "degree_three_or_more_vertex_count": sum(
                len(neighbors) >= 3 for neighbors in adjacency.values()
            ),
            "cycle_rank": len(traversal_counts) - len(adjacency) + component_count,
            "biological_validation_status": "not_verified_anatomical_centerline",
            "human_review_verified": False,
        }
        corrected_union = _collinear_union_measurement(
            collinear_source_total, scale, relative_scale_uncertainty
        )
        # Retain each original traversal, including direction and repetition.
        # The canonical chains partition the exact nonzero selected edges.
        chain_by_edge: dict[frozenset[_TracePoint], tuple[int, int, _TracePoint]] = {}
        for chain_index, chain in enumerate(chains):
            chain["selected_trace_traversals"] = []
            for offset, (first, last) in enumerate(pairwise(chain["source_waypoints_mesh_units"])):
                start = (first[0], first[1], first[2])
                end = (last[0], last[1], last[2])
                chain_by_edge[frozenset((start, end))] = (chain_index, offset, start)
        for trace_index, path in enumerate(surface_trace_vertex_paths or []):
            for trace_offset, (first, last) in enumerate(pairwise(path)):
                start, end = points[first], points[last]
                if start == end:
                    continue
                chain_index, chain_offset, chain_start = chain_by_edge[frozenset((start, end))]
                chains[chain_index]["selected_trace_traversals"].append(
                    {
                        "trace_index": trace_index,
                        "trace_edge_offset": trace_offset,
                        "chain_edge_offset": chain_offset,
                        "follows_chain_orientation": start == chain_start,
                    }
                )
        # Derive membership and per-edge support from the indexed traversals,
        # without rescanning every selected edge for every chain and trace.
        for chain in chains:
            edge_count = chain["edge_count"]
            trace_offsets: dict[int, set[int]] = {}
            forward_counts = [0] * edge_count
            reverse_counts = [0] * edge_count
            for traversal in chain["selected_trace_traversals"]:
                offset = traversal["chain_edge_offset"]
                trace_offsets.setdefault(traversal["trace_index"], set()).add(offset)
                if traversal["follows_chain_orientation"]:
                    forward_counts[offset] += 1
                else:
                    reverse_counts[offset] += 1
            distinct_counts = [0] * edge_count
            for offsets in trace_offsets.values():
                for offset in offsets:
                    distinct_counts[offset] += 1
            chain["selected_trace_memberships"] = [
                {"trace_index": trace_index, "chain_edge_offsets": sorted(offsets)}
                for trace_index, offsets in sorted(trace_offsets.items())
            ]
            chain["selected_chain_edge_support"] = [
                {
                    "chain_edge_offset": offset,
                    "distinct_trace_count": distinct_counts[offset],
                    "forward_traversal_count": forward_counts[offset],
                    "reverse_traversal_count": reverse_counts[offset],
                }
                for offset in range(edge_count)
            ]
        # Component-level provenance aggregates canonical chain support without
        # treating overlapping selections as independent biological observations.
        for component in components:
            component_chains = [chains[index] for index in component["chain_indices"]]
            component["selected_trace_indices"] = sorted(
                {
                    membership["trace_index"]
                    for chain in component_chains
                    for membership in chain["selected_trace_memberships"]
                }
            )
            component["nonzero_edge_traversal_count"] = sum(
                len(chain["selected_trace_traversals"]) for chain in component_chains
            )
            component["distinct_trace_edge_membership_count"] = sum(
                len(membership["chain_edge_offsets"])
                for chain in component_chains
                for membership in chain["selected_trace_memberships"]
            )
        chain_warnings = sorted({warning for chain in chains for warning in chain["qc_warnings"]})
        # A representable aggregate can conceal an unavailable individual
        # chain measurement. Surface-level QC must expose both.
        component_warnings = sorted(
            {warning for component in components for warning in component["qc_warnings"]}
        )
        corrected_component_warnings = sorted(
            {
                warning
                for component in components
                for warning in component["collinear_overlap_corrected_union"]["qc_warnings"]
            }
            - set(corrected_union["qc_warnings"])
        )
        trace_union_qc_warnings = (
            union_warnings
            + corrected_union["qc_warnings"]
            + chain_warnings
            + component_warnings
            + corrected_component_warnings
        )
        exact_edge_union = {
            "endpoint_graph_topology": topology,
            "endpoint_graph_chains": chains,
            "endpoint_graph_components": components,
            "method": "exact_endpoint_pair_equality_only",
            "unequal_collinear_overlap_pair_count": unequal_overlap_count,
            "cross_component_unequal_collinear_overlap_pair_count": cross_component_overlap_count,
            "collinear_overlap_corrected_union": corrected_union,
            "distinct_nonzero_edge_count": len(traversal_counts),
            "nonzero_edge_traversal_count": traversal_count,
            "within_trace_redundant_traversal_count": traversal_count - trace_membership_count,
            "cross_trace_redundant_traversal_count": trace_membership_count - len(traversal_counts),
            "redundant_traversal_source_length_mesh_units": float(redundant_source_total),
            "source_length_mesh_units": float(source_total),
            "length_m": None if calibrated_total > 0 and length_m == 0 else length_m,
            "length_scale_only_interval_m": interval,
            "biological_validation_status": "not_verified_anatomical_centerline",
            "human_review_verified": False,
            "qc_warnings": union_warnings,
        }
    return {
        "schema_version": "mesh-preview-0001",
        "surface_area_m2": area_m2,
        "surface_area_to_bounding_diagonal_squared_ratio": shape_ratio,
        "enclosed_volume_m3": enclosed_volume_m3,
        "edge_connected_patch_enclosed_volumes_m3": patch_volumes_m3,
        "enclosed_volume_scale_interval_m3": volume_scale_interval_m3,
        "edge_connected_patch_enclosed_volume_scale_intervals_m3": (
            patch_volume_scale_intervals_m3
        ),
        "enclosed_volume_is_provisional": True,
        "surface_to_enclosed_volume_ratio_per_m": surface_volume_ratio_per_m,
        "surface_to_enclosed_volume_ratio_scale_interval_per_m": ratio_scale_interval_per_m,
        "edge_connected_patch_surface_to_enclosed_volume_ratios_per_m": (
            patch_surface_volume_ratios_per_m
        ),
        "edge_connected_patch_surface_to_enclosed_volume_ratio_scale_intervals_per_m": (
            patch_ratio_scale_intervals_per_m
        ),
        "axis_aligned_dimensions_m": dimensions,
        "axis_aligned_dimension_scale_intervals_m": (
            [
                [
                    dimension * (1 - relative_scale_uncertainty),
                    dimension * (1 + relative_scale_uncertainty),
                ]
                for dimension in dimensions
            ]
            if relative_scale_uncertainty is not None
            else None
        ),
        # This global-axis diagonal is not an anatomical measurement.
        "axis_aligned_bounding_box_diagonal_m": dist((0.0, 0.0, 0.0), dimensions),
        "axis_aligned_bounding_box_diagonal_scale_interval_m": (
            [
                dist((0.0, 0.0, 0.0), dimensions) * (1 - relative_scale_uncertainty),
                dist((0.0, 0.0, 0.0), dimensions) * (1 + relative_scale_uncertainty),
            ]
            if relative_scale_uncertainty is not None
            else None
        ),
        "axis_aligned_bounding_box_diagonal_scale_uncertainty_m": (
            dist((0.0, 0.0, 0.0), dimensions) * relative_scale_uncertainty
            if relative_scale_uncertainty is not None
            else None
        ),
        "area_weighted_surface_centroid_m": centroid_m,
        "area_weighted_centroid_scale_uncertainty_m": centroid_uncertainty_m,
        "face_count": len(faces),
        "largest_triangle_area_fraction": largest_triangle_area_fraction,
        "preview_largest_triangle_face_index": largest_triangle_face_index,
        "preview_largest_triangle_displayed": preview_largest_triangle_displayed,
        "area_weighted_effective_triangle_count": area_weighted_effective_triangle_count,
        **display_geometry,
        "preview_sampled_surface_area_m2": sampled_raw_area * scale * scale,
        "preview_displayed_bounds_in_source_frame_m": {
            "minimum": sampled_bounds_min_m,
            "maximum": sampled_bounds_max_m,
        },
        "preview_omitted_axis_extremum_sides": omitted_extremum_sides,
        "preview_surface_area_fraction": sampled_raw_area / raw_area if raw_area > 0 else None,
        "preview_edge_connected_patch_face_counts": preview_patch_face_counts,
        "preview_edge_connected_patch_surface_area_coverage_fractions": (
            preview_patch_area_coverage_fractions
        ),
        "preview_omitted_edge_connected_patch_indices": preview_omitted_patch_indices,
        "preview_partially_sampled_patch_indices": preview_partially_sampled_patch_indices,
        "preview_partially_sampled_patch_missing_area_fraction": (
            preview_partially_sampled_missing_raw_area / raw_area if raw_area > 0 else None
        ),
        "preview_partially_sampled_patch_missing_area_m2": (
            partial_missing_area_m2 if partial_missing_area_representable else None
        ),
        "preview_partially_sampled_patch_missing_area_scale_interval_m2": (
            partial_missing_area_scale_interval_m2
        ),
        "preview_omitted_patch_surface_area_fraction": (
            omitted_patch_raw_area / raw_area if raw_area > 0 else None
        ),
        "preview_omitted_patch_surface_area_m2": (
            omitted_patch_area_m2 if omitted_patch_area_representable else None
        ),
        "preview_omitted_patch_surface_area_scale_interval_m2": (
            omitted_patch_area_scale_interval_m2
        ),
        "vertex_count": len(points),
        "preview_referenced_bounds_in_source_frame_m": {
            "minimum": preview_min_m,
            "maximum": preview_max_m,
        },
        "preview_camera_target_in_source_frame_m": preview_camera_target_m,
        "preview_camera_radius_m": preview_camera_radius_m,
        "preview_camera_fit_basis": "all_referenced_vertices",
        "preview_coordinate_registration_verified": False,
        "unreferenced_vertex_count": unreferenced_vertex_count,
        "degenerate_face_count": degenerate,
        "boundary_edge_count": boundary,
        "boundary_loop_count": sum(patch_boundary_loop_counts),
        "noncycle_boundary_component_count": sum(patch_noncycle_boundary_counts),
        "boundary_loop_perimeters_m": boundary_loop_perimeters_m,
        "noncycle_boundary_component_lengths_m": noncycle_boundary_component_lengths_m,
        "boundary_loop_perimeter_scale_intervals_m": (
            [
                [
                    length * (1 - relative_scale_uncertainty),
                    length * (1 + relative_scale_uncertainty),
                ]
                for length in boundary_loop_perimeters_m
            ]
            if relative_scale_uncertainty is not None
            else None
        ),
        "noncycle_boundary_component_length_scale_intervals_m": (
            [
                [
                    length * (1 - relative_scale_uncertainty),
                    length * (1 + relative_scale_uncertainty),
                ]
                for length in noncycle_boundary_component_lengths_m
            ]
            if relative_scale_uncertainty is not None
            else None
        ),
        "boundary_edge_length_m": boundary_length_m,
        "boundary_edge_length_scale_interval_m": (
            [
                boundary_length_m * (1 - relative_scale_uncertainty),
                boundary_length_m * (1 + relative_scale_uncertainty),
            ]
            if relative_scale_uncertainty is not None
            else None
        ),
        "surface_edge_paths": spatial_mesh_paths_v14.mesh_edge_paths(
            points, faces, surface_path_vertex_pairs, scale, relative_scale_uncertainty
        ),
        "surface_edge_traces": surface_edge_traces,
        "surface_trace_shared_geometric_edge_pairs": shared_trace_edge_pairs,
        "surface_trace_exact_edge_union": exact_edge_union,
        "boundary_edge_length_scale_uncertainty_m": (
            boundary_length_m * relative_scale_uncertainty
            if relative_scale_uncertainty is not None
            else None
        ),
        "nonmanifold_edge_count": nonmanifold,
        "edge_connected_patch_count": edge_connected_patch_count,
        "vertex_touching_patch_vertex_count": len(vertex_touching_patch_vertices),
        "coincident_patch_coordinate_count": len(coincident_patch_coordinates),
        "edge_connected_patch_face_counts": [patch_face_counts[patch] for patch in ordered_patches],
        "edge_connected_patch_vertex_counts": [
            len(patch_vertex_indices[patch]) for patch in ordered_patches
        ],
        "edge_connected_patch_edge_counts": [patch_edge_counts[patch] for patch in ordered_patches],
        "edge_connected_patch_euler_characteristics": patch_euler_characteristics,
        "edge_connected_patch_geometry_sha256": patch_geometry_hashes,
        "edge_connected_patch_degenerate_face_counts": [
            patch_degenerate_faces[patch] for patch in ordered_patches
        ],
        "edge_connected_patch_boundary_edge_counts": patch_boundary_edge_counts,
        "edge_connected_patch_boundary_loop_counts": patch_boundary_loop_counts,
        "edge_connected_patch_noncycle_boundary_component_counts": (patch_noncycle_boundary_counts),
        "edge_connected_patch_boundary_loop_perimeters_m": patch_boundary_loop_perimeters_m,
        "edge_connected_patch_noncycle_boundary_component_lengths_m": (
            patch_noncycle_boundary_component_lengths_m
        ),
        "edge_connected_patch_boundary_loop_perimeter_scale_intervals_m": (
            [
                [
                    [
                        length * (1 - relative_scale_uncertainty),
                        length * (1 + relative_scale_uncertainty),
                    ]
                    for length in patch
                ]
                for patch in patch_boundary_loop_perimeters_m
            ]
            if relative_scale_uncertainty is not None
            else None
        ),
        "edge_connected_patch_noncycle_boundary_component_length_scale_intervals_m": (
            [
                [
                    [
                        length * (1 - relative_scale_uncertainty),
                        length * (1 + relative_scale_uncertainty),
                    ]
                    for length in patch
                ]
                for patch in patch_noncycle_boundary_component_lengths_m
            ]
            if relative_scale_uncertainty is not None
            else None
        ),
        "edge_connected_patch_boundary_edge_lengths_m": patch_boundary_lengths_m,
        "edge_connected_patch_boundary_length_scale_intervals_m": (
            [
                [
                    length * (1 - relative_scale_uncertainty),
                    length * (1 + relative_scale_uncertainty),
                ]
                for length in patch_boundary_lengths_m
            ]
            if relative_scale_uncertainty is not None
            else None
        ),
        "edge_connected_patch_boundary_length_scale_uncertainties_m": (
            [length * relative_scale_uncertainty for length in patch_boundary_lengths_m]
            if relative_scale_uncertainty is not None
            else None
        ),
        "edge_connected_patch_nonmanifold_edge_counts": patch_nonmanifold_edge_counts,
        "edge_connected_patch_inconsistent_winding_edge_counts": patch_winding_edge_counts,
        "edge_connected_patch_surface_areas_m2": patch_areas_m2,
        "edge_connected_patch_surface_area_fractions": patch_area_fractions,
        "edge_connected_patch_area_concentration_index": patch_area_concentration,
        "area_weighted_effective_patch_count": effective_patch_count,
        "largest_surface_patch_index": largest_patch_index,
        "largest_surface_patch_area_fraction": (
            patch_area_fractions[largest_patch_index]
            if largest_patch_index is not None and patch_area_fractions is not None
            else None
        ),
        "edge_connected_patch_axis_aligned_dimensions_m": patch_dimensions_m,
        "edge_connected_patch_dimension_scale_intervals_m": (
            [
                [
                    [
                        dimension * (1 - relative_scale_uncertainty),
                        dimension * (1 + relative_scale_uncertainty),
                    ]
                    for dimension in patch_dimensions
                ]
                for patch_dimensions in patch_dimensions_m
            ]
            if relative_scale_uncertainty is not None
            else None
        ),
        "edge_connected_patch_bounding_box_diagonals_m": [
            dist((0.0, 0.0, 0.0), dims) for dims in patch_dimensions_m
        ],
        "edge_connected_patch_bounding_box_diagonal_scale_intervals_m": (
            [
                [
                    dist((0.0, 0.0, 0.0), dims) * (1 - relative_scale_uncertainty),
                    dist((0.0, 0.0, 0.0), dims) * (1 + relative_scale_uncertainty),
                ]
                for dims in patch_dimensions_m
            ]
            if relative_scale_uncertainty is not None
            else None
        ),
        "edge_connected_patch_bounding_box_diagonal_scale_uncertainties_m": (
            [
                dist((0.0, 0.0, 0.0), dims) * relative_scale_uncertainty
                for dims in patch_dimensions_m
            ]
            if relative_scale_uncertainty is not None
            else None
        ),
        "edge_connected_patch_area_weighted_surface_centroids_m": patch_centroids_m,
        "edge_connected_patch_centroid_scale_uncertainties_m": (patch_centroid_uncertainties_m),
        "edge_connected_patch_dimension_scale_uncertainties_m": (
            [
                [dimension * relative_scale_uncertainty for dimension in dimensions]
                for dimensions in patch_dimensions_m
            ]
            if relative_scale_uncertainty is not None
            else None
        ),
        "edge_connected_patch_area_scale_uncertainties_m2": (
            [2 * relative_scale_uncertainty * area for area in patch_areas_m2]
            if relative_scale_uncertainty is not None
            else None
        ),
        "edge_connected_patch_area_scale_intervals_m2": (patch_area_scale_intervals_m2),
        "inconsistent_winding_edge_count": inconsistent_winding_edge_count,
        "qc_warnings": (
            sorted(volume_qc_warnings)
            + (["degenerate_triangles_present"] if degenerate else [])
            + (["mesh_face_area_fraction_underflow"] if face_area_fraction_underflow else [])
            + (["mesh_patch_area_fraction_underflow"] if patch_area_fraction_underflow else [])
            + (["mesh_shape_ratio_unavailable_zero_extent"] if source_diagonal == 0 else [])
            + (
                ["mesh_shape_ratio_unavailable_numeric_underflow"]
                if source_diagonal > 0 and source_diagonal_squared == 0
                else []
            )
            + (["open_mesh_surface_not_enclosed"] if boundary else [])
            + (["noncycle_mesh_boundary_components"] if any(patch_noncycle_boundary_counts) else [])
            + (["nonmanifold_mesh_edges"] if nonmanifold else [])
            + (["disconnected_mesh_patches"] if edge_connected_patch_count > 1 else [])
            + (["vertex_touching_mesh_patches"] if vertex_touching_patch_vertices else [])
            + (["coincident_mesh_patch_coordinates"] if coincident_patch_coordinates else [])
            + (["inconsistent_face_winding"] if inconsistent_winding_edge_count else [])
            + (["unreferenced_mesh_vertices"] if unreferenced_vertex_count else [])
            + (["surface_traces_share_geometric_edges"] if shared_trace_edge_pairs else [])
            + trace_union_qc_warnings
            + (
                ["preview_omits_edge_connected_mesh_patches"]
                if preview_omitted_patch_indices
                else []
            )
            + (
                ["preview_omits_reconstructed_mesh_surface_area"]
                if omitted_patch_raw_area > 0 or preview_partially_sampled_missing_raw_area > 0
                else []
            )
            + (
                ["preview_partially_sampled_missing_area_numeric_unrepresentable"]
                if preview_partially_sampled_missing_raw_area > 0
                and not partial_missing_area_representable
                else []
            )
            + (["preview_omits_source_axis_extrema"] if omitted_extremum_sides else [])
            + (
                ["preview_omits_largest_mesh_triangle"]
                if preview_largest_triangle_displayed is False
                else []
            )
            + (
                ["zero_area_mesh_patch_centroid_undefined"]
                if any(patch_area_mesh_units[patch] == 0 for patch in ordered_patches)
                else []
            )
        ),
        "area_scale_uncertainty_m2": (
            2 * relative_scale_uncertainty * area_m2
            if relative_scale_uncertainty is not None
            else None
        ),
        "surface_area_scale_interval_m2": (area_scale_interval_m2),
        "axis_aligned_dimension_scale_uncertainty_m": (
            [dimension * relative_scale_uncertainty for dimension in dimensions]
            if relative_scale_uncertainty is not None
            else None
        ),
        "confidence_interval": None,
        "measurement_status": "caller_supplied_unverified",
        "provenance": {
            "geometry_sha256": geometry_hash,
            "source_label": source_label,
            "meters_per_mesh_unit": scale,
            "calibration_method": calibration_method,
            "calibration_evidence": calibration_evidence.strip(),
            "calibration_verified": False,
            "relative_scale_uncertainty": relative_scale_uncertainty,
        },
    }


def preview_from_request(payload: Any) -> dict[str, Any]:
    # Preserve a byte-exact content identity for future project-scoped imports.
    # This identifies caller-supplied source bytes, not a stored or verified asset.
    source_bytes: bytes | None = None
    if payload.obj_text is not None:
        vertices, faces = spatial_mesh_obj_v14.parse_obj_triangles(payload.obj_text)
        source_format = "obj"
        source_bytes = payload.obj_text.encode("utf-8")
    elif payload.ply_text is not None:
        vertices, faces = spatial_mesh_ply_v14.parse_ply_triangles(payload.ply_text)
        source_format = "ply_ascii"
        source_bytes = payload.ply_text.encode("utf-8")
    elif payload.glb_base64 is not None:
        vertices, faces = spatial_mesh_glb_v14.parse_glb_triangles(payload.glb_base64)
        source_format = "glb_2_0"
        # The parser has already strictly validated and bounded the GLB bytes.
        # Hash the decoded binary, never the transport base64 representation.
        source_bytes = base64.b64decode(payload.glb_base64, validate=True)
    else:
        vertices, faces = payload.vertices, payload.faces
        source_format = "indexed_triangles"
    source_sha256 = hashlib.sha256(source_bytes).hexdigest() if source_bytes is not None else None
    expected_sha256 = payload.expected_source_payload_sha256
    if expected_sha256 is not None:
        if source_sha256 is None:
            raise ValueError("Source SHA-256 binding requires an imported mesh file")
        if source_sha256 != expected_sha256:
            raise ValueError("Imported mesh source SHA-256 does not match expected source payload")
    result = measure_mesh_preview(
        vertices=vertices,
        faces=faces,
        meters_per_unit=payload.meters_per_unit,
        calibration_method=payload.calibration_method,
        calibration_evidence=payload.calibration_evidence,
        relative_scale_uncertainty=payload.relative_scale_uncertainty,
        source_label=payload.source_label,
        surface_path_vertex_pairs=payload.surface_path_vertex_pairs,
        surface_trace_vertex_paths=payload.surface_trace_vertex_paths,
        preserve_axis_extrema_in_preview=payload.preserve_axis_extrema_in_preview,
        preserve_edge_connected_patches_in_preview=(
            payload.preserve_edge_connected_patches_in_preview
        ),
    )
    source_byte_count = len(source_bytes) if source_bytes is not None else None
    result["provenance"].update(
        source_format=source_format,
        source_payload_sha256=source_sha256,
        source_payload_size_bytes=source_byte_count,
        source_payload_integrity_checked=expected_sha256 is not None,
    )
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
        coordinate_registration_verified=False,
        specimen_identity_verified=False,
        observation_metadata_verified=False,
    )
    review = payload.calibration_review
    if review is not None:
        # Pydantic does not revalidate already-created mutable model instances.
        # Reject altered or constructed audit evidence before persisting provenance.
        review = MeshCalibrationReviewEvidence.model_validate(review.model_dump(mode="python"))
        # An audit note must not be silently reused after geometry, scale,
        # method, evidence, or uncertainty is revised. Independent review
        # remains a caller-supplied claim, never a verified calibration.
        if review.reviewed_geometry_sha256 != result["provenance"]["geometry_sha256"]:
            raise ValueError("Calibration review does not match source geometry")
        if (
            review.reviewed_source_payload_sha256 is not None
            and review.reviewed_source_payload_sha256 != source_sha256
        ):
            raise ValueError("Calibration review does not match imported source bytes")
        if source_sha256 is not None and review.reviewed_source_payload_sha256 is None:
            result["qc_warnings"].append("independent_calibration_review_source_bytes_unbound")
        if (
            review.reviewed_coordinate_frame_id is not None
            and review.reviewed_coordinate_frame_id != payload.coordinate_frame_id
        ):
            raise ValueError("Calibration review does not match source coordinate frame")
        if payload.coordinate_frame_id is not None and review.reviewed_coordinate_frame_id is None:
            result["qc_warnings"].append("independent_calibration_review_coordinate_frame_unbound")
        if (
            review.reviewed_specimen_id != payload.specimen_id
            or review.reviewed_observation_id != payload.observation_id
            or review.reviewed_observed_at_utc != payload.observed_at_utc
        ):
            raise ValueError("Calibration review does not match source observation")
        if (
            review.reviewed_meters_per_unit != payload.meters_per_unit
            or review.reviewed_calibration_method != payload.calibration_method
            or review.reviewed_calibration_evidence.strip() != payload.calibration_evidence.strip()
            or review.reviewed_relative_scale_uncertainty != payload.relative_scale_uncertainty
        ):
            raise ValueError("Calibration review does not match current calibration inputs")
        if payload.observed_at_utc is not None and review.reviewed_at_utc < payload.observed_at_utc:
            raise ValueError("Calibration review predates the source observation")
        result["provenance"]["calibration_review_evidence"] = review.model_dump(mode="json")
        result["qc_warnings"].append("independent_calibration_review_not_verification")
        if review.independent_review_decision == "disputes_scale":
            result["qc_warnings"].append("independent_calibration_review_disputes_scale")
        elif review.independent_review_decision == "inconclusive":
            result["qc_warnings"].append("independent_calibration_review_inconclusive")
    return result
