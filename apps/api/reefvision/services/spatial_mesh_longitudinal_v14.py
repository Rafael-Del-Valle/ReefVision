"""Conservative, provisional comparison of two reviewed-as-unverified mesh previews."""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any


def compare_mesh_observations(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Compare two explicitly identified timepoints without asserting coral growth."""
    first = before.get("provenance") or {}
    second = after.get("provenance") or {}
    specimen = first.get("specimen_id")
    if not isinstance(specimen, str) or not specimen or specimen != second.get("specimen_id"):
        raise ValueError("Two observations require the same nonempty provisional specimen_id")
    first_id = first.get("observation_id")
    second_id = second.get("observation_id")
    if not all(isinstance(value, str) and value for value in (first_id, second_id)):
        raise ValueError("Both observations require nonempty observation_id values")
    if first_id == second_id:
        raise ValueError("Longitudinal comparison requires distinct observation_id values")
    try:
        before_time = datetime.fromisoformat(first["observed_at_utc"].replace("Z", "+00:00"))
        after_time = datetime.fromisoformat(second["observed_at_utc"].replace("Z", "+00:00"))
    except (KeyError, AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Both observations require valid UTC timestamps") from exc
    if (
        before_time.utcoffset() is None
        or after_time.utcoffset() is None
        or after_time <= before_time
    ):
        raise ValueError("Observations must have timezone-aware increasing timestamps")
    elapsed_days = (after_time - before_time).total_seconds() / 86400
    project_before = before.get("project_id")
    project_after = after.get("project_id")
    if project_before != project_after:
        raise ValueError("Longitudinal observations must belong to the same project")
    if before.get("schema_version") != "mesh-preview-0001" or (
        after.get("schema_version") != "mesh-preview-0001"
    ):
        raise ValueError("Only ReefVision 1.4 mesh measurement previews are supported")
    if before.get("measurement_status") != "caller_supplied_unverified" or (
        after.get("measurement_status") != "caller_supplied_unverified"
    ):
        raise ValueError("Comparison requires original unverified measurement previews")
    if first.get("calibration_verified") is not False or (
        second.get("calibration_verified") is not False
    ):
        raise ValueError("Unexpected calibration verification state")
    # Preserve the actual reconstruction QC at each timepoint. A longitudinal
    # difference must not hide an open, degenerate, or nonmanifold source mesh.
    observation_qc: list[list[str]] = []
    for record in (before, after):
        source_warnings = record.get("qc_warnings", [])
        if not isinstance(source_warnings, list) or any(
            not isinstance(warning, str) for warning in source_warnings
        ):
            raise ValueError("Mesh preview QC warnings must be lists of strings")
        observation_qc.append(list(source_warnings))
    a0 = before.get("surface_area_m2")
    a1 = after.get("surface_area_m2")
    # Narrow each value before arithmetic; a missing area must not reach isfinite.
    if (
        not isinstance(a0, (int, float))
        or isinstance(a0, bool)
        or not isfinite(a0)
        or a0 < 0
        or not isinstance(a1, (int, float))
        or isinstance(a1, bool)
        or not isfinite(a1)
        or a1 < 0
    ):
        raise ValueError("Both surface areas must be finite and nonnegative")
    difference = a1 - a0
    relative = (100 * difference / a0) if a0 > 0 else None
    if relative is not None and not isfinite(relative):
        relative = None

    # Independent per-timepoint scale bounds: subtract worst-case endpoints.
    # Never infer zero uncertainty when a calibration interval is absent.
    bounds: list[list[float]] = []
    for record in (before, after):
        pair = record.get("surface_area_scale_interval_m2")
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or any(type(v) not in (int, float) or not isfinite(v) or v < 0 for v in pair)
            or pair[0] > pair[1]
            or pair[0] > record["surface_area_m2"]
            or pair[1] < record["surface_area_m2"]
        ):
            bounds = []
            break
        bounds.append(pair)
    difference_bounds = (
        [bounds[1][0] - bounds[0][1], bounds[1][1] - bounds[0][0]] if len(bounds) == 2 else None
    )
    relative_bounds = (
        [
            100 * (bounds[1][0] / bounds[0][1] - 1),
            100 * (bounds[1][1] / bounds[0][0] - 1),
        ]
        if len(bounds) == 2 and bounds[0][0] > 0
        else None
    )
    if relative_bounds is not None and not all(isfinite(v) for v in relative_bounds):
        relative_bounds = None
    # Descriptive average change per elapsed day, not an estimated growth rate.
    rate = difference / elapsed_days
    rate_bounds = (
        [value / elapsed_days for value in difference_bounds]
        if difference_bounds is not None
        else None
    )
    if not isfinite(rate) or (
        rate_bounds is not None and not all(isfinite(v) for v in rate_bounds)
    ):
        raise ValueError("Surface-area change rate exceeds finite numeric range")
    # Bounding-box diagonals are rotation-dependent geometric extents, not branch lengths.
    # Keep this optional for older preview artifacts; never invent missing measurements.
    extents: list[float | None] = []
    for record in (before, after):
        value = record.get("axis_aligned_bounding_box_diagonal_m")
        if value is None:
            extents.append(None)
        elif type(value) in (int, float) and isfinite(value) and value >= 0:
            extents.append(float(value))
        else:
            raise ValueError("Bounding-box diagonals must be finite and nonnegative")
    early_extent, late_extent = extents
    extent_delta = (
        late_extent - early_extent if early_extent is not None and late_extent is not None else None
    )
    extent_rate = extent_delta / elapsed_days if extent_delta is not None else None
    extent_intervals: list[list[float]] = []
    if extent_delta is not None:
        for record, nominal in zip((before, after), extents, strict=True):
            pair = record.get("axis_aligned_bounding_box_diagonal_scale_interval_m")
            if (
                nominal is None
                or not isinstance(pair, list)
                or len(pair) != 2
                or any(type(v) not in (int, float) or not isfinite(v) or v < 0 for v in pair)
                or pair[0] > nominal
                or pair[1] < nominal
            ):
                extent_intervals = []
                break
            extent_intervals.append(pair)
    extent_delta_bounds = (
        [
            extent_intervals[1][0] - extent_intervals[0][1],
            extent_intervals[1][1] - extent_intervals[0][0],
        ]
        if len(extent_intervals) == 2
        else None
    )
    extent_rate_bounds = (
        [value / elapsed_days for value in extent_delta_bounds]
        if extent_delta_bounds is not None
        else None
    )
    # Relative change is undefined for a zero baseline. These are descriptive
    # reconstruction extents, not biological growth or branch-length changes.
    extent_relative = (
        100 * (late_extent / early_extent - 1)
        if early_extent is not None and early_extent > 0 and late_extent is not None
        else None
    )
    extent_relative_bounds = (
        [
            100 * (extent_intervals[1][0] / extent_intervals[0][1] - 1),
            100 * (extent_intervals[1][1] / extent_intervals[0][0] - 1),
        ]
        if len(extent_intervals) == 2 and extent_intervals[0][0] > 0
        else None
    )
    if extent_relative is not None and not isfinite(extent_relative):
        extent_relative = None
    if extent_relative_bounds is not None and not all(
        isfinite(value) for value in extent_relative_bounds
    ):
        extent_relative_bounds = None
    if any(not isfinite(value) for value in (extent_delta, extent_rate) if value is not None) or (
        extent_rate_bounds is not None and not all(isfinite(value) for value in extent_rate_bounds)
    ):
        raise ValueError("Bounding-box extent change exceeds finite numeric range")
    warnings = [
        "specimen_identity_not_verified",
        "observation_metadata_not_verified",
        "calibration_not_verified",
        "reconstruction_and_registration_uncertainty_not_estimated",
        "surface_area_change_is_not_verified_biological_growth",
        "average_change_per_day_is_not_a_biological_growth_rate",
    ]
    if any(observation_qc):
        warnings.append("source_mesh_qc_requires_review")
    for field, warning in (
        ("source_format", "mesh_source_formats_differ_between_observations"),
        ("calibration_method", "calibration_methods_differ_between_observations"),
    ):
        if first.get(field) and second.get(field) and first[field] != second[field]:
            warnings.append(warning)
    if extent_delta is not None:
        warnings.append("axis_aligned_extent_change_is_not_verified_branch_growth")
        if extent_relative is None:
            warnings.append("relative_axis_aligned_extent_change_unavailable")
        if extent_delta_bounds is None:
            warnings.append("extent_scale_uncertainty_interval_unavailable")
    else:
        warnings.append("axis_aligned_extent_comparison_unavailable")
    if first.get("geometry_sha256") and (
        first.get("geometry_sha256") == second.get("geometry_sha256")
    ):
        warnings.append("identical_geometry_fingerprint")
    if difference_bounds is None:
        warnings.append("scale_uncertainty_interval_unavailable")
    return {
        "schema_version": "mesh-longitudinal-comparison-0001",
        "specimen_id": specimen,
        "before_observation_id": first_id,
        "after_observation_id": second_id,
        "before_observed_at_utc": first["observed_at_utc"],
        "after_observed_at_utc": second["observed_at_utc"],
        "elapsed_days": elapsed_days,
        "before_mesh_qc_warnings": observation_qc[0],
        "after_mesh_qc_warnings": observation_qc[1],
        "before_surface_area_m2": a0,
        "after_surface_area_m2": a1,
        "delta_surface_area_m2": difference,
        "before_axis_aligned_bounding_box_diagonal_m": early_extent,
        "after_axis_aligned_bounding_box_diagonal_m": late_extent,
        "delta_axis_aligned_bounding_box_diagonal_m": extent_delta,
        "relative_axis_aligned_bounding_box_diagonal_change_percent": extent_relative,
        "relative_axis_aligned_bounding_box_diagonal_scale_interval_percent": (
            extent_relative_bounds
        ),
        "delta_axis_aligned_bounding_box_diagonal_scale_interval_m": extent_delta_bounds,
        "average_axis_aligned_bounding_box_diagonal_change_m_per_day": extent_rate,
        "average_axis_aligned_bounding_box_diagonal_change_"
        "scale_interval_m_per_day": extent_rate_bounds,
        "average_surface_area_change_m2_per_day": rate,
        "average_surface_area_change_scale_interval_m2_per_day": rate_bounds,
        "delta_surface_area_scale_interval_m2": difference_bounds,
        "relative_surface_area_change_percent": relative,
        "relative_surface_area_scale_interval_percent": relative_bounds,
        "measurement_status": "provisional_unverified_longitudinal_comparison",
        "qc_warnings": warnings,
        "project_id": project_before,
        "provenance": {
            "before_geometry_sha256": first.get("geometry_sha256"),
            "after_geometry_sha256": second.get("geometry_sha256"),
            "before_calibration_evidence": first.get("calibration_evidence"),
            "after_calibration_evidence": second.get("calibration_evidence"),
            "specimen_identity_verified": False,
            "coordinate_registration_verified": False,
            "observation_metadata_verified": False,
            "calibration_verified": False,
            "scale_uncertainty_only": difference_bounds is not None,
        },
    }
