"""Direct mesh service must not coerce triangle vertex indices."""

from __future__ import annotations

from typing import cast

import pytest

from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview


@pytest.mark.parametrize("invalid_index", [True, 1.0, "1", None])
def test_direct_mesh_service_rejects_noninteger_face_indices(invalid_index: object) -> None:
    with pytest.raises(ValueError, match="three distinct existing vertices"):
        measure_mesh_preview(
            vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]],
            faces=[[0, cast(int, invalid_index), 2]],
            meters_per_unit=0.01,
            calibration_method="ruler",
            calibration_evidence="Unverified ruler",
        )


def test_direct_mesh_service_accepts_integer_face_indices() -> None:
    result = measure_mesh_preview(
        vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]],
        faces=[[0, 1, 2]],
        meters_per_unit=0.01,
        calibration_method="ruler",
        calibration_evidence="Unverified ruler",
    )
    assert result["face_count"] == 1
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False
