"""Tiny but representable calibrated coral volume must survive cubic scaling."""

from __future__ import annotations

from fractions import Fraction
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_mesh_surface_v14 import measure_mesh_preview
from reefvision.tests.test_annotations import create_project

LARGE_TETRA_VERTICES = [
    [0.0, 0.0, 0.0],
    [1e8, 0.0, 0.0],
    [0.0, 1e8, 0.0],
    [0.0, 0.0, 1e8],
]
CLOSED_FACES = [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]]


def _params(scale: float) -> dict:
    return {
        "vertices": LARGE_TETRA_VERTICES,
        "faces": CLOSED_FACES,
        "meters_per_unit": scale,
        "calibration_method": "ruler",
        "calibration_evidence": "Synthetic scale; not independently verified",
        "relative_scale_uncertainty": 0.1,
    }


def test_representable_tiny_volume_preserves_exact_cubic_scale_bounds() -> None:
    scale = 1e-110
    assert scale**3 == 0.0  # Regression: applying this intermediate drops all volume.
    result = measure_mesh_preview(**_params(scale))
    expected = (1e24 / 6) * scale * scale * scale
    assert expected > 0
    assert result["surface_area_m2"] > 0
    assert result["enclosed_volume_m3"] == pytest.approx(expected, rel=1e-12, abs=0)
    assert result["edge_connected_patch_enclosed_volumes_m3"] == pytest.approx(
        [expected], rel=1e-12, abs=0
    )
    assert result["enclosed_volume_scale_interval_m3"] == pytest.approx(
        [expected * 0.9**3, expected * 1.1**3], rel=1e-12, abs=0
    )
    patch_interval = result["edge_connected_patch_enclosed_volume_scale_intervals_m3"][0]
    assert patch_interval == pytest.approx([expected * 0.9**3, expected * 1.1**3], rel=1e-12, abs=0)
    assert result["surface_to_enclosed_volume_ratio_per_m"] is not None
    assert "enclosed_volume_zero_or_underflow" not in result["qc_warnings"]
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False


@pytest.mark.parametrize(
    ("uncertainty", "bounds_available", "omit_uncertainty"),
    [
        (None, None, False),
        (None, None, True),
        (0.0, True, False),
        (0.1, True, False),
        (0.8, False, False),
        (1.0, True, False),
    ],
    ids=[
        "explicit-null-scale-uncertainty-withholds-bounds",
        "omitted-scale-uncertainty-withholds-bounds",
        "zero-scale-uncertainty-retains-nominal-bounds",
        "ten-percent-scale-uncertainty-retains-positive-bounds",
        "positive-bound-underflow",
        "legitimate-zero-bound-at-100-percent",
    ],
)
def test_subnormal_volume_interval_qc_replays_in_saved_typed_workflow(
    client: TestClient,
    uncertainty: float | None,
    bounds_available: bool | None,
    omit_uncertainty: bool,
) -> None:
    """A rounded zero lower limit must not masquerade as scale evidence."""
    params = {
        **_params(1e-115),
        "relative_scale_uncertainty": uncertainty,
        "specimen_id": "synthetic-unverified-small-volume",
        "observation_id": "subnormal-volume-interval-review",
        "coordinate_frame_id": "unregistered-import-frame",
    }
    direct_params = {**_params(1e-115), "relative_scale_uncertainty": uncertainty}
    if omit_uncertainty:
        # The API default and explicit JSON null must both mean unknown scale error.
        params.pop("relative_scale_uncertainty")
        direct_params.pop("relative_scale_uncertainty")
    direct = measure_mesh_preview(**direct_params)
    project_id = str(create_project(client, "Subnormal provisional volume interval")["id"])
    base = f"/api/v1/projects/{project_id}"
    response = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert response.status_code == 200, response.text
    standalone = response.json()
    nominal = standalone["enclosed_volume_m3"]
    assert nominal is not None and 0 < nominal < 1e-320
    assert standalone["edge_connected_patch_enclosed_volumes_m3"] == [nominal]
    assert direct["enclosed_volume_m3"] == nominal
    warning = "enclosed_volume_scale_interval_numeric_unrepresentable"
    if uncertainty is None:
        # Missing uncertainty is not equivalent to a verified zero-error scale.
        assert bounds_available is None
        assert standalone["enclosed_volume_scale_interval_m3"] is None
        assert standalone["edge_connected_patch_enclosed_volume_scale_intervals_m3"] is None
        assert standalone["surface_area_scale_interval_m2"] is None
        assert standalone["edge_connected_patch_area_scale_intervals_m2"] is None
        assert standalone["axis_aligned_dimension_scale_intervals_m"] is None
        assert standalone["provenance"]["relative_scale_uncertainty"] is None
        assert warning not in standalone["qc_warnings"]
    elif bounds_available:
        expected = [nominal * (1 - uncertainty) ** 3, nominal * (1 + uncertainty) ** 3]
        # Zero must mean a genuine 100% lower scale bound, never rounding loss.
        assert (expected[0] == 0.0) is (uncertainty == 1.0)
        assert standalone["enclosed_volume_scale_interval_m3"] == expected
        assert standalone["edge_connected_patch_enclosed_volume_scale_intervals_m3"] == [expected]
        assert warning not in standalone["qc_warnings"]
    else:
        # The true lower bound is strictly positive for uncertainty below 100%.
        assert nominal * (1 - uncertainty) ** 3 == 0.0
        assert standalone["enclosed_volume_scale_interval_m3"] is None
        assert standalone["edge_connected_patch_enclosed_volume_scale_intervals_m3"] == [None]
        assert warning in standalone["qc_warnings"]
    assert (
        direct["enclosed_volume_scale_interval_m3"]
        == (standalone["enclosed_volume_scale_interval_m3"])
    )
    assert (
        direct["edge_connected_patch_enclosed_volume_scale_intervals_m3"]
        == (standalone["edge_connected_patch_enclosed_volume_scale_intervals_m3"])
    )
    assert standalone["measurement_status"] == "caller_supplied_unverified"
    assert standalone["provenance"]["calibration_verified"] is False
    assert standalone["provenance"]["specimen_identity_verified"] is False
    assert standalone["provenance"]["coordinate_registration_verified"] is False

    graph = {
        "graph_id": "subnormal-volume-interval-qc-v14",
        "name": "Review provisional cubic-scale numeric bounds",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "mesh", "node_type": "mesh_surface_preview", "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "project-mesh",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "mesh",
                "target_port_id": "project",
            }
        ],
    }
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    app = cast(FastAPI, client.app)
    hashes: list[str] = []
    for _ in range(2):
        run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
        assert run.status_code == 202, run.text
        assert process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run.json()["job_id"])
        )
        detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["run"]["status"] == "succeeded"
        artifacts = [
            item
            for item in detail.json()["artifacts"]
            if item["data_type"] == "mesh_measurement_preview"
        ]
        assert len(artifacts) == 1
        assert artifacts[0]["payload_json"] == standalone
        hashes.append(artifacts[0]["payload_sha256"])
    assert len(hashes[0]) == 64
    assert hashes[0] == hashes[1]


def test_genuinely_unrepresentable_cubic_volume_remains_withheld() -> None:
    # Surface area and dimensions still survive; the physical volume does not.
    result = measure_mesh_preview(**_params(1e-150))
    assert result["surface_area_m2"] > 0
    assert all(dimension > 0 for dimension in result["axis_aligned_dimensions_m"])
    assert result["enclosed_volume_m3"] is None
    assert result["edge_connected_patch_enclosed_volumes_m3"] == [None]
    assert result["enclosed_volume_scale_interval_m3"] is None
    assert "enclosed_volume_zero_or_underflow" in result["qc_warnings"]


@pytest.mark.parametrize(
    ("coordinate_extent", "scale"),
    [(1e8, 1e-110), (1e-110, 1e6)],
    ids=["large-source-tiny-calibration", "tiny-source-large-calibration"],
)
@pytest.mark.parametrize("reverse_winding", [False, True], ids=["forward", "reversed"])
def test_tiny_volume_standalone_and_replayed_saved_graph_preserve_provenance(
    client: TestClient, coordinate_extent: float, scale: float, reverse_winding: bool
) -> None:
    project_id = str(create_project(client, "Small provisional enclosed volume")["id"])
    base = f"/api/v1/projects/{project_id}"
    params = {
        **_params(scale),
        "vertices": [
            [0.0, 0.0, 0.0],
            [coordinate_extent, 0.0, 0.0],
            [0.0, coordinate_extent, 0.0],
            [0.0, 0.0, coordinate_extent],
        ],
        "specimen_id": "synthetic-unverified-coral",
        "observation_id": "tiny-volume-survey-1",
        "coordinate_frame_id": "imported-unregistered",
        "faces": [[a, c, b] for a, b, c in CLOSED_FACES] if reverse_winding else CLOSED_FACES,
    }
    standalone_response = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone_response.status_code == 200, standalone_response.text
    standalone = standalone_response.json()
    expected_volume = (coordinate_extent * scale) ** 3 / 6
    assert expected_volume > 0
    assert standalone["enclosed_volume_m3"] == pytest.approx(expected_volume, rel=1e-8, abs=0)
    patch_volumes = standalone["edge_connected_patch_enclosed_volumes_m3"]
    assert patch_volumes == pytest.approx([expected_volume], rel=1e-8, abs=0)
    scale_bounds = [expected_volume * 0.9**3, expected_volume * 1.1**3]
    assert standalone["enclosed_volume_scale_interval_m3"] == pytest.approx(
        scale_bounds, rel=1e-8, abs=0
    )
    patch_bounds = standalone["edge_connected_patch_enclosed_volume_scale_intervals_m3"]
    assert patch_bounds is not None
    assert patch_bounds[0] == pytest.approx(scale_bounds, rel=1e-8, abs=0)
    assert standalone["surface_area_m2"] > 0
    assert standalone["measurement_status"] == "caller_supplied_unverified"
    assert "enclosed_volume_zero_or_underflow" not in standalone["qc_warnings"]
    assert ("enclosed_volume_source_unit_numeric_recovery" in standalone["qc_warnings"]) is (
        coordinate_extent < 1
    )
    if coordinate_extent < 1:
        exact_calibrated = float((Fraction(coordinate_extent) * Fraction(scale)) ** 3 / 6)
        assert standalone["enclosed_volume_m3"] == exact_calibrated
    assert standalone["provenance"]["calibration_verified"] is False
    assert standalone["provenance"]["specimen_identity_verified"] is False
    assert standalone["provenance"]["coordinate_registration_verified"] is False

    graph = {
        "graph_id": "tiny-calibrated-volume-v14",
        "name": "Preserve representable provisional cubic volumes",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "mesh", "node_type": "mesh_surface_preview", "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "project-mesh",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "mesh",
                "target_port_id": "project",
            }
        ],
    }
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text

    app = cast(FastAPI, client.app)
    hashes: list[str] = []
    for _ in range(2):
        run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
        assert run.status_code == 202, run.text
        assert process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run.json()["job_id"])
        )
        detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["run"]["status"] == "succeeded"
        artifacts = [
            item
            for item in detail.json()["artifacts"]
            if item["data_type"] == "mesh_measurement_preview"
        ]
        assert len(artifacts) == 1
        assert artifacts[0]["payload_json"] == standalone
        hashes.append(artifacts[0]["payload_sha256"])
    assert len(hashes[0]) == 64
    assert hashes[0] == hashes[1]


@pytest.mark.parametrize("reverse_winding", [False, True], ids=["forward", "reversed"])
def test_source_unit_underflow_recovers_volume_with_review_flag(
    reverse_winding: bool,
) -> None:
    """Calibrating before binary64 rounding preserves provisional status."""
    extent = 1e-110
    vertices = [
        [0.0, 0.0, 0.0],
        [extent, 0.0, 0.0],
        [0.0, extent, 0.0],
        [0.0, 0.0, extent],
    ]
    faces = [[a, c, b] for a, b, c in CLOSED_FACES] if reverse_winding else CLOSED_FACES
    params = {**_params(1e6), "vertices": vertices, "faces": faces}
    result = measure_mesh_preview(**params)
    expected = float((Fraction(extent) * Fraction(1e6)) ** 3 / 6)
    assert expected > 0
    assert result["enclosed_volume_m3"] == expected
    assert result["edge_connected_patch_enclosed_volumes_m3"] == [expected]
    assert result["enclosed_volume_scale_interval_m3"] == pytest.approx(
        [expected * 0.9**3, expected * 1.1**3], rel=1e-8, abs=0
    )
    assert "enclosed_volume_source_unit_numeric_recovery" in result["qc_warnings"]
    assert "enclosed_volume_zero_or_underflow" not in result["qc_warnings"]
    assert result["measurement_status"] == "caller_supplied_unverified"
    assert result["provenance"]["calibration_verified"] is False


def test_unrepresentable_volume_after_large_scale_is_rejected() -> None:
    """Positive area can remain measurable even when the enclosure cannot."""
    extent = 1e-120
    vertices = [
        [0.0, 0.0, 0.0],
        [extent, 0.0, 0.0],
        [0.0, extent, 0.0],
        [0.0, 0.0, extent],
    ]
    control = measure_mesh_preview(
        **(_params(1e6) | {"vertices": vertices, "faces": CLOSED_FACES[:-1]})
    )
    assert control["surface_area_m2"] > 0
    assert control["enclosed_volume_m3"] is None
    with pytest.raises(ValueError, match="volume underflowed numeric precision after calibration"):
        measure_mesh_preview(**(_params(1e6) | {"vertices": vertices}))


def test_cubic_volume_subresolution_scale_qc_standalone_and_saved_graph(
    client: TestClient,
) -> None:
    """Positive volume with rounded-equal bounds must not appear exact."""
    mesh_params = {**_params(1e-8), "relative_scale_uncertainty": 1e-17}
    params = {
        **mesh_params,
        "specimen_id": "synthetic-unverified-cubic-precision",
        "observation_id": "tiny-relative-uncertainty",
        "coordinate_frame_id": "source-frame-not-registered",
    }
    direct = measure_mesh_preview(**mesh_params)
    nominal = direct["enclosed_volume_m3"]
    assert nominal == pytest.approx(1 / 6)
    assert nominal > 0
    assert (1 - 1e-17) ** 3 == (1 + 1e-17) ** 3
    assert direct["enclosed_volume_scale_interval_m3"] is None
    assert direct["edge_connected_patch_enclosed_volume_scale_intervals_m3"] == [None]
    ratio = direct["surface_to_enclosed_volume_ratio_per_m"]
    assert ratio is not None and ratio > 0
    assert direct["surface_to_enclosed_volume_ratio_scale_interval_per_m"] is None
    assert direct[
        "edge_connected_patch_surface_to_enclosed_volume_ratio_scale_intervals_per_m"
    ] == [None]
    ratio_warning = "surface_volume_ratio_scale_interval_numeric_unrepresentable"
    assert ratio_warning in direct["qc_warnings"]
    warning = "enclosed_volume_scale_interval_numeric_unrepresentable"
    assert warning in direct["qc_warnings"]
    assert direct["measurement_status"] == "caller_supplied_unverified"
    assert direct["provenance"]["calibration_verified"] is False

    # Direct engine provenance lacks request-level specimen/coordinate fields;
    # those are added by preview_from_request in API and saved workflows.
    # An explicit zero error, an unknown error, and a physically valid 100%
    # lower bound must remain distinct from rounded-away positive error.
    exact = measure_mesh_preview(**{**mesh_params, "relative_scale_uncertainty": 0.0})
    assert exact["enclosed_volume_scale_interval_m3"] == [nominal, nominal]
    assert exact["surface_to_enclosed_volume_ratio_scale_interval_per_m"] == [ratio, ratio]
    assert warning not in exact["qc_warnings"]
    assert ratio_warning not in exact["qc_warnings"]
    ordinary = measure_mesh_preview(**{**mesh_params, "relative_scale_uncertainty": 0.1})
    assert ordinary["surface_to_enclosed_volume_ratio_scale_interval_per_m"] == pytest.approx(
        [ratio / 1.1, ratio / 0.9]
    )
    assert ratio_warning not in ordinary["qc_warnings"]
    unknown = measure_mesh_preview(**{**mesh_params, "relative_scale_uncertainty": None})
    assert unknown["enclosed_volume_scale_interval_m3"] is None
    assert unknown["edge_connected_patch_enclosed_volume_scale_intervals_m3"] is None
    assert unknown["surface_to_enclosed_volume_ratio_scale_interval_per_m"] is None
    assert (
        unknown["edge_connected_patch_surface_to_enclosed_volume_ratio_scale_intervals_per_m"]
        is None
    )
    assert warning not in unknown["qc_warnings"]
    assert ratio_warning not in unknown["qc_warnings"]
    full = measure_mesh_preview(**{**mesh_params, "relative_scale_uncertainty": 1.0})
    assert full["enclosed_volume_scale_interval_m3"] == [0.0, nominal * 8]
    assert full["surface_to_enclosed_volume_ratio_scale_interval_per_m"] is None
    assert warning not in full["qc_warnings"]
    assert ratio_warning not in full["qc_warnings"]

    project_id = str(create_project(client, "Provisional cubic precision review")["id"])
    base = f"/api/v1/projects/{project_id}"
    response = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert response.status_code == 200, response.text
    standalone = response.json()
    assert standalone["enclosed_volume_m3"] == nominal
    assert standalone["enclosed_volume_scale_interval_m3"] is None
    assert standalone["edge_connected_patch_enclosed_volume_scale_intervals_m3"] == [None]
    assert standalone["surface_to_enclosed_volume_ratio_per_m"] == ratio
    assert standalone["surface_to_enclosed_volume_ratio_scale_interval_per_m"] is None
    assert standalone[
        "edge_connected_patch_surface_to_enclosed_volume_ratio_scale_intervals_per_m"
    ] == [None]
    assert standalone["qc_warnings"] == direct["qc_warnings"]
    assert standalone["provenance"]["calibration_verified"] is False
    assert standalone["provenance"]["specimen_identity_verified"] is False
    assert standalone["provenance"]["coordinate_registration_verified"] is False
    # Human-provided specimen identifiers must remain audit metadata, not evidence
    # of biological re-identification. Changing a label cannot change geometry.
    for field in ("specimen_id", "observation_id", "coordinate_frame_id"):
        assert standalone["provenance"][field] == params[field]
    assert standalone["provenance"]["relative_scale_uncertainty"] == 1e-17
    assert standalone["provenance"]["calibration_evidence"] == mesh_params["calibration_evidence"]
    # Caller-supplied identity, observation, and coordinate-frame labels are
    # audit annotations, not registration or organism correspondence evidence.
    # Alter each label separately to catch accidental coupling to geometry.
    for field, alternate_label in (
        ("specimen_id", "synthetic-unverified-other-specimen"),
        ("observation_id", "another-unverified-survey"),
        ("coordinate_frame_id", "another-unregistered-source-frame"),
    ):
        alternate_response = client.post(
            f"{base}/spatial/mesh-preview",
            json={**params, field: alternate_label},
        )
        assert alternate_response.status_code == 200, alternate_response.text
        alternate = alternate_response.json()
        assert alternate["provenance"][field] == alternate_label
        for unchanged_field in (
            "specimen_id",
            "observation_id",
            "coordinate_frame_id",
        ):
            if unchanged_field != field:
                assert alternate["provenance"][unchanged_field] == params[unchanged_field]
        for verified_flag in (
            "calibration_verified",
            "specimen_identity_verified",
            "coordinate_registration_verified",
        ):
            assert alternate["provenance"][verified_flag] is False
        alternate_digest = alternate["provenance"]["geometry_sha256"]
        assert alternate_digest == standalone["provenance"]["geometry_sha256"]
        for geometry_field in (
            "surface_area_m2",
            "enclosed_volume_m3",
            "surface_to_enclosed_volume_ratio_per_m",
            "enclosed_volume_scale_interval_m3",
            "surface_to_enclosed_volume_ratio_scale_interval_per_m",
            "edge_connected_patch_enclosed_volumes_m3",
        ):
            assert alternate[geometry_field] == standalone[geometry_field]
        assert alternate["qc_warnings"] == standalone["qc_warnings"]

    graph = {
        "graph_id": "subresolution-cubic-scale-v14",
        "name": "Review numerically unresolved cubic uncertainty",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "mesh", "node_type": "mesh_surface_preview", "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "project-mesh",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "mesh",
                "target_port_id": "project",
            }
        ],
    }
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    app = cast(FastAPI, client.app)
    hashes: list[str] = []
    for _ in range(2):
        run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
        assert run.status_code == 202, run.text
        assert process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run.json()["job_id"])
        )
        detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["run"]["status"] == "succeeded"
        artifacts = [
            item
            for item in detail.json()["artifacts"]
            if item["data_type"] == "mesh_measurement_preview"
        ]
        assert len(artifacts) == 1
        assert artifacts[0]["payload_json"] == standalone
        hashes.append(artifacts[0]["payload_sha256"])
    assert len(hashes[0]) == 64
    assert hashes[0] == hashes[1]
