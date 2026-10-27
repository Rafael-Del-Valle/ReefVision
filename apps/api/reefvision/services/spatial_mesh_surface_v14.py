"""Bounded, explicitly unverified mesh surface measurement preview."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC
from math import dist, fsum, isfinite
from typing import Any

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
    return bounds if all(isfinite(bound) for bound in bounds) else None


def _sample_mesh_display_geometry(
    points: list[tuple[float, float, float]],
    faces: list[list[int]],
    scale: float,
) -> dict[str, Any]:
    """Bounded render-only triangle sample; scientific metrics use all faces."""
    count = min(len(faces), MAX_PREVIEW_TRIANGLES)
    last = len(faces) - 1
    face_indices = [0] if count == 1 else [index * last // (count - 1) for index in range(count)]
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
) -> dict[str, Any]:
    if (
        not 3 <= len(vertices) <= spatial_mesh_obj_v14.MAX_VERTICES
        or not 1 <= len(faces) <= spatial_mesh_obj_v14.MAX_FACES
    ):
        raise ValueError("Mesh preview vertex/face count is outside supported bounds")
    if type(meters_per_unit) not in (int, float):
        raise ValueError("meters_per_unit must be a real numeric value")
    scale = float(meters_per_unit)
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
        or not isfinite(relative_scale_uncertainty)
        or not 0 <= relative_scale_uncertainty <= 1
    ):
        raise ValueError("relative_scale_uncertainty must be between 0 and 1")

    points: list[tuple[float, float, float]] = []
    for vertex in vertices:
        if (
            not isinstance(vertex, (list, tuple))
            or len(vertex) != 3
            or any(
                type(value) not in (int, float) or not isfinite(value) or abs(value) > 1_000_000_000
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
    # These describe mesh tessellation concentration, not independent
    # biological observations or a calibrated reconstruction error model.
    area_shares = [area / raw_area for area in face_areas] if raw_area > 0 else []
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
    dimensions = [
        (max(p[axis] for p in referenced_points) - min(p[axis] for p in referenced_points)) * scale
        for axis in range(3)
    ]
    boundary = sum(count == 1 for count in edges.values())
    nonmanifold = sum(count > 2 for count in edges.values())
    # Group by shared edges, never by shared vertices alone. Sort patches by
    # their first face so that exported results are reproducible across runs.
    patch_area_mesh_units: dict[int, float] = {}
    patch_first_face: dict[int, int] = {}
    patch_face_counts: dict[int, int] = {}
    patch_degenerate_faces: Counter[int] = Counter()
    patch_vertex_indices: dict[int, set[int]] = {}
    patch_centroid_moments: dict[int, list[float]] = {}
    patch_triangles: dict[int, list[list[tuple[float, float, float]]]] = {}
    patch_faces: dict[int, list[list[int]]] = {}
    for face_index, face_area in enumerate(face_areas):
        patch = root(face_index)
        patch_area_mesh_units[patch] = patch_area_mesh_units.get(patch, 0.0) + face_area
        patch_face_counts[patch] = patch_face_counts.get(patch, 0) + 1
        if face_area == 0:
            patch_degenerate_faces[patch] += 1
        patch_vertex_indices.setdefault(patch, set()).update(faces[face_index])
        moment = patch_centroid_moments.setdefault(patch, [0.0, 0.0, 0.0])
        for axis in range(3):
            moment[axis] += face_area * sum(points[index][axis] for index in faces[face_index]) / 3
        patch_triangles.setdefault(patch, []).append(
            sorted(points[index] for index in faces[face_index])
        )
        patch_faces.setdefault(patch, []).append(faces[face_index])
        patch_first_face.setdefault(patch, face_index)
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
    patch_boundary_lengths_mesh_units: dict[int, float] = {}
    patch_boundary_graph_edges: dict[int, list[tuple[int, int]]] = {}
    for (a, b), incidents in edge_faces.items():
        patch = root(incidents[0][0])
        patch_edge_counts[patch] += 1
        if len(incidents) == 1:
            patch_boundary_edges[patch] += 1
            patch_boundary_graph_edges.setdefault(patch, []).append((a, b))
            patch_boundary_lengths_mesh_units[patch] = patch_boundary_lengths_mesh_units.get(
                patch, 0.0
            ) + dist(points[a], points[b])
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
    patch_boundary_lengths_m = [
        patch_boundary_lengths_mesh_units.get(patch, 0.0) * scale for patch in ordered_patches
    ]
    boundary_length_m = sum(patch_boundary_lengths_m)
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
            raw_volume = abs(
                spatial_mesh_volume_v14.signed_enclosed_volume_mesh_units(
                    points, patch_faces[patch]
                )
            )
            calibrated_volume = raw_volume * scale**3
        except (ValueError, OverflowError):
            calibrated_volume = float("inf")
            raw_volume = float("inf")
        if not isfinite(calibrated_volume):
            patch_volumes_m3.append(None)
            volume_qc_warnings.add("enclosed_volume_numeric_overflow")
        elif raw_volume == 0 or calibrated_volume == 0:
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
    patch_areas_m2 = [patch_area_mesh_units[patch] * scale * scale for patch in ordered_patches]
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
    patch_dimensions_m = [
        [
            (
                max(points[index][axis] for index in patch_vertex_indices[patch])
                - min(points[index][axis] for index in patch_vertex_indices[patch])
            )
            * scale
            for axis in range(3)
        ]
        for patch in ordered_patches
    ]
    # Triangle-area-weighted centroids are coordinates in the imported source
    # frame, not registered positions or evidence of organism identity.
    # A zero-area patch has no mathematically defined surface centroid.
    patch_centroids_m = [
        (
            [
                moment * scale / patch_area_mesh_units[patch]
                for moment in patch_centroid_moments[patch]
            ]
            if patch_area_mesh_units[patch] > 0
            else None
        )
        for patch in ordered_patches
    ]
    centroid_m = (
        [
            sum(patch_centroid_moments[patch][axis] for patch in ordered_patches) * scale / raw_area
            for axis in range(3)
        ]
        if raw_area > 0
        else None
    )
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
    display_geometry = _sample_mesh_display_geometry(points, faces, scale)
    sampled_raw_area = sum(face_areas[index] for index in display_geometry["preview_face_indices"])
    return {
        "schema_version": "mesh-preview-0001",
        "surface_area_m2": area_m2,
        "enclosed_volume_m3": enclosed_volume_m3,
        "edge_connected_patch_enclosed_volumes_m3": patch_volumes_m3,
        "enclosed_volume_scale_interval_m3": (
            [
                enclosed_volume_m3 * (1 - relative_scale_uncertainty) ** 3,
                enclosed_volume_m3 * (1 + relative_scale_uncertainty) ** 3,
            ]
            if enclosed_volume_m3 is not None and relative_scale_uncertainty is not None
            else None
        ),
        "edge_connected_patch_enclosed_volume_scale_intervals_m3": (
            [
                (
                    [
                        volume * (1 - relative_scale_uncertainty) ** 3,
                        volume * (1 + relative_scale_uncertainty) ** 3,
                    ]
                    if volume is not None
                    else None
                )
                for volume in patch_volumes_m3
            ]
            if relative_scale_uncertainty is not None
            else None
        ),
        "enclosed_volume_is_provisional": True,
        "surface_to_enclosed_volume_ratio_per_m": surface_volume_ratio_per_m,
        "surface_to_enclosed_volume_ratio_scale_interval_per_m": _inverse_scale_interval_per_m(
            surface_volume_ratio_per_m, relative_scale_uncertainty
        ),
        "edge_connected_patch_surface_to_enclosed_volume_ratios_per_m": (
            patch_surface_volume_ratios_per_m
        ),
        "edge_connected_patch_surface_to_enclosed_volume_ratio_scale_intervals_per_m": (
            [
                _inverse_scale_interval_per_m(ratio, relative_scale_uncertainty)
                for ratio in patch_surface_volume_ratios_per_m
            ]
            if relative_scale_uncertainty is not None
            else None
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
        "area_weighted_effective_triangle_count": area_weighted_effective_triangle_count,
        **display_geometry,
        "preview_sampled_surface_area_m2": sampled_raw_area * scale * scale,
        "preview_surface_area_fraction": sampled_raw_area / raw_area if raw_area > 0 else None,
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
        "edge_connected_patch_area_scale_intervals_m2": (
            [
                [
                    area * (1 - relative_scale_uncertainty) ** 2,
                    area * (1 + relative_scale_uncertainty) ** 2,
                ]
                for area in patch_areas_m2
            ]
            if relative_scale_uncertainty is not None
            else None
        ),
        "inconsistent_winding_edge_count": inconsistent_winding_edge_count,
        "qc_warnings": (
            sorted(volume_qc_warnings)
            + (["degenerate_triangles_present"] if degenerate else [])
            + (["open_mesh_surface_not_enclosed"] if boundary else [])
            + (["noncycle_mesh_boundary_components"] if any(patch_noncycle_boundary_counts) else [])
            + (["nonmanifold_mesh_edges"] if nonmanifold else [])
            + (["disconnected_mesh_patches"] if edge_connected_patch_count > 1 else [])
            + (["vertex_touching_mesh_patches"] if vertex_touching_patch_vertices else [])
            + (["coincident_mesh_patch_coordinates"] if coincident_patch_coordinates else [])
            + (["inconsistent_face_winding"] if inconsistent_winding_edge_count else [])
            + (["unreferenced_mesh_vertices"] if unreferenced_vertex_count else [])
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
        "surface_area_scale_interval_m2": (
            [
                area_m2 * (1 - relative_scale_uncertainty) ** 2,
                area_m2 * (1 + relative_scale_uncertainty) ** 2,
            ]
            if relative_scale_uncertainty is not None
            else None
        ),
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
    if payload.obj_text is not None:
        vertices, faces = spatial_mesh_obj_v14.parse_obj_triangles(payload.obj_text)
        source_format = "obj"
    elif payload.ply_text is not None:
        vertices, faces = spatial_mesh_ply_v14.parse_ply_triangles(payload.ply_text)
        source_format = "ply_ascii"
    elif payload.glb_base64 is not None:
        vertices, faces = spatial_mesh_glb_v14.parse_glb_triangles(payload.glb_base64)
        source_format = "glb_2_0"
    else:
        vertices, faces = payload.vertices, payload.faces
        source_format = "indexed_triangles"
    result = measure_mesh_preview(
        vertices=vertices,
        faces=faces,
        meters_per_unit=payload.meters_per_unit,
        calibration_method=payload.calibration_method,
        calibration_evidence=payload.calibration_evidence,
        relative_scale_uncertainty=payload.relative_scale_uncertainty,
        source_label=payload.source_label,
        surface_path_vertex_pairs=payload.surface_path_vertex_pairs,
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
        coordinate_registration_verified=False,
        specimen_identity_verified=False,
        observation_metadata_verified=False,
    )
    return result
