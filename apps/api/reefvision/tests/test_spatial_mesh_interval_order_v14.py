"""Every timepoint's scale evidence must be checked even if its peer lacks bounds."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from reefvision.domain.errors import ValidationError
from reefvision.services.spatial_mesh_longitudinal_v14 import compare_mesh_observations
from reefvision.services.workflow_mesh_v14 import execute_mesh_longitudinal_comparison
from reefvision.tests.test_spatial_mesh_longitudinal_v14 import _minimal_topology_pair


@pytest.mark.parametrize(
    ("field", "nominal_field", "error"),
    [
        (
            "surface_area_scale_interval_m2",
            "surface_area_m2",
            "Surface-area scale interval contradicts source uncertainty",
        ),
        (
            "axis_aligned_bounding_box_diagonal_scale_interval_m",
            "axis_aligned_bounding_box_diagonal_m",
            "Bounding-box scale interval contradicts source uncertainty",
        ),
    ],
)
def test_later_forged_scale_bounds_rejected_when_earlier_bounds_missing(
    field: str, nominal_field: str, error: str
) -> None:
    before, after = _minimal_topology_pair()
    for record in (before, after):
        record["provenance"]["relative_scale_uncertainty"] = 0.1
        record["axis_aligned_bounding_box_diagonal_m"] = 2.0
    # The first observation has unknown bounds; the second cannot use that
    # absence to bypass independent validation of its own fabricated interval.
    before[field] = None
    after[field] = [after[nominal_field], after[nominal_field]]
    with pytest.raises(ValueError, match=error):
        compare_mesh_observations(before, after)

    # The executable typed Workflow Builder adapter must reject exactly the
    # same scientific evidence, not emit an apparently usable comparison.
    artifacts = {
        port: [
            SimpleNamespace(
                data_type="mesh_measurement_preview", payload_json=record
            )
        ]
        for port, record in (("before", before), ("after", after))
    }
    with pytest.raises(ValidationError, match=error):
        execute_mesh_longitudinal_comparison(
            None, None, "project-1", {}, artifacts
        )


def test_missing_early_bounds_still_withhold_combined_intervals() -> None:
    before, after = _minimal_topology_pair()
    for record in (before, after):
        record["provenance"]["relative_scale_uncertainty"] = 0.1
        record["axis_aligned_bounding_box_diagonal_m"] = 2.0
    after["surface_area_scale_interval_m2"] = [0.81, 1.21]
    after["axis_aligned_bounding_box_diagonal_scale_interval_m"] = [1.8, 2.2]
    result = compare_mesh_observations(before, after)
    assert result["delta_surface_area_scale_interval_m2"] is None
    assert result["delta_axis_aligned_bounding_box_diagonal_scale_interval_m"] is None
    assert result["measurement_status"] == "provisional_unverified_longitudinal_comparison"
