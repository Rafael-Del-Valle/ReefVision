"""Bounded, explicitly unverified mesh surface measurement preview."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from math import isfinite
from typing import Any

from reefvision.services.spatial_mesh_glb_v14 import parse_glb_triangles
from reefvision.services.spatial_mesh_measurements import triangle_area
from reefvision.services.spatial_mesh_obj_v14 import (
    MAX_FACES,
    MAX_VERTICES,
    parse_obj_triangles,
)
from reefvision.services.spatial_mesh_ply_v14 import parse_ply_triangles


def measure_mesh_preview(
    *,
    vertices: list[list[float]],
    faces: list[list[int]],
    meters_per_unit: float,
    calibration_method: str,
    calibration_evidence: str,
    relative_scale_uncertainty: float | None = None,
    source_label: str | None = None,
) -> dict[str, Any]:
    if not 3 <= len(vertices) <= MAX_VERTICES or not 1 <= len(faces) <= MAX_FACES:
        raise ValueError("Mesh preview vertex/face count is outside supported bounds")
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
        not isfinite(float(relative_scale_uncertainty)) or not 0 <= relative_scale_uncertainty <= 1
    ):
        raise ValueError("relative_scale_uncertainty must be between 0 and 1")

    points: list[tuple[float, float, float]] = []
    for vertex in vertices:
        if len(vertex) != 3 or any(
            not isfinite(float(value)) or abs(float(value)) > 1_000_000_000 for value in vertex
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
    raw_area = 0.0
    degenerate = 0
    for face_index, face in enumerate(faces):
        if (
            len(face) != 3
            or any(index < 0 or index >= len(points) for index in face)
            or len(set(face)) != 3
        ):
            raise ValueError("Every face must reference three distinct existing vertices")
        ordered = sorted(face)
        key = (ordered[0], ordered[1], ordered[2])
        if key in seen_faces:
            raise ValueError("Duplicate triangles would double-count surface area")
        seen_faces.add(key)
        area = triangle_area(points[face[0]], points[face[1]], points[face[2]])
        if not isfinite(area):
            raise ValueError("Mesh triangle area overflowed")
        degenerate += area == 0
        raw_area += area
        for a, b in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            edge = (min(a, b), max(a, b))
            edges[edge] += 1
            incidents = edge_faces.setdefault(edge, [])
            if incidents:
                parents[root(face_index)] = root(incidents[0][0])
            incidents.append((face_index, a < b))
    area_m2 = raw_area * scale * scale
    if not isfinite(area_m2):
        raise ValueError("Calibrated area overflowed")
    referenced_indices = {index for face in faces for index in face}
    referenced_points = [points[index] for index in sorted(referenced_indices)]
    unreferenced_vertex_count = len(points) - len(referenced_points)
    dimensions = [
        (max(p[axis] for p in referenced_points) - min(p[axis] for p in referenced_points))
        * scale
        for axis in range(3)
    ]
    boundary = sum(count == 1 for count in edges.values())
    nonmanifold = sum(count > 2 for count in edges.values())
    edge_connected_patch_count = len({root(index) for index in range(len(faces))})
    inconsistent_winding_edge_count = sum(
        len(incidents) == 2 and incidents[0][1] == incidents[1][1]
        for incidents in edge_faces.values()
    )
    geometry_hash = hashlib.sha256(
        json.dumps(
            {"vertices": points, "faces": faces}, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": "mesh-preview-0001",
        "surface_area_m2": area_m2,
        "axis_aligned_dimensions_m": dimensions,
        "face_count": len(faces),
        "vertex_count": len(points),
        "unreferenced_vertex_count": unreferenced_vertex_count,
        "degenerate_face_count": degenerate,
        "boundary_edge_count": boundary,
        "nonmanifold_edge_count": nonmanifold,
        "edge_connected_patch_count": edge_connected_patch_count,
        "inconsistent_winding_edge_count": inconsistent_winding_edge_count,
        "qc_warnings": (
            (["degenerate_triangles_present"] if degenerate else [])
            + (["open_mesh_surface_not_enclosed"] if boundary else [])
            + (["nonmanifold_mesh_edges"] if nonmanifold else [])
            + (["disconnected_mesh_patches"] if edge_connected_patch_count > 1 else [])
            + (["inconsistent_face_winding"] if inconsistent_winding_edge_count else [])
            + (["unreferenced_mesh_vertices"] if unreferenced_vertex_count else [])
        ),
        "area_scale_uncertainty_m2": (
            2 * relative_scale_uncertainty * area_m2
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
        vertices, faces = parse_obj_triangles(payload.obj_text)
        source_format = "obj"
    elif payload.ply_text is not None:
        vertices, faces = parse_ply_triangles(payload.ply_text)
        source_format = "ply_ascii"
    elif payload.glb_base64 is not None:
        vertices, faces = parse_glb_triangles(payload.glb_base64)
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
    )
    result["provenance"]["source_format"] = source_format
    return result
