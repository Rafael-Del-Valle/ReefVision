"""Scale-invariant patch concentration: longitudinal QC and saved-graph parity."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.spatial_mesh_preview_v14 import MeshPreviewRequest
from reefvision.services.spatial_mesh_longitudinal_v14 import compare_mesh_observations
from reefvision.services.spatial_mesh_surface_v14 import preview_from_request
from reefvision.tests.test_annotations import create_project


def _meshes() -> tuple[dict, dict]:
    common = {
        "faces": [[0, 1, 2], [3, 4, 5]],
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified survey ruler",
        "relative_scale_uncertainty": 0.1,
        "specimen_id": "colony:16",
    }
    before = {
        **common,
        "vertices": [
            [0, 0, 0],
            [1, 0, 0],
            [0, 2, 0],
            [10, 0, 0],
            [13, 0, 0],
            [10, 2, 0],
        ],
        "meters_per_unit": 0.1,
        "observation_id": "survey-1",
        "observed_at_utc": "2026-10-01T12:00:00Z",
    }
    after = {
        **common,
        "vertices": [
            [0, 0, 0],
            [2, 0, 0],
            [0, 2, 0],
            [10, 0, 0],
            [12, 0, 0],
            [10, 2, 0],
        ],
        "meters_per_unit": 2.0,
        "observation_id": "survey-2",
        "observed_at_utc": "2026-10-02T12:00:00Z",
    }
    return before, after


def _preview(payload: dict) -> dict:
    result = preview_from_request(MeshPreviewRequest.model_validate(payload))
    result["project_id"] = "project-1"
    return result


def test_patch_concentration_is_permutation_invariant_scale_free_qc() -> None:
    before, after = (_preview(payload) for payload in _meshes())
    result = compare_mesh_observations(before, after)
    assert result["before_patch_area_concentration_index"] == pytest.approx(0.625)
    assert result["after_patch_area_concentration_index"] == pytest.approx(0.5)
    assert result["delta_patch_area_concentration_index"] == pytest.approx(-0.125)
    assert result["before_area_weighted_effective_patch_count"] == pytest.approx(1.6)
    assert result["after_area_weighted_effective_patch_count"] == pytest.approx(2)
    assert result["delta_area_weighted_effective_patch_count"] == pytest.approx(0.4)
    assert result["ranked_patch_area_profile_distance"] == pytest.approx(0.25)
    assert result["ranked_patch_area_jensen_shannon_divergence_bits"] == pytest.approx(
        0.0487949406953985
    )
    warning = "ranked_patch_area_profile_distance_not_patch_correspondence"
    assert warning in result["qc_warnings"]
    assert (
        "patch_area_distribution_change_is_reconstruction_qc_not_fragmentation"
        in result["qc_warnings"]
    )
    assert result["provenance"]["specimen_identity_verified"] is False
    assert result["measurement_status"] == "provisional_unverified_longitudinal_comparison"


def test_ranked_profile_is_independent_of_patch_index_order() -> None:
    early, late = _meshes()
    before, after = _preview(early), _preview(late)
    baseline = compare_mesh_observations(before, after)
    # Permute source vertex indices to reverse the patch order without
    # tampering with saved artifact metadata or changing the actual geometry.
    early["vertices"] = early["vertices"][3:] + early["vertices"][:3]
    reordered_before = _preview(early)
    assert reordered_before["edge_connected_patch_surface_area_fractions"] == pytest.approx(
        list(reversed(before["edge_connected_patch_surface_area_fractions"]))
    )
    reordered = compare_mesh_observations(reordered_before, after)
    assert reordered["ranked_patch_area_profile_distance"] == pytest.approx(0.25)
    assert (
        reordered["ranked_patch_area_profile_distance"]
        == baseline["ranked_patch_area_profile_distance"]
    )
    assert reordered["ranked_patch_area_jensen_shannon_divergence_bits"] == pytest.approx(
        baseline["ranked_patch_area_jensen_shannon_divergence_bits"]
    )


def test_ranked_profile_pads_missing_patch_ranks_with_zero() -> None:
    early, late = _meshes()
    late["faces"] = [[0, 1, 2]]
    late["vertices"] = late["vertices"][:3]
    before, after = _preview(early), _preview(late)
    result = compare_mesh_observations(before, after)
    assert before["edge_connected_patch_count"] == 2
    assert after["edge_connected_patch_count"] == 1
    assert result["ranked_patch_area_profile_distance"] == pytest.approx(0.25)
    assert result["ranked_patch_area_jensen_shannon_divergence_bits"] == pytest.approx(
        0.1379253809700299
    )
    warning = "ranked_patch_area_profile_distance_not_patch_correspondence"
    assert warning in result["qc_warnings"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("edge_connected_patch_surface_area_fractions", [0.25, 0.25]),
        ("edge_connected_patch_surface_area_fractions", [0.5, float("nan")]),
        ("edge_connected_patch_surface_area_fractions", [True, 0.75]),
        ("edge_connected_patch_surface_area_fractions", [1.0]),
        ("edge_connected_patch_area_concentration_index", 0.9),
        ("area_weighted_effective_patch_count", 3.0),
    ],
)
def test_patch_concentration_rejects_contradictory_source_metadata(
    field: str, value: object
) -> None:
    before, after = (_preview(payload) for payload in _meshes())
    before[field] = value
    with pytest.raises(ValueError, match=r"[Pp]atch"):
        compare_mesh_observations(before, after)


@pytest.mark.parametrize(
    "invalid_count",
    [True, 2.0, 0, -1, "2", float("nan"), 3],
)
@pytest.mark.parametrize("timepoint", [0, 1])
def test_patch_count_rejects_forged_topology_metadata(
    invalid_count: object, timepoint: int
) -> None:
    observations = [_preview(payload) for payload in _meshes()]
    observations[timepoint]["edge_connected_patch_count"] = invalid_count
    with pytest.raises(ValueError, match=r"Patch (count|area fractions)"):
        compare_mesh_observations(*observations)


@pytest.mark.parametrize("timepoint", [0, 1])
def test_patch_area_evidence_without_fractions_is_rejected(timepoint: int) -> None:
    observations = [_preview(payload) for payload in _meshes()]
    record = observations[timepoint]
    for field in (
        "edge_connected_patch_surface_area_fractions",
        "edge_connected_patch_area_concentration_index",
        "area_weighted_effective_patch_count",
    ):
        record.pop(field)
    # A modern artifact with per-patch areas cannot claim to be a legacy
    # artifact lacking the distribution needed to audit those areas.
    with pytest.raises(ValueError, match="Patch concentration requires source area fractions"):
        compare_mesh_observations(*observations)


@pytest.mark.parametrize(
    "corruption",
    [
        lambda areas: areas[:1],
        lambda areas: [float("nan"), areas[1]],
        lambda areas: [True, areas[1]],
        lambda areas: [-1.0, areas[1]],
        lambda areas: [areas[0] / 2, areas[1] + areas[0] / 2],
        lambda areas: [area * 2 for area in areas],
    ],
)
@pytest.mark.parametrize("timepoint", [0, 1])
def test_patch_distribution_rejects_tampered_full_mesh_areas(corruption, timepoint: int) -> None:
    observations = [_preview(payload) for payload in _meshes()]
    record = observations[timepoint]
    original = record["edge_connected_patch_surface_areas_m2"]
    record["edge_connected_patch_surface_areas_m2"] = corruption(original)
    with pytest.raises(ValueError, match="Patch surface areas"):
        compare_mesh_observations(*observations)


def test_patch_distribution_rejects_tampered_full_mesh_total() -> None:
    observations = [_preview(payload) for payload in _meshes()]
    observations[0]["surface_area_m2"] *= 2
    with pytest.raises(ValueError, match="Patch surface areas"):
        compare_mesh_observations(*observations)


@pytest.mark.parametrize("timepoint", [0, 1])
def test_patch_distribution_rejects_zero_full_mesh_total(timepoint: int) -> None:
    observations = [_preview(payload) for payload in _meshes()]
    observations[timepoint]["surface_area_m2"] = 0.0
    with pytest.raises(ValueError, match="Patch surface areas"):
        compare_mesh_observations(*observations)


def test_legacy_patch_fractions_without_area_breakdown_remain_readable() -> None:
    observations = [_preview(payload) for payload in _meshes()]
    for record in observations:
        record.pop("edge_connected_patch_surface_areas_m2")
    result = compare_mesh_observations(*observations)
    assert result["ranked_patch_area_profile_distance"] == pytest.approx(0.25)
    assert result["measurement_status"] == "provisional_unverified_longitudinal_comparison"


def test_legacy_missing_topology_count_remains_readable() -> None:
    observations = [_preview(payload) for payload in _meshes()]
    for record in observations:
        record.pop("edge_connected_patch_count")
    result = compare_mesh_observations(*observations)
    assert result["ranked_patch_area_profile_distance"] == pytest.approx(0.25)
    assert result["measurement_status"] == "provisional_unverified_longitudinal_comparison"


def test_missing_legacy_distribution_does_not_invent_zero_change() -> None:
    before, after = (_preview(payload) for payload in _meshes())
    for record in (before, after):
        for field in (
            "edge_connected_patch_surface_area_fractions",
            "edge_connected_patch_area_concentration_index",
            "area_weighted_effective_patch_count",
            "edge_connected_patch_surface_areas_m2",
        ):
            record.pop(field)
    result = compare_mesh_observations(before, after)
    assert result["delta_patch_area_concentration_index"] is None
    assert result["delta_area_weighted_effective_patch_count"] is None
    assert result["ranked_patch_area_profile_distance"] is None
    assert result["ranked_patch_area_jensen_shannon_divergence_bits"] is None
    assert "patch_area_distribution_comparison_unavailable" in result["qc_warnings"]


def test_disputed_identity_withholds_patch_change_but_preserves_observations() -> None:
    before, after = (_preview(payload) for payload in _meshes())
    evidence = {
        "project_id": "project-1",
        "specimen_id": "colony:16",
        "before_observation_id": "survey-1",
        "after_observation_id": "survey-2",
        "method": "photo_match",
        "observer_id": "operator-1",
        "evidence_note": "Provisional photographic correspondence",
        "independent_reviewer_id": "reviewer-2",
        "independent_review_decision": "disputes_match",
        "independent_review_note": "Different colony morphology",
    }
    result = compare_mesh_observations(before, after, reidentification_evidence=evidence)
    assert result["before_patch_area_concentration_index"] == pytest.approx(0.625)
    assert result["after_patch_area_concentration_index"] == pytest.approx(0.5)
    assert result["delta_patch_area_concentration_index"] is None
    assert result["delta_area_weighted_effective_patch_count"] is None
    assert result["ranked_patch_area_profile_distance"] is None
    assert result["ranked_patch_area_jensen_shannon_divergence_bits"] is None
    assert result["provenance"]["longitudinal_change_withheld_due_to_identity_dispute"] is True


def test_patch_concentration_saved_workflow_matches_standalone(client: TestClient) -> None:
    project_id = str(create_project(client, "Patch concentration timepoints")["id"])
    base = f"/api/v1/projects/{project_id}"
    before, after = _meshes()
    standalone = client.post(
        f"{base}/spatial/mesh-longitudinal-comparison",
        json={"before": before, "after": after},
    )
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    graph = {
        "graph_id": "patch-concentration-longitudinal-v14",
        "name": "Provisional patch concentration comparison",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "before", "node_type": "mesh_surface_preview", "parameters": before},
            {"node_id": "after", "node_type": "mesh_surface_preview", "parameters": after},
            {"node_id": "compare", "node_type": "mesh_longitudinal_comparison"},
        ],
        "edges": [
            {
                "edge_id": "project-before",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "before",
                "target_port_id": "project",
            },
            {
                "edge_id": "project-after",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "after",
                "target_port_id": "project",
            },
            {
                "edge_id": "before-compare",
                "source_node_id": "before",
                "source_port_id": "measurement",
                "target_node_id": "compare",
                "target_port_id": "before",
            },
            {
                "edge_id": "after-compare",
                "source_node_id": "after",
                "source_port_id": "measurement",
                "target_node_id": "compare",
                "target_port_id": "after",
            },
        ],
    }
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifact = next(
        item["payload_json"]
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_longitudinal_comparison"
    )
    assert artifact == expected
    assert artifact["delta_patch_area_concentration_index"] == pytest.approx(-0.125)
    assert artifact["delta_area_weighted_effective_patch_count"] == pytest.approx(0.4)
    assert artifact["ranked_patch_area_profile_distance"] == pytest.approx(0.25)
    assert artifact["ranked_patch_area_jensen_shannon_divergence_bits"] == pytest.approx(
        0.0487949406953985
    )


def test_ranked_patch_divergence_zero_for_identical_area_profiles() -> None:
    early, late = _meshes()
    # Different geometry and calibration, but the same ranked area fractions.
    late["vertices"][4] = [16, 0, 0]
    result = compare_mesh_observations(_preview(early), _preview(late))
    assert result["ranked_patch_area_jensen_shannon_divergence_bits"] == pytest.approx(0)
    assert result["ranked_patch_area_profile_distance"] == pytest.approx(0)
    assert result["measurement_status"] == "provisional_unverified_longitudinal_comparison"


def test_ranked_patch_divergence_is_symmetric_without_correspondence() -> None:
    early, late = _meshes()
    first = compare_mesh_observations(_preview(early), _preview(late))
    # Swap which geometry is observed at each date, preserving chronological order.
    early["vertices"], late["vertices"] = late["vertices"], early["vertices"]
    second = compare_mesh_observations(_preview(early), _preview(late))
    assert first["ranked_patch_area_jensen_shannon_divergence_bits"] == pytest.approx(
        second["ranked_patch_area_jensen_shannon_divergence_bits"]
    )
    assert 0 <= first["ranked_patch_area_jensen_shannon_divergence_bits"] <= 1


@pytest.mark.parametrize("tiny_fraction", [5e-324, 1e-300])
def test_subnormal_patch_fraction_divergence_is_not_falsely_zero(
    tiny_fraction: float,
) -> None:
    observations = [_preview(payload) for payload in _meshes()]
    for record in observations:
        # Legacy fractions without per-patch areas are still supported.
        # Use valid concentration metadata to isolate numerical stability.
        record.pop("edge_connected_patch_surface_areas_m2")
        record["edge_connected_patch_surface_area_fractions"] = [1.0, 0.0]
        record["edge_connected_patch_area_concentration_index"] = 1.0
        record["area_weighted_effective_patch_count"] = 1.0
    observations[0]["edge_connected_patch_surface_area_fractions"] = [1.0, tiny_fraction]

    result = compare_mesh_observations(*observations)
    if tiny_fraction == 5e-324:
        # Half of the smallest positive subnormal cannot be represented.
        # Do not report zero as if the ranked profiles were identical.
        assert result["ranked_patch_area_profile_distance"] is None
        assert result["ranked_patch_area_jensen_shannon_divergence_bits"] is None
        assert (
            "ranked_patch_area_profile_distance_below_numeric_resolution" in result["qc_warnings"]
        )
        assert "ranked_patch_area_divergence_below_numeric_resolution" in result["qc_warnings"]
    else:
        assert result["ranked_patch_area_profile_distance"] > 0
        assert result["ranked_patch_area_jensen_shannon_divergence_bits"] > 0
        assert "ranked_patch_area_divergence_below_numeric_resolution" not in result["qc_warnings"]
    assert result["measurement_status"] == "provisional_unverified_longitudinal_comparison"
