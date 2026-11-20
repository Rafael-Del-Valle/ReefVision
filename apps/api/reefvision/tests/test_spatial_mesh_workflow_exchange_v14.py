"""Project Exchange preserves historical mesh receipts and replays local bindings."""

from __future__ import annotations

from hashlib import sha256
from json import dumps
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.domain.errors import ValidationError
from reefvision.jobs.project_exchange import process_project_exchange_export_job
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.project_exchange_mesh_v14 import validate_mesh_workflow_receipts
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project


def _digest(bundle: dict[str, Any]) -> str:
    return sha256(
        dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def test_comparison_with_stale_measurement_digest_is_rejected() -> None:
    # Older comparisons without a separate review bundle still have a payload digest.
    payload = {"provenance": {}, "delta_surface_area_m2": 0.5}
    archive = {
        "workflow_artifacts": [
            {
                "data_type": "mesh_longitudinal_comparison",
                "payload_sha256": canonical_json_sha256(payload),
                "payload_json": payload,
            }
        ]
    }
    validate_mesh_workflow_receipts(archive)
    payload["delta_surface_area_m2"] = 0.25
    with pytest.raises(ValidationError, match="payload checksum"):
        validate_mesh_workflow_receipts(archive)


def _run(client: TestClient, base: str, graph_record_id: str) -> dict[str, Any]:
    queued = client.post(f"{base}/workflow-runs", json={"graph_record_id": graph_record_id})
    assert queued.status_code == 202, queued.text
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, queued.json()["job_id"]
    )
    return _detail(client, queued.json()["id"])


def _detail(client: TestClient, run_id: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/workflow-runs/{run_id}")
    assert response.status_code == 200, response.text
    detail = response.json()
    assert isinstance(detail, dict)
    assert detail["run"]["status"] == "succeeded", detail
    return detail


def _comparison(detail: dict[str, Any]) -> dict[str, Any]:
    return next(
        entry
        for entry in detail["artifacts"]
        if entry["data_type"] == "mesh_longitudinal_comparison"
    )


def _exchange(client: TestClient, base: str) -> dict[str, Any]:
    export = client.post(f"{base}/exchange-packages", json={"include_media": True})
    assert export.status_code == 202, export.text
    app = cast(FastAPI, client.app)
    assert process_project_exchange_export_job(
        app.state.settings, app.state.session_factory, export.json()["job_id"]
    )
    archive = client.get(f"/api/v1/exchange-packages/{export.json()['package']['id']}/download")
    assert archive.status_code == 200, archive.text
    imported = client.post(
        "/api/v1/exchange-packages/import",
        files={"file": ("mesh.reefvision.zip", archive.content, "application/zip")},
    )
    assert imported.status_code == 201, imported.text
    result = imported.json()
    assert isinstance(result, dict)
    assert result["package"]["format_version"] == "1.0"
    return result


def test_exchange_keeps_archival_review_and_replays_local_mesh_sources(client: TestClient) -> None:
    project_id = str(create_project(client, "Two acquisitions for exchange")["id"])
    base = f"/api/v1/projects/{project_id}"
    assets = {}
    for slot, height in (("before", 1), ("after", 2)):
        original = f"v 0 0 0\nv 1 0 0\nv 0 {height} 0\nf 1 2 3\n".encode()
        imported = client.post(
            f"{base}/spatial/assets",
            files={"file": (f"{slot}.obj", original, "text/plain")},
        )
        assert imported.status_code == 201, imported.text
        assets[slot] = imported.json()
    # Deliberately make declared scientific labels equal genuine source UUIDs.
    # Exchange may remap the database links, but these user labels remain literal.
    frame_id = assets["before"]["id"]
    specimen = project_id
    nodes: list[dict[str, Any]] = [{"node_id": "project", "node_type": "project_source"}]
    edges = []
    for slot, day in (("before", 1), ("after", 2)):
        asset = assets[slot]
        nodes.append(
            {
                "node_id": slot,
                "node_type": "mesh_surface_preview",
                "parameters": {
                    "asset_id": asset["id"],
                    "expected_source_payload_sha256": asset["sha256"],
                    "meters_per_unit": 1,
                    "calibration_method": "ruler",
                    "calibration_evidence": assets["after"]["id"],
                    "relative_scale_uncertainty": 0.1,
                    "specimen_id": specimen,
                    "observation_id": asset["id"],
                    "coordinate_frame_id": frame_id,
                    "observed_at_utc": f"2026-01-0{day}T12:00:00Z",
                    **(
                        {
                            "anatomical_branch": {
                                "ordered_points_source_units": [[0, 0, 0], [1, 0, 0]],
                                "base_landmark": "Declared base",
                                "tip_landmark": "Declared tip",
                                "selection_method": "Synthetic line",
                                "operator_id": project_id,
                            }
                        }
                        if slot == "before"
                        else {}
                    ),
                },
            }
        )
        edges.extend(
            [
                {
                    "edge_id": f"project-{slot}",
                    "source_node_id": "project",
                    "source_port_id": "project",
                    "target_node_id": slot,
                    "target_port_id": "project",
                },
                {
                    "edge_id": f"{slot}-compare",
                    "source_node_id": slot,
                    "source_port_id": "measurement",
                    "target_node_id": "compare",
                    "target_port_id": slot,
                },
            ]
        )
    nodes.append(
        {
            "node_id": "compare",
            "node_type": "mesh_longitudinal_comparison",
            "parameters": {
                "reidentification_evidence": {
                    "project_id": project_id,
                    "specimen_id": specimen,
                    "before_observation_id": assets["before"]["id"],
                    "after_observation_id": assets["after"]["id"],
                    "method": "survey_tag",
                    "observer_id": assets["before"]["id"],
                    "evidence_note": "Fixture tags",
                    "independent_reviewer_id": assets["after"]["id"],
                    "independent_review_decision": "supports_match",
                    "independent_review_note": "Fixture agreement",
                    "independent_reviewed_at_utc": "2026-01-03T12:00:00Z",
                    "before_spatial_source_asset_id": assets["before"]["id"],
                    "after_spatial_source_asset_id": assets["after"]["id"],
                    "before_source_payload_sha256": assets["before"]["sha256"],
                    "after_source_payload_sha256": assets["after"]["sha256"],
                }
            },
        }
    )
    saved = client.post(
        f"{base}/workflow-graphs",
        json={
            "graph": {
                "graph_id": "two-for-exchange",
                "name": "Two acquisitions for exchange",
                "nodes": nodes,
                "edges": edges,
            }
        },
    )
    assert saved.status_code == 201, saved.text
    source = _comparison(_run(client, base, saved.json()["id"]))
    source_provenance = source["payload_json"]["provenance"]
    assert source_provenance["review_evidence_bundle_sha256"] == _digest(
        source_provenance["review_evidence_bundle"]
    )

    imported = _exchange(client, base)
    restored_project = imported["project_id"]
    restored_base = f"/api/v1/projects/{restored_project}"
    [restored_run] = client.get(f"{restored_base}/workflow-runs").json()
    restored_detail = _detail(client, restored_run["id"])
    archived = _comparison(restored_detail)
    assert archived["payload_sha256"] == source["payload_sha256"]
    assert archived["payload_json"] == source["payload_json"]

    replayed = _run(client, restored_base, restored_run["workflow_graph_record_id"])
    local = _comparison(replayed)
    provenance = local["payload_json"]["provenance"]
    bundle = provenance["review_evidence_bundle"]
    assert provenance["review_evidence_bundle_sha256"] == _digest(bundle)
    assert bundle["project_id"] == restored_project
    assert bundle["before_spatial_source_asset_id"] != assets["before"]["id"]
    assert bundle["before_source_payload_sha256"] == assets["before"]["sha256"]
    assert bundle["before_observation_id"] == assets["before"]["id"]
    assert bundle["after_observation_id"] == assets["after"]["id"]
    assert bundle["before_coordinate_frame_id"] == frame_id
    assert bundle["before_calibration_evidence"] == assets["after"]["id"]
    assert bundle["specimen_id"] == specimen
    assert bundle["reidentification_evidence"]["observer_id"] == assets["before"]["id"]
    assert (
        local["payload_json"]["delta_surface_area_m2"]
        == source["payload_json"]["delta_surface_area_m2"]
    )
    for detail in (restored_detail, replayed):
        payload = next(
            artifact["payload_json"]
            for artifact in detail["artifacts"]
            if "declared_branch_centerline" in artifact["payload_json"]
        )
        assert payload["project_id"] == restored_project
        assert (
            payload["provenance"]["spatial_source_asset_id"]
            == bundle["before_spatial_source_asset_id"]
        )
        assert payload["declared_branch_centerline"]["declaration"]["operator_id"] == project_id
        assert payload["declared_branch_centerline"]["coordinate_frame_id"] == frame_id
        assert payload["declared_branch_centerline"]["anatomical_claim_verified"] is False

    transferred = _exchange(client, restored_base)
    local_origin_map = transferred["package"]["options_json"]["origin_id_map"]
    final_project = transferred["project_id"]
    assert local_origin_map[project_id] == final_project
    assert local_origin_map[assets["before"]["id"]] != assets["before"]["id"]
    final_base = f"/api/v1/projects/{final_project}"
    final_runs = client.get(f"{final_base}/workflow-runs").json()
    final_artifacts = [_comparison(_detail(client, run["id"])) for run in final_runs]
    assert any(
        artifact["payload_sha256"] == source["payload_sha256"]
        and artifact["payload_json"] == source["payload_json"]
        for artifact in final_artifacts
    )
