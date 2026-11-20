"""Measure an explicitly declared centerline in the verified source bytes' frame."""

from __future__ import annotations

from itertools import pairwise
from math import dist, fsum, isfinite
from typing import Any

from reefvision.schemas.spatial_anatomical_branch_v14 import AnatomicalBranchDeclaration
from reefvision.services.spatial_mesh_paths_v14 import _scale_only_length_interval


def measure_declared_centerline(
    declaration: AnatomicalBranchDeclaration, mesh: dict[str, Any]
) -> dict[str, Any]:
    points = declaration.ordered_points_source_units
    provenance = mesh["provenance"]
    scale = provenance["meters_per_mesh_unit"]
    bounds = mesh["preview_referenced_bounds_in_source_frame_m"]
    minimum, maximum = bounds["minimum"], bounds["maximum"]
    if any(
        not minimum[axis] <= coordinate * scale <= maximum[axis]
        for point in points
        for axis, coordinate in enumerate(point)
    ):
        raise ValueError("Centerline points must lie within the source mesh coordinate bounds")
    try:
        length_m = fsum(dist(a, b) for a, b in pairwise(points)) * scale
    except OverflowError as exc:
        raise ValueError("Centerline length cannot be represented at the declared scale") from exc
    if not isfinite(length_m) or length_m <= 0:
        raise ValueError("Centerline length cannot be represented at the declared scale")

    scale_bounds = _scale_only_length_interval(length_m, provenance["relative_scale_uncertainty"])
    if scale_bounds is not None and not all(isfinite(bound) for bound in scale_bounds):
        scale_bounds = None

    evidence_status = "provisional_missing_evidence"
    reference_error = repeatability_range = None
    protocol = declaration.protocol
    if protocol is not None:
        reference_error = abs(length_m - protocol.independent_reference_length_m)
        repeatability_range = max(protocol.repeated_lengths_m) - min(protocol.repeated_lengths_m)
        if (
            reference_error > protocol.maximum_reference_error_m
            or repeatability_range > protocol.maximum_repeatability_range_m
        ):
            evidence_status = "declared_tolerances_exceeded"
        elif scale_bounds is not None:
            evidence_status = "awaiting_independent_adjudication"

    return {
        "schema_version": "anatomical-branch-centerline-1",
        "declaration": declaration.model_dump(mode="json"),
        "coordinate_frame_id": provenance["coordinate_frame_id"],
        "source_payload_sha256": provenance["source_payload_sha256"],
        "geometry_sha256": provenance["geometry_sha256"],
        "length_method": "ordered_source_coordinate_polyline",
        "length_m": length_m,
        "scale_only_length_interval_m": scale_bounds,
        "reference_absolute_error_m": reference_error,
        "repeatability_range_m": repeatability_range,
        "evidence_status": evidence_status,
        "anatomical_claim_verified": False,
    }
