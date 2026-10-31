"""Conservative, provisional comparison of two reviewed-as-unverified mesh previews."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from itertools import zip_longest
from json import dumps
from math import atan2, degrees, exp, fsum, hypot, isclose, isfinite, log, log2
from re import fullmatch
from typing import Any

from pydantic import ValidationError

from reefvision.schemas.spatial_mesh_preview_v14 import (
    MeshRegistrationEvidence,
    MeshReidentificationEvidence,
)


def _is_sha256_fingerprint(value: Any) -> bool:
    """Check format only; caller-supplied hashes remain unverified evidence."""
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_source_import_provenance(metadata: dict[str, Any]) -> None:
    """Reject malformed source-integrity claims without certifying imported bytes.

    Older previews may omit source fields; missing evidence remains unknown.
    A caller-supplied hash or check flag is never proof of source authenticity.
    """
    digest = metadata.get("source_payload_sha256")
    size = metadata.get("source_payload_size_bytes")
    checked = metadata.get("source_payload_integrity_checked")
    if digest is not None and not _is_sha256_fingerprint(digest):
        raise ValueError("Source payload SHA-256 must be lowercase hexadecimal")
    if size is not None and (type(size) is not int or size < 0):
        raise ValueError("Source payload size must be a nonnegative integer")
    if checked is not None and type(checked) is not bool:
        raise ValueError("Source payload integrity check must be boolean")
    source_format = metadata.get("source_format")
    if source_format is not None and source_format not in (
        "indexed_triangles",
        "obj",
        "ply_ascii",
        "glb_2_0",
    ):
        raise ValueError("Unsupported mesh source format")
    # Inline indexed triangles have no imported original. Reject contradictory
    # source-byte claims even when the caller has not requested a hash check.
    if source_format == "indexed_triangles" and (digest is not None or size is not None):
        raise ValueError("Inline indexed triangles cannot carry imported source payload")
    if checked is True and digest is None:
        raise ValueError("Source payload integrity check requires a source SHA-256")
    # A checked digest must refer to actual imported bytes. Indexed triangles
    # have no source file to check, and an absent/empty byte count cannot
    # substantiate a successful comparison with an expected file digest.
    if checked is True and metadata.get("source_format") not in (
        "obj",
        "ply_ascii",
        "glb_2_0",
    ):
        raise ValueError("Source payload integrity check requires an imported mesh format")
    if checked is True and (size is None or size == 0):
        raise ValueError("Source payload integrity check requires a positive source byte count")
    if source_format is None and (digest is not None or size is not None):
        raise ValueError("Source payload metadata requires an imported mesh format")


def _patch_area_concentration(record: dict[str, Any]) -> tuple[float, float] | None:
    """Recompute scale-invariant patch concentration from complete-mesh fractions.

    Never trust a stored concentration without its fractions. Source patch order
    is not a cross-survey identity, so only permutation-invariant QC is compared.
    """
    fractions = record.get("edge_connected_patch_surface_area_fractions")
    stored = (
        record.get("edge_connected_patch_area_concentration_index"),
        record.get("area_weighted_effective_patch_count"),
    )
    patch_count = record.get("edge_connected_patch_count")
    if patch_count is not None and (type(patch_count) is not int or patch_count < 0):
        raise ValueError("Patch count must be a nonnegative integer")
    if fractions is None:
        # Zero-area reconstructions have no defined area distribution, even
        # when degenerate triangles produce one or more geometric patches.
        # A valid modern zero-area preview records a zero for every patch;
        # never mistake positive, missing, or malformed area evidence for it.
        patch_areas = record.get("edge_connected_patch_surface_areas_m2")
        if any(value is not None for value in stored):
            raise ValueError("Patch concentration requires source area fractions")
        if patch_areas is not None and (
            not isinstance(patch_areas, list)
            or (patch_count is not None and len(patch_areas) != patch_count)
            or record.get("surface_area_m2") != 0
            or any(
                type(area) not in (int, float) or not isfinite(area) or area != 0
                for area in patch_areas
            )
        ):
            raise ValueError("Patch concentration requires source area fractions")
        return None
    if (
        not isinstance(fractions, list)
        or not fractions
        or any(
            type(value) not in (int, float) or not isfinite(value) or not 0 <= value <= 1
            for value in fractions
        )
    ):
        raise ValueError("Patch area fractions must be a nonempty finite unit-range list")
    if patch_count is not None and len(fractions) != patch_count:
        raise ValueError("Patch area fractions inconsistent with topology patch count")
    if not isclose(fsum(fractions), 1.0, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError("Patch area fractions must sum to one")
    # A ranked distribution must be derived from the actual full-mesh patch
    # areas, not independently editable summary fractions. Older artifacts
    # without per-patch areas remain readable but cannot gain this binding.
    patch_areas = record.get("edge_connected_patch_surface_areas_m2")
    if patch_areas is not None:
        if (
            not isinstance(patch_areas, list)
            or len(patch_areas) != len(fractions)
            or any(
                type(area) not in (int, float) or not isfinite(area) or area < 0
                for area in patch_areas
            )
        ):
            raise ValueError("Patch surface areas must be finite nonnegative matching entries")
        try:
            area_total = fsum(patch_areas)
        except OverflowError as exc:
            raise ValueError("Patch surface areas exceed finite numeric range") from exc
        source_total = record.get("surface_area_m2")
        if (
            not isinstance(source_total, (int, float))
            or isinstance(source_total, bool)
            or not isfinite(source_total)
            or source_total <= 0
            or not isclose(area_total, source_total, rel_tol=1e-9, abs_tol=0.0)
            or any(
                not isclose(area / source_total, fraction, rel_tol=1e-9, abs_tol=1e-12)
                for area, fraction in zip(patch_areas, fractions, strict=True)
            )
        ):
            raise ValueError("Patch surface areas contradict full-mesh area fractions")
    concentration = fsum(fraction * fraction for fraction in fractions)
    effective_count = 1.0 / concentration if concentration > 0 else float("inf")
    if not isfinite(effective_count):
        raise ValueError("Patch area concentration is outside numeric bounds")
    for claimed, expected in zip(stored, (concentration, effective_count), strict=True):
        if claimed is not None and (
            type(claimed) not in (int, float)
            or not isfinite(claimed)
            or not isclose(claimed, expected, rel_tol=1e-9, abs_tol=1e-9)
        ):
            raise ValueError("Stored patch concentration contradicts source area fractions")
    return concentration, effective_count


def compare_mesh_observations(
    before: dict[str, Any],
    after: dict[str, Any],
    registration_evidence: MeshRegistrationEvidence | dict[str, Any] | None = None,
    reidentification_evidence: MeshReidentificationEvidence | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare two explicitly identified timepoints without asserting coral growth."""
    first = before.get("provenance")
    second = after.get("provenance")
    if not isinstance(first, dict) or not isinstance(second, dict):
        raise ValueError("Both observations require provenance dictionaries")
    for metadata in (first, second):
        _validate_source_import_provenance(metadata)
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
    if not isinstance(project_before, str) or not project_before or project_before != project_after:
        raise ValueError("Longitudinal observations require the same nonempty project_id")
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
    # Geometry topology is an acquisition/reconstruction QC diagnostic, not
    # evidence of colony fragmentation, growth, or biological condition.
    topology_fields = (
        "face_count",
        "edge_connected_patch_count",
        "boundary_edge_count",
        "nonmanifold_edge_count",
        "degenerate_face_count",
    )
    topology_counts: list[dict[str, int | None]] = []
    for record in (before, after):
        counts: dict[str, int | None] = {}
        for field in topology_fields:
            value = record.get(field)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{field} must be a nonnegative integer when present")
            counts[field] = value
        # Each edge-connected patch contains at least one face. Every face
        # contributes at most three distinct edges, and a degenerate face
        # cannot exceed the total number of faces. Validate only when the
        # necessary fields are present so older artifacts remain readable.
        face_count = counts["face_count"]
        if face_count is not None:
            patch_count = counts["edge_connected_patch_count"]
            if patch_count is not None and (
                patch_count > face_count or (face_count > 0 and patch_count == 0)
            ):
                raise ValueError("Mesh topology patch count inconsistent with face_count")
            degenerate_count = counts["degenerate_face_count"]
            if degenerate_count is not None and degenerate_count > face_count:
                raise ValueError("Mesh topology degenerate count inconsistent with face_count")
            for edge_field in ("boundary_edge_count", "nonmanifold_edge_count"):
                edge_count = counts[edge_field]
                if edge_count is not None and edge_count > 3 * face_count:
                    raise ValueError(f"Mesh topology {edge_field} inconsistent with face_count")
        topology_counts.append(counts)
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
    # Divide before multiplying: 100 * a finite large delta can overflow even
    # when the actual percent change is representable (e.g. 1e307 / 1e307).
    relative = ((difference / a0) * 100) if a0 > 0 else None
    if relative is not None and not isfinite(relative):
        relative = None

    # Independent per-timepoint scale bounds: subtract worst-case endpoints.
    # Never infer zero uncertainty when a calibration interval is absent.
    bounds: list[list[float]] = []
    for record, metadata in zip((before, after), (first, second), strict=True):
        pair = record.get("surface_area_scale_interval_m2")
        # Legacy previews without uncertainty metadata cannot authenticate a
        # supplied scale interval. Reject rather than assume zero uncertainty.
        if pair is not None and "relative_scale_uncertainty" not in metadata:
            raise ValueError("Surface-area scale interval requires source uncertainty")
        # A supplied interval must agree with the source preview's scale
        # uncertainty. Merely enclosing the nominal area would permit a
        # forged, arbitrarily narrow longitudinal uncertainty interval.
        if "relative_scale_uncertainty" in metadata:
            uncertainty = metadata["relative_scale_uncertainty"]
            if uncertainty is not None and (
                type(uncertainty) not in (int, float)
                or not isfinite(uncertainty)
                or not 0 <= uncertainty <= 1
            ):
                raise ValueError("Source relative scale uncertainty invalid")
            if pair is not None:
                if uncertainty is None:
                    raise ValueError("Surface-area scale interval requires source uncertainty")
                if (
                    isinstance(pair, list)
                    and len(pair) == 2
                    and all(type(value) in (int, float) and isfinite(value) for value in pair)
                ):
                    nominal = record["surface_area_m2"]
                    expected = (
                        nominal * (1 - uncertainty) ** 2,
                        nominal * (1 + uncertainty) ** 2,
                    )
                    if not all(
                        isclose(value, bound, rel_tol=1e-9, abs_tol=0.0)
                        for value, bound in zip(pair, expected, strict=True)
                    ):
                        raise ValueError(
                            "Surface-area scale interval contradicts source uncertainty"
                        )
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or any(type(v) not in (int, float) or not isfinite(v) or v < 0 for v in pair)
            or pair[0] > pair[1]
            or pair[0] > record["surface_area_m2"]
            or pair[1] < record["surface_area_m2"]
        ):
            bounds = []
            continue
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
    # A dimensionless reconstruction descriptor from the full source mesh.
    # Missing values in older artifacts stay unknown; never infer them from
    # nominal calibrated values, which may underflow at extreme scales.
    shape_ratios: list[float | None] = []
    for record, extent in zip((before, after), extents, strict=True):
        value = record.get("surface_area_to_bounding_diagonal_squared_ratio")
        if value is None:
            shape_ratios.append(None)
        elif type(value) in (int, float) and isfinite(value) and value >= 0:
            # A saved summary must agree with the source preview's area and
            # diagonal. Otherwise a changed ratio could fabricate longitudinal
            # morphology change without changing either measurement.
            # Only cross-check representable positive calibrated values: at
            # extreme scales, area or squared extent can underflow to zero.
            area = record["surface_area_m2"]
            if area > 0 and extent is not None and extent > 0:
                # Compare in log space so extreme, but finite, calibrated
                # values cannot bypass integrity checks via overflow/underflow.
                expected_log_ratio = log(area) - 2 * log(extent)
                if value <= 0 or not isclose(
                    log(value), expected_log_ratio, rel_tol=0.0, abs_tol=1e-8
                ):
                    raise ValueError("Mesh shape ratio contradicts calibrated area and extent")
            shape_ratios.append(float(value))
        else:
            raise ValueError("Mesh shape ratios must be finite and nonnegative")
    before_shape_ratio, after_shape_ratio = shape_ratios
    shape_ratio_delta = (
        after_shape_ratio - before_shape_ratio
        if before_shape_ratio is not None and after_shape_ratio is not None
        else None
    )
    if shape_ratio_delta is not None and not isfinite(shape_ratio_delta):
        raise ValueError("Mesh shape ratio change exceeds finite numeric range")
    extent_delta = (
        late_extent - early_extent if early_extent is not None and late_extent is not None else None
    )
    extent_rate = extent_delta / elapsed_days if extent_delta is not None else None
    extent_intervals: list[list[float]] = []
    if extent_delta is not None:
        for record, nominal, metadata in zip(
            (before, after), extents, (first, second), strict=True
        ):
            pair = record.get("axis_aligned_bounding_box_diagonal_scale_interval_m")
            # A legacy preview lacking scale uncertainty cannot substantiate
            # a claimed diagonal interval, even if it encloses the nominal value.
            if pair is not None and "relative_scale_uncertainty" not in metadata:
                raise ValueError("Bounding-box scale interval requires source uncertainty")
            # A caller cannot substitute narrower scale-only extent bounds
            # than those implied by the source preview's uncertainty.
            if "relative_scale_uncertainty" in metadata and pair is not None:
                uncertainty = metadata["relative_scale_uncertainty"]
                if uncertainty is None:
                    raise ValueError("Bounding-box scale interval requires source uncertainty")
                if (
                    nominal is not None
                    and isinstance(pair, list)
                    and len(pair) == 2
                    and all(type(value) in (int, float) and isfinite(value) for value in pair)
                ):
                    expected = (
                        nominal * (1 - uncertainty),
                        nominal * (1 + uncertainty),
                    )
                    if not all(
                        isclose(value, bound, rel_tol=1e-9, abs_tol=0.0)
                        for value, bound in zip(pair, expected, strict=True)
                    ):
                        raise ValueError(
                            "Bounding-box scale interval contradicts source uncertainty"
                        )
            if (
                nominal is None
                or not isinstance(pair, list)
                or len(pair) != 2
                or any(type(v) not in (int, float) or not isfinite(v) or v < 0 for v in pair)
                or pair[0] > nominal
                or pair[1] < nominal
            ):
                extent_intervals = []
                continue
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
    # A geometry fingerprint describes source triangles, not calibrated size.
    # The same imported geometry can appear to grow solely because its scale
    # changed. Surface-area changes are still reported, but never certified.
    calibration_scales: list[float | None] = []
    for metadata in (first, second):
        raw_scale = metadata.get("meters_per_mesh_unit")
        if raw_scale is None:
            calibration_scales.append(None)
        elif type(raw_scale) in (int, float) and isfinite(raw_scale) and raw_scale > 0:
            calibration_scales.append(float(raw_scale))
        else:
            raise ValueError("Calibration scale metadata must be finite and positive")
    before_scale, after_scale = calibration_scales
    scale_ratio = (
        after_scale / before_scale if before_scale is not None and after_scale is not None else None
    )
    # Both scales are strictly positive. Floating-point overflow or a zero
    # quotient from positive underflow must not masquerade as a measured ratio.
    scale_ratio_out_of_range = False
    if scale_ratio is not None and (not isfinite(scale_ratio) or scale_ratio == 0):
        scale_ratio = None
        scale_ratio_out_of_range = True
    # Remove the *nominal* calibration-scale contribution to the area ratio.
    # This describes reconstruction geometry only when both scans use a common
    # source-unit convention; it does not establish registration or coral growth.
    # Work in log space to avoid intermediate squared-scale overflow.
    scale_normalized_area_ratio = None
    normalized_ratio_out_of_range = False
    if before_scale is not None and after_scale is not None and a0 > 0:
        if a1 == 0:
            # An exact zero observation is not positive floating-point underflow.
            scale_normalized_area_ratio = 0.0
        else:
            try:
                scale_normalized_area_ratio = exp(
                    log(a1) - log(a0) - 2 * (log(after_scale) - log(before_scale))
                )
            except OverflowError:
                normalized_ratio_out_of_range = True
            if scale_normalized_area_ratio == 0:
                # Only a positive ratio can underflow to floating-point zero.
                scale_normalized_area_ratio = None
                normalized_ratio_out_of_range = True
    # Remove nominal scale from axis-aligned diagonal ratios as a separate
    # reconstruction diagnostic. This is not a branch-length or growth metric.
    scale_normalized_extent_ratio = None
    extent_ratio_out_of_range = False
    if (
        before_scale is not None
        and after_scale is not None
        and early_extent is not None
        and early_extent > 0
        and late_extent is not None
    ):
        if late_extent == 0:
            # An exact zero observation is not positive floating-point underflow.
            scale_normalized_extent_ratio = 0.0
        else:
            try:
                scale_normalized_extent_ratio = exp(
                    log(late_extent) - log(early_extent) - (log(after_scale) - log(before_scale))
                )
            except OverflowError:
                extent_ratio_out_of_range = True
            if scale_normalized_extent_ratio == 0:
                # Positive ratios below float range must not masquerade as zero.
                scale_normalized_extent_ratio = None
                extent_ratio_out_of_range = True
    warnings = [
        "specimen_identity_not_verified",
        "observation_metadata_not_verified",
        "calibration_not_verified",
        "reconstruction_and_registration_uncertainty_not_estimated",
        "surface_area_change_is_not_verified_biological_growth",
        "average_change_per_day_is_not_a_biological_growth_rate",
    ]
    # Bind provisional matching notes to this pair of observations. They are
    # audit evidence, never a verified specimen-identity determination.
    reidentification_record = None
    identity_disputed = False
    identity_inconclusive = False
    if reidentification_evidence is None:
        warnings.append("reidentification_evidence_unavailable")
    else:
        evidence_values = (
            reidentification_evidence.model_dump(mode="python")
            if isinstance(reidentification_evidence, MeshReidentificationEvidence)
            else reidentification_evidence
        )
        try:
            identity = MeshReidentificationEvidence.model_validate(evidence_values)
        except ValueError as exc:
            raise ValueError("Invalid pairwise reidentification evidence") from exc
        if identity.before_observation_id != first_id or identity.after_observation_id != second_id:
            raise ValueError("Reidentification evidence must match both observation IDs")
        if identity.specimen_id is not None and identity.specimen_id != specimen:
            raise ValueError("Reidentification evidence must match the provisional specimen ID")
        # Local observation labels and geometry fingerprints are not globally
        # unique. Reject cross-project evidence reuse when a binding is supplied.
        if identity.project_id is None:
            warnings.append("reidentification_project_binding_unavailable")
        elif identity.project_id != project_before:
            raise ValueError("Reidentification evidence must match the project ID")
        # Bind evidence to the actual observation instants as well as IDs.
        # Legacy evidence without both timestamps remains provisional and flagged.
        if identity.before_observed_at_utc is None:
            warnings.append("reidentification_timepoint_binding_unavailable")
        elif (
            identity.before_observed_at_utc != before_time
            or identity.after_observed_at_utc != after_time
        ):
            raise ValueError("Reidentification evidence must match both observation timestamps")
        # Match both source geometry fingerprints, not only mutable labels.
        # Missing hashes remain supported for older evidence but are flagged.
        if identity.before_geometry_sha256 is None:
            warnings.append("reidentification_geometry_binding_unavailable")
        elif identity.before_geometry_sha256 != first.get(
            "geometry_sha256"
        ) or identity.after_geometry_sha256 != second.get("geometry_sha256"):
            raise ValueError(
                "Reidentification evidence must match both source geometry fingerprints"
            )
        reidentification_record = identity.model_dump(mode="json", exclude_none=True)
        if identity.specimen_id is None:
            warnings.append("reidentification_specimen_binding_unavailable")
        if identity.independent_reviewer_id is None:
            warnings.append("reidentification_evidence_requires_independent_review")
        else:
            # A dated review cannot precede the observation it claims to review.
            # Undated legacy review records are retained with explicit audit QC.
            if identity.independent_reviewed_at_utc is None:
                warnings.append("reidentification_independent_review_timestamp_unavailable")
            elif identity.independent_reviewed_at_utc < after_time:
                raise ValueError(
                    "Independent reidentification review predates the later observation"
                )
            # A reviewer decision is attributed evidence, not identity approval.
            warnings.append(
                "reidentification_independent_review_recorded_not_identity_verification"
            )
            if identity.independent_review_decision == "disputes_match":
                identity_disputed = True
                warnings.append("reidentification_independent_review_disputes_match")
            elif identity.independent_review_decision == "inconclusive":
                identity_inconclusive = True
                warnings.append("reidentification_independent_review_inconclusive")
    if scale_normalized_area_ratio is not None:
        warnings.append("scale_normalized_area_ratio_requires_common_units_and_registration")
    elif normalized_ratio_out_of_range:
        warnings.append("scale_normalized_area_ratio_out_of_numeric_range")
    else:
        warnings.append("scale_normalized_area_ratio_unavailable")
    if scale_normalized_extent_ratio is not None:
        warnings.append("scale_normalized_extent_ratio_requires_common_units_and_registration")
    elif extent_ratio_out_of_range:
        warnings.append("scale_normalized_extent_ratio_out_of_numeric_range")
    else:
        warnings.append("scale_normalized_extent_ratio_unavailable")
    if scale_ratio_out_of_range:
        warnings.append("calibration_scale_ratio_out_of_numeric_range")
    if before_scale is None or after_scale is None:
        warnings.append("calibration_scale_metadata_unavailable")
    elif before_scale != after_scale:
        warnings.append("calibration_scale_changed_between_observations")
    if shape_ratio_delta is None:
        warnings.append("mesh_shape_ratio_comparison_unavailable")
    else:
        warnings.append("mesh_shape_ratio_change_is_orientation_sensitive_reconstruction_qc")
    if a0 == 0:
        warnings.append("relative_surface_area_change_unavailable_zero_baseline")
    if a0 > 0 and a1 == 0:
        warnings.append("zero_followup_surface_area_requires_reconstruction_review")
    if early_extent is not None and early_extent > 0 and late_extent == 0:
        warnings.append("zero_followup_extent_requires_reconstruction_review")
    if any(observation_qc):
        warnings.append("source_mesh_qc_requires_review")
    before_topology, after_topology = topology_counts
    topology_changed_fields = [
        field
        for field in topology_fields
        if before_topology[field] is not None
        and after_topology[field] is not None
        and before_topology[field] != after_topology[field]
    ]
    if topology_changed_fields:
        warnings.append("reconstruction_topology_changed_requires_review")
    if any(
        before_topology[field] is None or after_topology[field] is None for field in topology_fields
    ):
        warnings.append("reconstruction_topology_comparison_incomplete")
    # Rates normalize reconstruction defects by the number of triangles, so
    # scans with different tessellation densities can be compared descriptively.
    # These are mesh-acquisition QC indicators, NOT biological condition scores.
    qc_rate_sources = {
        "degenerate_face_fraction": "degenerate_face_count",
        "boundary_edges_per_face": "boundary_edge_count",
        "nonmanifold_edges_per_face": "nonmanifold_edge_count",
    }
    reconstruction_qc_rates: list[dict[str, float | None]] = []
    for counts in topology_counts:
        faces = counts["face_count"]
        rates: dict[str, float | None] = {}
        for label, field in qc_rate_sources.items():
            defect_count = counts[field]
            # Narrow both optional operands before division (also avoids
            # treating absent counts or a zero-face mesh as zero defects).
            rates[label] = (
                defect_count / faces
                if faces is not None and faces > 0 and defect_count is not None
                else None
            )
        reconstruction_qc_rates.append(rates)
    reconstruction_qc_rate_changes: dict[str, float | None] = {}
    for label in qc_rate_sources:
        before_rate = reconstruction_qc_rates[0][label]
        after_rate = reconstruction_qc_rates[1][label]
        reconstruction_qc_rate_changes[label] = (
            after_rate - before_rate if before_rate is not None and after_rate is not None else None
        )
    if any(value is not None for rates in reconstruction_qc_rates for value in rates.values()):
        warnings.append("reconstruction_qc_rates_not_biological_condition")
    else:
        warnings.append("reconstruction_qc_rates_unavailable")
    # Complete-mesh area concentration is independent of a common scale and
    # of patch ordering. It is reconstruction QC, not coral fragmentation.
    patch_distributions = [_patch_area_concentration(record) for record in (before, after)]
    before_patch_distribution, after_patch_distribution = patch_distributions
    patch_concentration_delta = (
        after_patch_distribution[0] - before_patch_distribution[0]
        if before_patch_distribution is not None and after_patch_distribution is not None
        else None
    )
    effective_patch_count_delta = (
        after_patch_distribution[1] - before_patch_distribution[1]
        if before_patch_distribution is not None and after_patch_distribution is not None
        else None
    )
    # Compare *ranked* patch-area fractions, not corresponding patch indices.
    # Patches have no established cross-survey identity. Padding the shorter
    # distribution with zero makes the distance symmetric and defined even
    # when reconstructions contain different numbers of disconnected patches.
    ranked_patch_area_profile_distance = None
    ranked_patch_area_jensen_shannon_divergence_bits = None
    if before_patch_distribution is not None and after_patch_distribution is not None:
        ranked_before = sorted(before["edge_connected_patch_surface_area_fractions"], reverse=True)
        ranked_after = sorted(after["edge_connected_patch_surface_area_fractions"], reverse=True)
        ranked_patch_area_profile_distance = 0.5 * fsum(
            abs(early - late)
            for early, late in zip_longest(ranked_before, ranked_after, fillvalue=0.0)
        )
        # All source fractions have been validated as finite and summing to
        # one. Clamp only tiny floating-point overshoot of the [0, 1] bound.
        ranked_patch_area_profile_distance = min(1.0, max(0.0, ranked_patch_area_profile_distance))
        # An exactly zero float from distinct ranked fractions can reflect
        # subnormal underflow, not identical reconstructions.
        if ranked_before != ranked_after and ranked_patch_area_profile_distance == 0.0:
            ranked_patch_area_profile_distance = None
            warnings.append("ranked_patch_area_profile_distance_below_numeric_resolution")
        # Jensen-Shannon divergence (base-2, [0, 1]) detects changes in
        # ranked patch areas without claiming correspondence. Computing
        # 2 * p / (p + q) avoids a zero midpoint when p is subnormal and q=0.
        # Zero-area ranks contribute zero, including padded absent patches.
        ranked_patch_area_jensen_shannon_divergence_bits = fsum(
            0.5 * early * log2((2.0 * early) / (early + late)) if early > 0 else 0.0
            for early, late in zip_longest(ranked_before, ranked_after, fillvalue=0.0)
        ) + fsum(
            0.5 * late * log2((2.0 * late) / (early + late)) if late > 0 else 0.0
            for early, late in zip_longest(ranked_before, ranked_after, fillvalue=0.0)
        )
        ranked_patch_area_jensen_shannon_divergence_bits = min(
            1.0, max(0.0, ranked_patch_area_jensen_shannon_divergence_bits)
        )
        if (
            ranked_before != ranked_after
            and ranked_patch_area_jensen_shannon_divergence_bits == 0.0
        ):
            ranked_patch_area_jensen_shannon_divergence_bits = None
            warnings.append("ranked_patch_area_divergence_below_numeric_resolution")
    if patch_concentration_delta is None:
        warnings.append("patch_area_distribution_comparison_unavailable")
    else:
        warnings.append("patch_area_distribution_change_is_reconstruction_qc_not_fragmentation")
        warnings.append("ranked_patch_area_profile_distance_not_patch_correspondence")
    # A change in triangle count changes the reconstruction sampling. This
    # dimensionless ratio is a QC descriptor, not biological growth evidence.
    early_faces = before_topology["face_count"]
    late_faces = after_topology["face_count"]
    face_count_ratio = None
    if early_faces is not None and early_faces > 0 and late_faces is not None:
        try:
            candidate = late_faces / early_faces
        except OverflowError:
            warnings.append("reconstruction_face_count_ratio_out_of_numeric_range")
        else:
            if isfinite(candidate) and (candidate > 0 or late_faces == 0):
                face_count_ratio = candidate
            else:
                warnings.append("reconstruction_face_count_ratio_out_of_numeric_range")
    if face_count_ratio is None:
        warnings.append("reconstruction_face_count_ratio_unavailable")
    if early_faces is not None and late_faces is not None and early_faces != late_faces:
        warnings.append("reconstruction_face_count_changed_qc_rate_comparability_requires_review")
    # Source-frame labels are audit metadata, not registration transforms.
    frames = [first.get("coordinate_frame_id"), second.get("coordinate_frame_id")]
    for frame in frames:
        if frame is not None and (
            not isinstance(frame, str)
            or len(frame) > 128
            or fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", frame) is None
        ):
            raise ValueError("Coordinate frame IDs must be valid bounded source labels")
    if any(frame is None for frame in frames):
        warnings.append("coordinate_frame_metadata_unavailable")
    elif frames[0] != frames[1]:
        warnings.append("coordinate_frames_differ_registration_required")
    else:
        warnings.append("matching_coordinate_frame_id_not_registration_proof")
    # Compare the claimed alignment RMS with a conservative organism-size
    # reference. This is a QC diagnostic only: axis-aligned extents depend on
    # reconstruction orientation and cannot certify registration accuracy.
    registration_record = None
    registration_disputed = False
    registration_inconclusive = False
    registration_residual_to_smaller_extent_ratio = None
    registration_translation_magnitude_m = None
    registration_rotation_angle_degrees = None
    registered_surface_centroid_offset_target_frame_m = None
    registered_surface_centroid_separation_m = None
    registered_centroid_separation_to_registration_rms_ratio = None
    registered_surface_centroid_separation_caller_bound_interval_m = None
    centroid_axis_bound_intervals_m = None
    if registration_evidence is None:
        warnings.append("registration_evidence_unavailable")
    else:
        # Pydantic normally trusts an existing model instance. Revalidate its
        # current values because callers can mutate nested transform lists or
        # scalar evidence after construction, bypassing the original QC.
        evidence_values = (
            registration_evidence.model_dump(mode="python")
            if isinstance(registration_evidence, MeshRegistrationEvidence)
            else registration_evidence
        )
        try:
            registration = MeshRegistrationEvidence.model_validate(evidence_values)
        except ValueError as exc:
            # Keep controlled scientific precondition errors actionable while
            # rejecting malformed fields with the existing generic message.
            # Pydantic's validation details may include caller-supplied input.
            bounds_error = (
                "Centroid separation bounds require a transform and all three error bounds"
            )
            if isinstance(exc, ValidationError) and any(
                error["type"] == "value_error" and error["msg"] == f"Value error, {bounds_error}"
                for error in exc.errors(include_url=False)
            ):
                raise ValueError(bounds_error) from exc
            raise ValueError("Invalid pairwise registration evidence") from exc
        if (
            frames[0] is None
            or frames[1] is None
            or registration.source_frame_id != frames[0]
            or registration.target_frame_id != frames[1]
        ):
            raise ValueError("Registration evidence frame IDs must match observation source frames")
        # Local frame labels and geometry can recur across projects or
        # observation dates. Supplied bindings must match this exact pair.
        # Missing legacy bindings remain readable but explicitly provisional.
        if registration.project_id is None:
            warnings.append("registration_project_binding_unavailable")
        elif registration.project_id != project_before:
            raise ValueError("Registration evidence must match the project ID")
        if registration.source_observation_id is None:
            warnings.append("registration_observation_binding_unavailable")
        elif (
            registration.source_observation_id != first_id
            or registration.target_observation_id != second_id
        ):
            raise ValueError("Registration evidence must match both observation IDs")
        if registration.source_observed_at_utc is None:
            warnings.append("registration_timepoint_binding_unavailable")
        elif (
            registration.source_observed_at_utc != before_time
            or registration.target_observed_at_utc != after_time
        ):
            raise ValueError("Registration evidence must match both observation timestamps")
        # Frame labels can be reused for new reconstructions. Optional paired
        # fingerprints bind this evidence to the actual imported geometry.
        if registration.source_geometry_sha256 is None:
            warnings.append("registration_geometry_binding_unavailable")
        elif registration.source_geometry_sha256 != first.get(
            "geometry_sha256"
        ) or registration.target_geometry_sha256 != second.get("geometry_sha256"):
            raise ValueError("Registration evidence must match both source geometry fingerprints")
        # A geometry hash does not cover physical calibration. Reject a stale
        # meter-valued registration after either observation is recalibrated.
        # Older unbound evidence remains readable with explicit QC.
        if registration.source_meters_per_mesh_unit is None:
            warnings.append("registration_calibration_scale_binding_unavailable")
        elif registration.source_meters_per_mesh_unit != first.get(
            "meters_per_mesh_unit"
        ) or registration.target_meters_per_mesh_unit != second.get("meters_per_mesh_unit"):
            raise ValueError("Registration evidence must match both calibration scales")
        # A calibration QC revision can alter uncertainty intervals without
        # changing geometry or the central meters-per-unit conversion.
        # Old registrations without this paired binding remain provisional.
        if registration.source_relative_scale_uncertainty is None:
            warnings.append("registration_scale_uncertainty_binding_unavailable")
        elif registration.source_relative_scale_uncertainty != first.get(
            "relative_scale_uncertainty"
        ) or registration.target_relative_scale_uncertainty != second.get(
            "relative_scale_uncertainty"
        ):
            raise ValueError("Registration evidence must match both scale uncertainties")
        # An unchanged scale/uncertainty does not imply unchanged calibration
        # provenance. Keep legacy registrations readable but explicitly flagged.
        if registration.source_calibration_method is None:
            warnings.append("registration_calibration_provenance_binding_unavailable")
        elif (
            registration.source_calibration_method != first.get("calibration_method")
            or registration.target_calibration_method != second.get("calibration_method")
            or registration.source_calibration_evidence != first.get("calibration_evidence")
            or registration.target_calibration_evidence != second.get("calibration_evidence")
        ):
            raise ValueError("Registration evidence must match both calibration provenance records")
        registration_record = registration.model_dump(mode="json", exclude_none=True)
        if registration.registration_operator_id is None:
            warnings.append("registration_operator_attribution_unavailable")
        if registration.independent_reviewer_id is None:
            warnings.append("registration_evidence_requires_independent_review")
        else:
            if registration.independent_reviewed_at_utc is None:
                warnings.append("registration_independent_review_timestamp_unavailable")
            elif registration.independent_reviewed_at_utc < after_time:
                raise ValueError("Independent registration review predates the later observation")
            warnings.append("registration_independent_review_recorded_not_alignment_verification")
            if registration.independent_review_decision == "disputes_alignment":
                registration_disputed = True
                warnings.append("registration_independent_review_disputes_alignment")
            elif registration.independent_review_decision == "inconclusive":
                registration_inconclusive = True
                warnings.append("registration_independent_review_inconclusive")
        warnings.append("registration_residual_requires_independent_review")
        warnings.append("registration_transform_and_accuracy_not_verified")
        if registration.source_to_target_transform_m is None:
            warnings.append("registration_transform_unavailable")
        else:
            # Diagnostic only: summarize the caller-supplied rigid transform.
            # The transform is NOT applied to either mesh or independently verified.
            transform = registration.source_to_target_transform_m
            registration_translation_magnitude_m = hypot(*(row[3] for row in transform[:3]))
            rotation = [row[:3] for row in transform[:3]]
            # atan2 is stable near zero and 180 degrees, unlike acos(trace).
            registration_rotation_angle_degrees = degrees(
                atan2(
                    hypot(
                        rotation[2][1] - rotation[1][2],
                        rotation[0][2] - rotation[2][0],
                        rotation[1][0] - rotation[0][1],
                    ),
                    rotation[0][0] + rotation[1][1] + rotation[2][2] - 1.0,
                )
            )
            warnings.append("registration_transform_requires_independent_review")
            # Compare surface centroids only after applying the *supplied* rigid
            # source-to-target transform. This is a reconstruction-alignment
            # diagnostic, never evidence of organism motion or biological growth.
            centroids = []
            for observation in (before, after):
                centroid = observation.get("area_weighted_surface_centroid_m")
                if centroid is not None and (
                    not isinstance(centroid, list)
                    or len(centroid) != 3
                    or any(
                        type(value) not in (int, float) or not isfinite(value) for value in centroid
                    )
                ):
                    raise ValueError("Surface centroid must be three finite coordinates")
                centroids.append(centroid)
            # Disputed or inconclusive alignment cannot support even a
            # provisional transformed-centroid comparison. Preserve the matrix
            # and diagnostics for audit, but withhold derived offsets,
            # separations, uncertainty intervals, and RMS ratios.
            if registration.independent_review_decision in (
                "disputes_alignment",
                "inconclusive",
            ):
                if registration.independent_review_decision == "disputes_alignment":
                    warnings.append(
                        "registered_surface_centroid_comparison_withheld_disputed_alignment"
                    )
                else:
                    warnings.append(
                        "registered_surface_centroid_comparison_withheld_inconclusive_alignment"
                    )
            elif any(centroid is None for centroid in centroids):
                warnings.append("registered_surface_centroid_comparison_unavailable")
            else:
                source_centroid, target_centroid = centroids
                assert source_centroid is not None and target_centroid is not None
                offset = [
                    target_centroid[axis]
                    - (
                        sum(
                            transform[axis][column] * source_centroid[column] for column in range(3)
                        )
                        + transform[axis][3]
                    )
                    for axis in range(3)
                ]
                separation = hypot(*offset)
                if all(isfinite(value) for value in offset) and isfinite(separation):
                    registered_surface_centroid_offset_target_frame_m = offset
                    registered_surface_centroid_separation_m = separation
                    warnings.append("registered_centroid_offset_not_verified_biological_movement")
                    warnings.append("registered_centroid_position_uncertainty_not_estimated")
                    # The rotation preserves the Euclidean source-centroid
                    # error radius. Triangle inequality bounds the separation
                    # error by source + target + registration-alignment radii.
                    # RMS residual is NOT an error bound and is never substituted.
                    centroid_bounds = (
                        registration.source_centroid_position_error_bound_m,
                        registration.target_centroid_position_error_bound_m,
                        registration.registration_alignment_error_bound_m,
                    )
                    if all(bound is not None for bound in centroid_bounds):
                        combined_bound = sum(
                            bound for bound in centroid_bounds if bound is not None
                        )
                        upper_bound = separation + combined_bound
                        if isfinite(upper_bound):
                            registered_surface_centroid_separation_caller_bound_interval_m = [
                                max(0.0, separation - combined_bound),
                                upper_bound,
                            ]
                            # A Euclidean error radius also bounds each signed
                            # target-frame offset component, without assuming
                            # independent axes or a probability distribution.
                            centroid_axis_bound_intervals_m = [
                                [component - combined_bound, component + combined_bound]
                                for component in offset
                            ]
                            warnings.append(
                                "registered_centroid_caller_bounds_not_independently_verified"
                            )
                            warnings.append(
                                "registered_centroid_caller_interval_not_a_confidence_interval"
                            )
                        else:
                            warnings.append(
                                "registered_centroid_caller_interval_out_of_numeric_range"
                            )
                    else:
                        warnings.append("registered_centroid_error_bounds_unavailable")
                    # The ratio compares a centroid separation with a reported
                    # landmark-fit RMS. It is not a positional uncertainty,
                    # significance test, or evidence of biological movement.
                    if registration.rms_residual_m == 0:
                        warnings.append("registered_centroid_rms_ratio_unavailable_zero_residual")
                    else:
                        ratio = separation / registration.rms_residual_m
                        if isfinite(ratio) and (ratio > 0 or separation == 0):
                            registered_centroid_separation_to_registration_rms_ratio = ratio
                            warnings.append(
                                "registered_centroid_rms_ratio_not_a_movement_significance_test"
                            )
                        else:
                            warnings.append("registered_centroid_rms_ratio_out_of_numeric_range")
                else:
                    warnings.append("registered_surface_centroid_comparison_out_of_numeric_range")
        if (
            early_extent is not None
            and early_extent > 0
            and late_extent is not None
            and late_extent > 0
        ):
            ratio = registration.rms_residual_m / min(early_extent, late_extent)
            # A positive RMS residual must not underflow to a reported exact
            # zero: that would falsely imply perfect source registration.
            if isfinite(ratio) and (ratio != 0 or registration.rms_residual_m == 0):
                registration_residual_to_smaller_extent_ratio = ratio
                if ratio >= 1:
                    warnings.append("registration_residual_at_least_smaller_mesh_extent")
            else:
                warnings.append("registration_residual_extent_ratio_out_of_numeric_range")
        else:
            warnings.append("registration_residual_extent_ratio_unavailable")
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
    first_geometry_hash = first.get("geometry_sha256")
    second_geometry_hash = second.get("geometry_sha256")
    first_hash_valid = _is_sha256_fingerprint(first_geometry_hash)
    second_hash_valid = _is_sha256_fingerprint(second_geometry_hash)
    if not (first_hash_valid and second_hash_valid):
        warnings.append("geometry_fingerprint_missing_or_invalid")
    # Reusing the exact imported file across distinct timepoints is not an
    # independent observation, even if scale, notes, or reconstruction settings
    # have changed. A source digest is still caller-supplied, not authenticated.
    first_source_hash = first.get("source_payload_sha256")
    second_source_hash = second.get("source_payload_sha256")
    if (
        _is_sha256_fingerprint(first_source_hash)
        and _is_sha256_fingerprint(second_source_hash)
        and first_source_hash == second_source_hash
    ):
        warnings.append("identical_imported_source_payload_reused_across_observations")
        if first_hash_valid and second_hash_valid and first_geometry_hash != second_geometry_hash:
            warnings.append("identical_imported_source_payload_geometry_inconsistent")
    if first_hash_valid and second_hash_valid and first_geometry_hash == second_geometry_hash:
        warnings.append("identical_geometry_fingerprint")
        # A fingerprint covers the original triangles; calibration cannot alter
        # triangle counts or mesh connectivity. Conflicting topology metadata
        # indicates a provenance/serialization discrepancy, not biological change.
        if topology_changed_fields:
            warnings.append("identical_geometry_topology_metadata_inconsistent")
        if before_scale is not None and after_scale is not None:
            if before_scale != after_scale:
                warnings.append("identical_geometry_rescaled_not_biological_growth")
            # Same source geometry must retain its uncalibrated area. Compare
            # logarithms to avoid overflow when scales span many orders of magnitude.
            # This is a QC check, not a verification of biological identity.
            if (a0 == 0) != (a1 == 0) or (
                a0 > 0
                and a1 > 0
                and not isclose(
                    log(a1) - log(a0),
                    2 * (log(after_scale) - log(before_scale)),
                    rel_tol=0,
                    abs_tol=1e-8,
                )
            ):
                warnings.append("identical_geometry_area_inconsistent_with_calibration_scale")
            # An unchanged source mesh must also retain its uncalibrated
            # bounding-box diagonal. Missing extents cannot be validated.
            if (
                early_extent is not None
                and late_extent is not None
                and (
                    (early_extent == 0) != (late_extent == 0)
                    or (
                        early_extent > 0
                        and late_extent > 0
                        and not isclose(
                            log(late_extent) - log(early_extent),
                            log(after_scale) - log(before_scale),
                            rel_tol=0,
                            abs_tol=1e-8,
                        )
                    )
                )
            ):
                warnings.append("identical_geometry_extent_inconsistent_with_calibration_scale")
    if difference_bounds is None:
        warnings.append("scale_uncertainty_interval_unavailable")
    if identity_disputed:
        warnings.append("longitudinal_change_withheld_disputed_specimen_identity")
    if identity_inconclusive:
        warnings.append("longitudinal_change_withheld_inconclusive_specimen_identity")
    # A content-addressed audit fingerprint binds caller-supplied review records
    # to both observations' source bytes, geometry, calibration and identity.
    # Revisions to calibration evidence must invalidate the old review bundle,
    # even when the original geometry and observation timestamps are unchanged.
    # This is NOT an authenticated review, signature, or durable review ledger.
    review_bundle: dict[str, Any] | None = None
    review_bundle_sha256 = None
    if registration_record is not None or reidentification_record is not None:
        review_bundle = {
            "schema_version": "mesh-review-bundle-0003",
            "project_id": project_before,
            "specimen_id": specimen,
            "before_observation_id": first_id,
            "after_observation_id": second_id,
            "before_observed_at_utc": before_time.astimezone(UTC)
            .isoformat()
            .replace("+00:00", "Z"),
            "after_observed_at_utc": after_time.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "before_geometry_sha256": first.get("geometry_sha256"),
            "after_geometry_sha256": second.get("geometry_sha256"),
            "before_source_payload_sha256": first.get("source_payload_sha256"),
            "after_source_payload_sha256": second.get("source_payload_sha256"),
            # Bind the interpretation of source-byte hashes to the import format,
            # byte count and whether an expected hash was actually checked.
            # These are caller-derived audit facts, not verified authenticity.
            "before_source_format": first.get("source_format"),
            "after_source_format": second.get("source_format"),
            "before_source_payload_size_bytes": first.get("source_payload_size_bytes"),
            "after_source_payload_size_bytes": second.get("source_payload_size_bytes"),
            "before_source_payload_integrity_checked": first.get(
                "source_payload_integrity_checked"
            ),
            "after_source_payload_integrity_checked": second.get(
                "source_payload_integrity_checked"
            ),
            "before_coordinate_frame_id": frames[0],
            "after_coordinate_frame_id": frames[1],
            "before_calibration_method": first.get("calibration_method"),
            "after_calibration_method": second.get("calibration_method"),
            "before_calibration_evidence": first.get("calibration_evidence"),
            "after_calibration_evidence": second.get("calibration_evidence"),
            "before_meters_per_mesh_unit": before_scale,
            "after_meters_per_mesh_unit": after_scale,
            "before_relative_scale_uncertainty": first.get("relative_scale_uncertainty"),
            "after_relative_scale_uncertainty": second.get("relative_scale_uncertainty"),
            "before_calibration_review_evidence": first.get("calibration_review_evidence"),
            "after_calibration_review_evidence": second.get("calibration_review_evidence"),
            "registration_evidence": registration_record,
            "reidentification_evidence": reidentification_record,
        }
        review_bundle_sha256 = sha256(
            dumps(
                review_bundle,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
    result = {
        "schema_version": "mesh-longitudinal-comparison-0001",
        "specimen_id": specimen,
        "before_observation_id": first_id,
        "after_observation_id": second_id,
        "before_observed_at_utc": first["observed_at_utc"],
        "after_observed_at_utc": second["observed_at_utc"],
        "before_observed_at_utc_normalized": (
            before_time.astimezone(UTC).isoformat().replace("+00:00", "Z")
        ),
        "after_observed_at_utc_normalized": (
            after_time.astimezone(UTC).isoformat().replace("+00:00", "Z")
        ),
        "elapsed_days": elapsed_days,
        "before_meters_per_mesh_unit": before_scale,
        "after_meters_per_mesh_unit": after_scale,
        "calibration_scale_ratio_after_to_before": scale_ratio,
        "scale_normalized_surface_area_ratio_after_to_before": (scale_normalized_area_ratio),
        "scale_normalized_bounding_box_diagonal_ratio_after_to_before": (
            scale_normalized_extent_ratio
        ),
        "before_mesh_qc_warnings": observation_qc[0],
        "after_mesh_qc_warnings": observation_qc[1],
        "before_reconstruction_topology_counts": before_topology,
        "after_reconstruction_topology_counts": after_topology,
        "reconstruction_topology_changed_fields": topology_changed_fields,
        "before_reconstruction_qc_rates": reconstruction_qc_rates[0],
        "after_reconstruction_qc_rates": reconstruction_qc_rates[1],
        "reconstruction_qc_rate_changes_after_minus_before": reconstruction_qc_rate_changes,
        "before_patch_area_concentration_index": (
            before_patch_distribution[0] if before_patch_distribution is not None else None
        ),
        "after_patch_area_concentration_index": (
            after_patch_distribution[0] if after_patch_distribution is not None else None
        ),
        "delta_patch_area_concentration_index": patch_concentration_delta,
        "before_area_weighted_effective_patch_count": (
            before_patch_distribution[1] if before_patch_distribution is not None else None
        ),
        "after_area_weighted_effective_patch_count": (
            after_patch_distribution[1] if after_patch_distribution is not None else None
        ),
        "delta_area_weighted_effective_patch_count": effective_patch_count_delta,
        "ranked_patch_area_profile_distance": ranked_patch_area_profile_distance,
        "ranked_patch_area_jensen_shannon_divergence_bits": (
            ranked_patch_area_jensen_shannon_divergence_bits
        ),
        "reconstruction_face_count_ratio_after_to_before": face_count_ratio,
        "registration_residual_to_smaller_extent_ratio": (
            registration_residual_to_smaller_extent_ratio
        ),
        "registration_translation_magnitude_m": registration_translation_magnitude_m,
        "registration_rotation_angle_degrees": registration_rotation_angle_degrees,
        "registered_surface_centroid_offset_target_frame_m": (
            registered_surface_centroid_offset_target_frame_m
        ),
        "registered_surface_centroid_separation_m": registered_surface_centroid_separation_m,
        "registered_centroid_separation_to_registration_rms_ratio": (
            registered_centroid_separation_to_registration_rms_ratio
        ),
        "registered_surface_centroid_separation_caller_bound_interval_m": (
            registered_surface_centroid_separation_caller_bound_interval_m
        ),
        "registered_surface_centroid_offset_target_frame_caller_bound_intervals_m": (
            centroid_axis_bound_intervals_m
        ),
        "before_surface_area_to_bounding_diagonal_squared_ratio": before_shape_ratio,
        "after_surface_area_to_bounding_diagonal_squared_ratio": after_shape_ratio,
        "delta_surface_area_to_bounding_diagonal_squared_ratio": shape_ratio_delta,
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
            "before_coordinate_frame_id": frames[0],
            "after_coordinate_frame_id": frames[1],
            "registration_evidence": registration_record,
            "reidentification_evidence": reidentification_record,
            "review_evidence_bundle_schema_version": (
                "mesh-review-bundle-0003" if review_bundle_sha256 is not None else None
            ),
            "review_evidence_bundle_sha256": review_bundle_sha256,
            "review_evidence_bundle": review_bundle,
            "reidentification_evidence_review_status": (
                "caller_supplied_unverified"
                if reidentification_record is not None
                else "unavailable"
            ),
            "registration_evidence_review_status": (
                "caller_supplied_unverified" if registration_record is not None else "unavailable"
            ),
            "before_calibration_evidence": first.get("calibration_evidence"),
            "after_calibration_evidence": second.get("calibration_evidence"),
            "specimen_identity_verified": False,
            "coordinate_registration_verified": False,
            "registered_centroid_comparison_withheld_due_to_registration_dispute": (
                registration_disputed
            ),
            "registered_centroid_comparison_withheld_due_to_inconclusive_registration_review": (
                registration_inconclusive
            ),
            "observation_metadata_verified": False,
            "calibration_verified": False,
            "scale_uncertainty_only": (
                difference_bounds is not None
                and not identity_disputed
                and not identity_inconclusive
            ),
            "longitudinal_change_withheld_due_to_identity_dispute": identity_disputed,
            "longitudinal_change_withheld_due_to_inconclusive_identity_review": (
                identity_inconclusive
            ),
        },
    }
    if identity_disputed or identity_inconclusive:
        # Keep each original observation and reconstruction QC intact. A
        # disputed or inconclusive match cannot support cross-timepoint organism
        # change estimates, even if the numerical geometry is well formed.
        for key in (
            "delta_surface_area_to_bounding_diagonal_squared_ratio",
            "delta_patch_area_concentration_index",
            "delta_area_weighted_effective_patch_count",
            "ranked_patch_area_profile_distance",
            "ranked_patch_area_jensen_shannon_divergence_bits",
            "scale_normalized_surface_area_ratio_after_to_before",
            "scale_normalized_bounding_box_diagonal_ratio_after_to_before",
            "registered_surface_centroid_offset_target_frame_m",
            "registered_surface_centroid_separation_m",
            "registered_centroid_separation_to_registration_rms_ratio",
            "registered_surface_centroid_separation_caller_bound_interval_m",
            "registered_surface_centroid_offset_target_frame_caller_bound_intervals_m",
            "delta_surface_area_m2",
            "delta_axis_aligned_bounding_box_diagonal_m",
            "relative_axis_aligned_bounding_box_diagonal_change_percent",
            "relative_axis_aligned_bounding_box_diagonal_scale_interval_percent",
            "delta_axis_aligned_bounding_box_diagonal_scale_interval_m",
            "average_axis_aligned_bounding_box_diagonal_change_m_per_day",
            "average_axis_aligned_bounding_box_diagonal_change_scale_interval_m_per_day",
            "average_surface_area_change_m2_per_day",
            "average_surface_area_change_scale_interval_m2_per_day",
            "delta_surface_area_scale_interval_m2",
            "relative_surface_area_change_percent",
            "relative_surface_area_scale_interval_percent",
        ):
            result[key] = None
    return result
