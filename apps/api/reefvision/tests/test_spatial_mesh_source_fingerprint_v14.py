"""Imported mesh source bytes remain distinguishable from parsed geometry identity."""

from __future__ import annotations

import base64
import hashlib
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.spatial_mesh_preview_v14 import MeshPreviewRequest
from reefvision.services.spatial_mesh_longitudinal_v14 import compare_mesh_observations
from reefvision.services.spatial_mesh_surface_v14 import preview_from_request
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_spatial_mesh_cross_format_v14 import COMMON, OBJ, PLY
from reefvision.tests.test_spatial_mesh_glb_v14 import make_glb


@pytest.mark.parametrize(
    ("source_key", "source_value"),
    [
        ("obj_text", OBJ),
        ("ply_text", PLY),
        ("glb_base64", make_glb()),
    ],
    ids=["obj", "ply", "glb"],
)
def test_source_byte_fingerprint_survives_standalone_and_saved_workflow(
    client: TestClient, source_key: str, source_value: str
) -> None:
    project_id = str(create_project(client, "Source content provenance")["id"])
    base = f"/api/v1/projects/{project_id}"
    params: dict[str, Any] = {**COMMON, source_key: source_value}
    expected_bytes = (
        base64.b64decode(source_value, validate=True)
        if source_key == "glb_base64"
        else source_value.encode("utf-8")
    )
    expected_sha = hashlib.sha256(expected_bytes).hexdigest()

    direct = preview_from_request(MeshPreviewRequest.model_validate(params))
    standalone = client.post(f"{base}/spatial/mesh-preview", json=params)
    assert standalone.status_code == 200, standalone.text
    assert direct["provenance"]["source_payload_sha256"] == expected_sha
    assert direct["provenance"]["source_payload_size_bytes"] == len(expected_bytes)
    assert standalone.json()["provenance"] == direct["provenance"]
    assert direct["provenance"]["calibration_verified"] is False
    assert direct["measurement_status"] == "caller_supplied_unverified"

    graph = {
        "graph_id": f"mesh-source-fingerprint-{source_key}",
        "name": "Auditable imported mesh source identity",
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
        if item["data_type"] == "mesh_measurement_preview"
    )
    assert artifact["provenance"] == direct["provenance"]
    assert artifact["surface_area_m2"] == direct["surface_area_m2"]
    assert artifact["project_id"] == project_id
    assert artifact["measurement_status"] == "caller_supplied_unverified"


def test_source_bytes_and_parsed_geometry_have_separate_fingerprints() -> None:
    obj = preview_from_request(MeshPreviewRequest(**COMMON, obj_text=OBJ))
    ply = preview_from_request(MeshPreviewRequest(**COMMON, ply_text=PLY))
    obj_whitespace = preview_from_request(
        MeshPreviewRequest(**COMMON, obj_text=OBJ.replace("v 2 0 0\n", "v 2 0 0  \n"))
    )
    obj_provenance = obj["provenance"]
    ply_provenance = ply["provenance"]
    whitespace_provenance = obj_whitespace["provenance"]
    assert obj_provenance["geometry_sha256"] == ply_provenance["geometry_sha256"]
    assert obj_provenance["geometry_sha256"] == whitespace_provenance["geometry_sha256"]
    assert obj_provenance["source_payload_sha256"] != ply_provenance["source_payload_sha256"]
    whitespace_sha = whitespace_provenance["source_payload_sha256"]
    assert obj_provenance["source_payload_sha256"] != whitespace_sha


def test_indexed_triangles_do_not_claim_an_imported_source_file() -> None:
    result = preview_from_request(
        MeshPreviewRequest(
            **COMMON,
            vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]],
            faces=[[0, 1, 2]],
        )
    )
    assert result["provenance"]["source_format"] == "indexed_triangles"
    assert result["provenance"]["source_payload_sha256"] is None
    assert result["provenance"]["source_payload_size_bytes"] is None
    assert len(result["provenance"]["geometry_sha256"]) == 64


@pytest.mark.parametrize(
    ("source_key", "source_value"),
    [
        ("obj_text", OBJ),
        ("ply_text", PLY),
        ("glb_base64", make_glb()),
    ],
    ids=["obj", "ply", "glb"],
)
def test_unchecked_zero_byte_import_provenance_fails_but_missing_legacy_count_survives(
    source_key: str, source_value: str
) -> None:
    """A claimed imported original cannot be empty, even without a hash check."""
    common = {**COMMON, source_key: source_value, "specimen_id": "colony:16"}
    before = preview_from_request(
        MeshPreviewRequest.model_validate(
            {
                **common,
                "observation_id": "survey-1",
                "observed_at_utc": "2026-10-01T12:00:00Z",
            }
        )
    )
    after = preview_from_request(
        MeshPreviewRequest.model_validate(
            {
                **common,
                "observation_id": "survey-2",
                "observed_at_utc": "2026-10-02T12:00:00Z",
            }
        )
    )
    for observation in (before, after):
        observation["project_id"] = "local-project"
    assert before["provenance"]["source_payload_integrity_checked"] is False
    baseline = compare_mesh_observations(before, after)
    assert baseline["provenance"]["longitudinal_change_withheld_due_to_reused_source_payload"]

    before["provenance"]["source_payload_size_bytes"] = 0
    with pytest.raises(ValueError, match="Imported mesh source byte count must be positive"):
        compare_mesh_observations(before, after)

    # Older preview artifacts can omit the count entirely. Missing is not
    # equivalent to an impossible explicitly claimed zero-byte original.
    before["provenance"].pop("source_payload_size_bytes")
    legacy = compare_mesh_observations(before, after)
    assert legacy["provenance"]["longitudinal_change_withheld_due_to_reused_source_payload"]


@pytest.mark.parametrize(
    ("source_key", "source_value"),
    [("obj_text", OBJ), ("ply_text", PLY), ("glb_base64", make_glb())],
    ids=["obj", "ply", "glb"],
)
def test_imported_source_digest_check_qc_matches_saved_comparison(
    client: TestClient, source_key: str, source_value: str
) -> None:
    """A computed digest is not proof that the expected original was checked."""
    source_bytes = (
        base64.b64decode(source_value, validate=True)
        if source_key == "glb_base64"
        else source_value.encode("utf-8")
    )
    digest = hashlib.sha256(source_bytes).hexdigest()
    project_id = str(create_project(client, "Source integrity review replay")["id"])
    base = f"/api/v1/projects/{project_id}"
    shared = {**COMMON, source_key: source_value, "specimen_id": "colony:16"}
    before = {
        **shared,
        "observation_id": "survey-1",
        "observed_at_utc": "2026-10-01T12:00:00Z",
        "expected_source_payload_sha256": digest,
    }
    after = {
        **shared,
        "observation_id": "survey-2",
        "observed_at_utc": "2026-10-02T12:00:00Z",
    }
    reidentification = {
        "before_observation_id": "survey-1",
        "after_observation_id": "survey-2",
        "method": "photo_match",
        "observer_id": "lab-annotator-1",
        "evidence_note": "Provisional photo match; no independent verification",
        "before_source_payload_sha256": digest,
        "after_source_payload_sha256": digest,
    }
    response = client.post(
        f"{base}/spatial/mesh-longitudinal-comparison",
        json={
            "before": before,
            "after": after,
            "reidentification_evidence": reidentification,
        },
    )
    assert response.status_code == 200, response.text
    expected = response.json()
    warnings = expected["qc_warnings"]
    assert "before_imported_source_expected_digest_not_checked" not in warnings
    assert "after_imported_source_expected_digest_not_checked" in warnings
    assert "identical_imported_source_payload_reused_across_observations" in warnings
    assert "reidentification_source_payload_binding_unavailable" not in warnings
    bound_evidence = expected["provenance"]["reidentification_evidence"]
    assert bound_evidence["before_source_payload_sha256"] == digest
    assert expected["delta_surface_area_m2"] is None
    assert expected["provenance"]["specimen_identity_verified"] is False

    graph = {
        "graph_id": "mesh-integrity-check-qc-v14",
        "name": "Per-timepoint imported original integrity QC",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "early", "node_type": "mesh_surface_preview", "parameters": before},
            {"node_id": "late", "node_type": "mesh_surface_preview", "parameters": after},
            {
                "node_id": "compare",
                "node_type": "mesh_longitudinal_comparison",
                "parameters": {"reidentification_evidence": reidentification},
            },
        ],
        "edges": [
            {
                "edge_id": f"project-{node}",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": node,
                "target_port_id": "project",
            }
            for node in ("early", "late")
        ]
        + [
            {
                "edge_id": f"{node}-compare",
                "source_node_id": node,
                "source_port_id": "measurement",
                "target_node_id": "compare",
                "target_port_id": port,
            }
            for node, port in (("early", "before"), ("late", "after"))
        ],
    }
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
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


@pytest.mark.parametrize("reindexed", [False, True], ids=["original", "reindexed"])
@pytest.mark.parametrize("inline_after", [False, True], ids=["ply", "inline"])
@pytest.mark.parametrize("asset_before", [False, True], ids=["obj-text", "obj-asset"])
def test_rescaled_cross_format_reexport_withholds_false_growth_in_saved_workflow(
    client: TestClient, inline_after: bool, asset_before: bool, reindexed: bool
) -> None:
    """Changing source representation cannot make rescaled triangles biological growth."""
    project_id = str(create_project(client, "Rescaled reexport QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    before = {
        **COMMON,
        "obj_text": OBJ,
        "specimen_id": "colony:16",
        "observation_id": "survey-1",
        "observed_at_utc": "2026-10-01T12:00:00Z",
    }
    after = {
        **COMMON,
        "ply_text": PLY,
        "meters_per_unit": COMMON["meters_per_unit"] * 2,
        "specimen_id": "colony:16",
        "observation_id": "survey-2",
        "observed_at_utc": "2026-10-02T12:00:00Z",
    }
    if asset_before:
        uploaded = client.post(
            f"{base}/spatial/assets", files={"file": ("coral.obj", OBJ.encode("utf-8"))}
        )
        assert uploaded.status_code == 201, uploaded.text
        del before["obj_text"]
        before["asset_id"] = uploaded.json()["id"]
    if inline_after:
        del after["ply_text"]
        after["vertices"] = [[0, 0, 0], [2, 0, 0], [0, 3, 0]]
        after["faces"] = [[0, 1, 2]]
    if reindexed:
        if inline_after:
            after["vertices"] = [[0, 3, 0], [0, 0, 0], [2, 0, 0]]
            after["faces"] = [[1, 0, 2]]
        else:
            after["ply_text"] = PLY.replace(
                "0 0 0\n2 0 0\n0 3 0\n3 0 1 2\n",
                "0 3 0\n0 0 0\n2 0 0\n3 1 0 2\n",
            )
    response = client.post(
        f"{base}/spatial/mesh-longitudinal-comparison",
        json={"before": before, "after": after},
    )
    assert response.status_code == 200, response.text
    expected = response.json()
    assert expected["after_surface_area_m2"] == pytest.approx(
        4 * expected["before_surface_area_m2"]
    )
    warnings = expected["qc_warnings"]
    exact_reexport = not inline_after and not reindexed
    incomplete = inline_after and not reindexed
    assert ("identical_geometry_different_imported_source_payload" in warnings) is exact_reexport
    reexport_warning = "longitudinal_change_withheld_rescaled_reexported_geometry"
    assert (reexport_warning in warnings) is exact_reexport
    incomplete_warning = "longitudinal_change_withheld_rescaled_geometry_incomplete_import_lineage"
    assert (incomplete_warning in warnings) is incomplete
    patch_warning = "longitudinal_change_withheld_rescaled_matching_surface_patches"
    patch_flag = "longitudinal_change_withheld_due_to_rescaled_matching_surface_patches"
    assert (patch_warning in warnings) is reindexed
    assert expected["provenance"][patch_flag] is reindexed
    assert expected["provenance"]["surface_patch_fingerprint_comparison"] == "matching"
    missing_warning = "matching_surface_patches_primary_geometry_fingerprint_unavailable"
    assert missing_warning not in warnings
    match_warning = "matching_surface_patches_different_geometry_fingerprints"
    assert (match_warning in warnings) is reindexed
    assert (
        expected["provenance"]["before_geometry_sha256"]
        != expected["provenance"]["after_geometry_sha256"]
    ) is reindexed
    assert (
        "identical_imported_source_payload_reused_across_observations"
        not in expected["qc_warnings"]
    )
    assert (
        expected["provenance"]["longitudinal_change_withheld_due_to_rescaled_reexported_geometry"]
        is exact_reexport
    )
    incomplete_flag = (
        "longitudinal_change_withheld_due_to_rescaled_geometry_incomplete_import_lineage"
    )
    assert expected["provenance"][incomplete_flag] is incomplete
    if asset_before:
        assert expected["provenance"]["before_spatial_source_asset_id"] == before["asset_id"]
        assert expected["provenance"]["before_source_payload_integrity_checked"] is True
    assert expected["provenance"]["independent_acquisition_verified"] is False
    assert expected["provenance"]["scale_uncertainty_only"] is False
    for field in (
        "delta_surface_area_m2",
        "relative_surface_area_change_percent",
        "average_surface_area_change_m2_per_day",
        "delta_surface_area_scale_interval_m2",
        "delta_axis_aligned_bounding_box_diagonal_m",
    ):
        assert expected[field] is None
    assert expected["provenance"]["calibration_verified"] is False
    assert expected["provenance"]["specimen_identity_verified"] is False

    # A same-scale re-export or inline conversion does not trigger the
    # narrowly scoped recalibration withholding rule.
    same_scale = {**after, "meters_per_unit": COMMON["meters_per_unit"]}
    control = client.post(
        f"{base}/spatial/mesh-longitudinal-comparison",
        json={"before": before, "after": same_scale},
    )
    assert control.status_code == 200, control.text
    assert control.json()["delta_surface_area_m2"] == pytest.approx(0)
    assert (
        control.json()["provenance"][
            "longitudinal_change_withheld_due_to_rescaled_reexported_geometry"
        ]
        is False
    )
    assert control.json()["provenance"][incomplete_flag] is False
    assert control.json()["provenance"][patch_flag] is False
    assert control.json()["provenance"]["surface_patch_fingerprint_comparison"] == "matching"
    assert (match_warning in control.json()["qc_warnings"]) is reindexed

    graph = {
        "graph_id": "rescaled-cross-format-reexport-v14",
        "name": "Rescaled imported geometry is not growth",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "early", "node_type": "mesh_surface_preview", "parameters": before},
            {"node_id": "late", "node_type": "mesh_surface_preview", "parameters": after},
            {"node_id": "compare", "node_type": "mesh_longitudinal_comparison"},
        ],
        "edges": [
            {
                "edge_id": f"project-{node}",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": node,
                "target_port_id": "project",
            }
            for node in ("early", "late")
        ]
        + [
            {
                "edge_id": f"{node}-compare",
                "source_node_id": node,
                "source_port_id": "measurement",
                "target_node_id": "compare",
                "target_port_id": port,
            }
            for node, port in (("early", "before"), ("late", "after"))
        ],
    }
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    app = cast(FastAPI, client.app)
    digests = []
    for _ in range(2):
        run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
        assert run.status_code == 202, run.text
        assert process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(run.json()["job_id"])
        )
        detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["run"]["status"] == "succeeded"
        artifact = next(
            item
            for item in detail.json()["artifacts"]
            if item["data_type"] == "mesh_longitudinal_comparison"
        )
        assert artifact["payload_json"] == expected
        digests.append(artifact["payload_sha256"])
    assert digests[0] == digests[1]
    assert len(digests[0]) == 64


@pytest.mark.parametrize("missing", ["before", "after", "both"])
def test_rescaled_legacy_imports_with_missing_digest_withhold_change(missing: str) -> None:
    before = preview_from_request(
        MeshPreviewRequest(
            **COMMON,
            obj_text=OBJ,
            specimen_id="colony:16",
            observation_id="survey-1",
            observed_at_utc="2026-10-01T12:00:00Z",
        )
    )
    after = preview_from_request(
        MeshPreviewRequest(
            **{**COMMON, "meters_per_unit": COMMON["meters_per_unit"] * 2},
            ply_text=PLY,
            specimen_id="colony:16",
            observation_id="survey-2",
            observed_at_utc="2026-10-02T12:00:00Z",
        )
    )
    for label, preview in (("before", before), ("after", after)):
        preview["project_id"] = "project-1"
        if missing in (label, "both"):
            preview["provenance"].pop("source_payload_sha256")
    result = compare_mesh_observations(before, after)
    flag = "longitudinal_change_withheld_due_to_rescaled_geometry_incomplete_import_lineage"
    assert result["provenance"][flag] is True
    assert result["provenance"]["independent_acquisition_verified"] is False
    assert result["delta_surface_area_m2"] is None
    assert result["average_surface_area_change_m2_per_day"] is None
    assert result["after_surface_area_m2"] == pytest.approx(4 * result["before_surface_area_m2"])


@pytest.mark.parametrize("asset_side", ["before", "after"])
def test_rescaled_legacy_asset_without_format_or_digest_withholds_change(asset_side: str) -> None:
    """An asset-linked legacy preview remains an import even without file metadata."""
    previews = []
    for side, scale, day in (("before", 0.01, 1), ("after", 0.02, 2)):
        source = (
            {"obj_text": OBJ}
            if side == asset_side
            else {"vertices": [[0, 0, 0], [2, 0, 0], [0, 3, 0]], "faces": [[0, 1, 2]]}
        )
        preview = preview_from_request(
            MeshPreviewRequest.model_validate(
                {
                    **COMMON,
                    **source,
                    "meters_per_unit": scale,
                    "specimen_id": "colony:16",
                    "observation_id": f"survey-{day}",
                    "observed_at_utc": f"2026-10-0{day}T12:00:00Z",
                }
            )
        )
        preview["project_id"] = "project-1"
        if side == asset_side:
            provenance = preview["provenance"]
            provenance["spatial_source_asset_id"] = "00000000-0000-4000-8000-000000000001"
            for field in (
                "source_format",
                "source_payload_sha256",
                "source_payload_size_bytes",
                "source_payload_integrity_checked",
            ):
                provenance.pop(field, None)
        previews.append(preview)
    result = compare_mesh_observations(*previews)
    flag = "longitudinal_change_withheld_due_to_rescaled_geometry_incomplete_import_lineage"
    assert result["provenance"][flag] is True
    assert result["provenance"]["independent_acquisition_verified"] is False
    assert result["provenance"]["acquisition_lineage_status"] == (
        "insufficient_original_source_lineage"
    )
    assert result["delta_surface_area_m2"] is None
    assert result["delta_axis_aligned_bounding_box_diagonal_m"] is None
    assert result["after_surface_area_m2"] == pytest.approx(4 * result["before_surface_area_m2"])


@pytest.mark.parametrize("patch_metadata", ["missing", "invalid", "partial", "different"])
def test_rescaled_patch_match_requires_complete_equal_fingerprints(patch_metadata: str) -> None:
    before = preview_from_request(
        MeshPreviewRequest(
            **COMMON,
            obj_text=OBJ,
            specimen_id="colony:16",
            observation_id="survey-1",
            observed_at_utc="2026-10-01T12:00:00Z",
        )
    )
    after = preview_from_request(
        MeshPreviewRequest(
            **{**COMMON, "meters_per_unit": COMMON["meters_per_unit"] * 2},
            vertices=[[0, 3, 0], [0, 0, 0], [2, 0, 0]],
            faces=[[1, 0, 2]],
            specimen_id="colony:16",
            observation_id="survey-2",
            observed_at_utc="2026-10-02T12:00:00Z",
        )
    )
    for preview in (before, after):
        preview["project_id"] = "project-1"
    flag = "longitudinal_change_withheld_due_to_rescaled_matching_surface_patches"
    matched = compare_mesh_observations(before, after)
    assert matched["provenance"][flag] is True
    assert matched["provenance"]["surface_patch_fingerprint_comparison"] == "matching"
    key = "edge_connected_patch_geometry_sha256"
    if patch_metadata == "missing":
        after.pop(key)
    elif patch_metadata == "invalid":
        after[key] = ["not-a-digest"]
    elif patch_metadata == "partial":
        after[key] = []
    else:
        after[key] = ["f" * 64]
    result = compare_mesh_observations(before, after)
    assert result["provenance"][flag] is False
    comparison = "different" if patch_metadata == "different" else "unavailable"
    assert result["provenance"]["surface_patch_fingerprint_comparison"] == comparison
    assert "matching_surface_patches_different_geometry_fingerprints" not in result["qc_warnings"]
    assert result["provenance"]["independent_acquisition_verified"] is False
    assert result["provenance"]["specimen_identity_verified"] is False


@pytest.mark.parametrize("missing_side", ["before", "after", "both"])
@pytest.mark.parametrize("invalid_digest", [False, True], ids=["missing", "malformed"])
@pytest.mark.parametrize("rescaled", [False, True], ids=["same-scale", "rescaled"])
def test_matching_legacy_patches_with_unavailable_primary_digest(
    missing_side: str, invalid_digest: bool, rescaled: bool
) -> None:
    before = preview_from_request(
        MeshPreviewRequest(
            **COMMON,
            obj_text=OBJ,
            specimen_id="colony:16",
            observation_id="survey-1",
            observed_at_utc="2026-10-01T12:00:00Z",
        )
    )
    scale = COMMON["meters_per_unit"] * (2 if rescaled else 1)
    after = preview_from_request(
        MeshPreviewRequest(
            **{**COMMON, "meters_per_unit": scale},
            vertices=[[0, 3, 0], [0, 0, 0], [2, 0, 0]],
            faces=[[1, 0, 2]],
            specimen_id="colony:16",
            observation_id="survey-2",
            observed_at_utc="2026-10-02T12:00:00Z",
        )
    )
    for side, preview in (("before", before), ("after", after)):
        preview["project_id"] = "project-1"
        if missing_side in (side, "both"):
            if invalid_digest:
                preview["provenance"]["geometry_sha256"] = "invalid"
            else:
                preview["provenance"].pop("geometry_sha256")
    result = compare_mesh_observations(before, after)
    provenance = result["provenance"]
    warnings = result["qc_warnings"]
    assert provenance["surface_patch_fingerprint_comparison"] == "matching"
    assert "matching_surface_patches_primary_geometry_fingerprint_unavailable" in warnings
    assert "matching_surface_patches_different_geometry_fingerprints" not in warnings
    flag = "longitudinal_change_withheld_due_to_rescaled_matching_surface_patches"
    assert provenance[flag] is rescaled
    assert provenance["independent_acquisition_verified"] is False
    assert provenance["specimen_identity_verified"] is False
    if rescaled:
        assert result["delta_surface_area_m2"] is None
        assert result["delta_axis_aligned_bounding_box_diagonal_m"] is None
        assert result["average_surface_area_change_m2_per_day"] is None
    else:
        assert result["delta_surface_area_m2"] == pytest.approx(0)

    # Missing primary provenance alone cannot establish a surface match.
    after.pop("edge_connected_patch_geometry_sha256")
    control = compare_mesh_observations(before, after)
    assert control["provenance"]["surface_patch_fingerprint_comparison"] == "unavailable"
    assert control["provenance"][flag] is False
    assert (
        "matching_surface_patches_primary_geometry_fingerprint_unavailable"
        not in control["qc_warnings"]
    )
