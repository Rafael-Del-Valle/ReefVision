from __future__ import annotations

import numpy as np
import pytest

from reefvision.jobs.depth import _generated_depth_source_kind
from reefvision.schemas.depth import CameraIntrinsics, DepthMapImportRequest
from reefvision.services.depth_maps import _visible_surface_area


def test_flat_metric_depth_surface_matches_pixel_footprint() -> None:
    values = np.ones((2, 2), dtype=np.float32)
    valid = np.ones((2, 2), dtype=bool)
    intrinsics = CameraIntrinsics(fx_px=1, fy_px=1, cx_px=0, cy_px=0)

    area, patch_count = _visible_surface_area(values, valid, intrinsics)

    assert area == pytest.approx(4.0)
    assert patch_count == 4


def test_metric_import_requires_positive_physical_depth() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        DepthMapImportRequest(
            values=[[1.0, 0.0]],
            depth_kind="metric",
            source_kind="rgbd_metric",
            unit="m",
        )


def test_depth_import_source_kind_must_match_depth_kind() -> None:
    with pytest.raises(ValueError, match="metric depth source kind"):
        DepthMapImportRequest(
            values=[[1.0]],
            depth_kind="metric",
            source_kind="relative_monocular",
            unit="m",
        )

    with pytest.raises(ValueError, match="relative depth source kind"):
        DepthMapImportRequest(
            values=[[0.2]],
            depth_kind="relative",
            source_kind="stereo_metric",
        )


def test_depth_import_defaults_preserve_relative_vs_metric_semantics() -> None:
    relative = DepthMapImportRequest(values=[[0.2]], depth_kind="relative", unit="cm")
    metric = DepthMapImportRequest(values=[[2.0]], depth_kind="metric")

    assert relative.source_kind == "relative_imported"
    assert relative.unit is None
    assert metric.source_kind == "imported_metric"
    assert metric.unit == "m"


def test_generated_depth_sources_are_not_user_relabelled() -> None:
    assert _generated_depth_source_kind("luminance_relative", "relative") == "relative_fixture"
    assert (
        _generated_depth_source_kind("depth_anything_v2_relative", "relative")
        == "relative_monocular"
    )
    assert (
        _generated_depth_source_kind("depth_anything_v2_metric", "metric")
        == "metric_monocular_estimate"
    )
