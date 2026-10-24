"""Conservative, provisional comparison of two reviewed-as-unverified mesh previews."""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any


def compare_mesh_observations(
    before: dict[str, Any], after: dict[str, Any]
) -> dict[str, Any]:
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
    a0 = before.get("surface_area_m2")
    a1 = after.get("surface_area_m2")
    if any(type(value) not in (int, float) or not isfinite(value) or value < 0 for value in (a0, a1)):
        raise ValueError("Both surface areas must be finite and nonnegative")
    difference = a1 - a0
    relative = (100 * difference / a0) if a0 > 0 else None
    if relative is not None and not isfinite(relative):
        relative = None

    # Independent per-timepoint scale bounds: subtract worst-case endpoints.
    # Never infer zero uncertainty when a calibration interval is absent.
    bounds = []
    for record in (before, after):
        pair = record.get("surface_area_scale_interval_m2")
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or any(type(v) not in (int, float) or not isfinite(v) or v < 0 for v in pair)
            or pair[0] > pair[1]
        ):
            bounds = []
            break
        bounds.append(pair)
    difference_bounds = (
        [bounds[1][0] - bounds[0][1], bounds[1][1] - bounds[0][0]]
        if len(bounds) == 2
        else None
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
    warnings = [
        "specimen_identity_not_verified",
        "observation_metadata_not_verified",
        "calibration_not_verified",
        "reconstruction_and_registration_uncertainty_not_estimated",
        "surface_area_change_is_not_verified_biological_growth",
    ]
    if first.get("geometry_sha256") == second.get("geometry_sha256"):
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
        "elapsed_days": (after_time - before_time).total_seconds() / 86400,
        "before_surface_area_m2": a0,
        "after_surface_area_m2": a1,
        "delta_surface_area_m2": difference,
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
