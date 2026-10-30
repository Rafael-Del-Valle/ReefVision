"""Asset-bound independent calibration review survives saved workflow execution.

An attributed review is auditable QC, never verified physical scale or identity.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import SpatialSourceAsset
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.spatial_source_assets_v14 import MAX_BYTES
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project

OBJ = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
PLY = (
    b"ply\nformat ascii 1.0\nelement vertex 3\n"
    b"property float x\nproperty float y\nproperty float z\n"
    b"end_header\n0 0 0\n1 0 0\n0 1 0\n"
)


@pytest.mark.parametrize("bind_asset", [True, False], ids=["bound", "legacy-unbound"])
@pytest.mark.parametrize(
    ("filename", "original", "endpoint", "node_type", "artifact_type"),
    [
        (
            "coral.obj",
            OBJ,
            "mesh-preview",
            "mesh_surface_preview",
            "mesh_measurement_preview",
        ),
        (
            "survey.ply",
            PLY,
            "point-cloud-preview",
            "point_cloud_preview",
            "point_cloud_measurement_preview",
        ),
    ],
)
def test_project_original_review_replays_identically_in_saved_workflow(
    client: TestClient,
    filename: str,
    original: bytes,
    endpoint: str,
    node_type: str,
    artifact_type: str,
    bind_asset: bool,
) -> None:
    project_id = str(create_project(client, "Reviewed 3D source replay")["id"])
    base = f"/api/v1/projects/{project_id}"
    imported = client.post(f"{base}/spatial/assets", files={"file": (filename, original)})
    assert imported.status_code == 201, imported.text
    asset = imported.json()
    params = {
        "asset_id": asset["id"],
        "expected_source_payload_sha256": asset["sha256"],
        "meters_per_unit": 0.01,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified scale bar in source images",
        "relative_scale_uncertainty": 0.05,
        "specimen_id": "colony-16",
        "observation_id": "visit-1",
        "observed_at_utc": "2026-10-01T12:00:00Z",
        "coordinate_frame_id": "survey-local-A",
    }
    baseline = client.post(f"{base}/spatial/{endpoint}", json=params)
    assert baseline.status_code == 200, baseline.text
    params["calibration_review"] = {
        "calibration_operator_id": "operator-1",
        "independent_reviewer_id": "reviewer-2",
        "independent_review_decision": "disputes_scale",
        "independent_review_note": "Scale bar needs field verification",
        "reviewed_at_utc": "2026-10-02T12:00:00Z",
        "reviewed_geometry_sha256": baseline.json()["provenance"]["geometry_sha256"],
        "reviewed_source_payload_sha256": asset["sha256"],
        "reviewed_coordinate_frame_id": "survey-local-A",
        "reviewed_specimen_id": "colony-16",
        "reviewed_observation_id": "visit-1",
        "reviewed_observed_at_utc": "2026-10-01T12:00:00Z",
        "reviewed_meters_per_unit": 0.01,
        "reviewed_calibration_method": "ruler",
        "reviewed_calibration_evidence": "Unverified scale bar in source images",
        "reviewed_relative_scale_uncertainty": 0.05,
    }
    if bind_asset:
        params["calibration_review"]["reviewed_spatial_source_asset_id"] = asset["id"]
    standalone = client.post(f"{base}/spatial/{endpoint}", json=params)
    assert standalone.status_code == 200, standalone.text
    expected = standalone.json()
    assert expected["provenance"]["spatial_source_asset_id"] == asset["id"]
    assert expected["provenance"]["calibration_verified"] is False
    assert expected["provenance"]["specimen_identity_verified"] is False
    assert (
        expected["provenance"]["calibration_review_evidence"]["independent_review_decision"]
        == "disputes_scale"
    )
    assert "independent_calibration_review_disputes_scale" in expected["qc_warnings"]
    assert "project_source_original_unreviewed" in expected["qc_warnings"]
    assert (
        "independent_calibration_review_source_asset_unbound" in expected["qc_warnings"]
    ) is not bind_asset

    graph = {
        "graph_id": f"asset-review-{node_type}",
        "name": "Auditable provisional 3D source review",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "measure", "node_type": node_type, "parameters": params},
        ],
        "edges": [
            {
                "edge_id": "project-measure",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "measure",
                "target_port_id": "project",
            }
        ],
    }
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    assert (
        saved.json()["graph_json"]["nodes"][1]["parameters"]["calibration_review"]
        == params["calibration_review"]
    )
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
        if item["data_type"] == artifact_type
    )
    assert artifact == expected

    if bind_asset:
        # Identical bytes imported into another project still have a distinct
        # project-owned identity. A review for that asset cannot be replayed.
        foreign_project = str(create_project(client, "Separate imported source")["id"])
        foreign = client.post(
            f"/api/v1/projects/{foreign_project}/spatial/assets",
            files={"file": (filename, original)},
        )
        assert foreign.status_code == 201, foreign.text
        assert foreign.json()["sha256"] == asset["sha256"]
        assert foreign.json()["id"] != asset["id"]
        invalid_params = {
            **params,
            "calibration_review": {
                **params["calibration_review"],
                "reviewed_spatial_source_asset_id": foreign.json()["id"],
            },
        }
        rejected = client.post(f"{base}/spatial/{endpoint}", json=invalid_params)
        assert rejected.status_code == 400, rejected.text
        assert "does not match imported spatial source asset" in rejected.text
        invalid_graph = {
            **graph,
            "graph_id": f"foreign-asset-review-{node_type}",
            "nodes": [
                graph["nodes"][0],
                {**graph["nodes"][1], "parameters": invalid_params},
            ],
        }
        rejected_save = client.post(
            f"{base}/workflow-graphs", json={"graph": invalid_graph}
        )
        assert rejected_save.status_code == 201, rejected_save.text
        rejected_run = client.post(
            f"{base}/workflow-runs",
            json={"graph_record_id": rejected_save.json()["id"]},
        )
        assert rejected_run.status_code == 202, rejected_run.text
        assert not process_workflow_run_job(
            app.state.settings,
            app.state.session_factory,
            str(rejected_run.json()["job_id"]),
        )
        rejected_detail = client.get(f"/api/v1/workflow-runs/{rejected_run.json()['id']}")
        assert rejected_detail.status_code == 200, rejected_detail.text
        assert rejected_detail.json()["run"]["status"] == "failed"
        assert not any(
            item["data_type"] == artifact_type
            for item in rejected_detail.json()["artifacts"]
        )

    # Reusing a review after changing physical scale must fail closed.
    stale = client.post(
        f"{base}/spatial/{endpoint}",
        json={**params, "meters_per_unit": 0.02},
    )
    assert stale.status_code == 400, stale.text


def test_original_read_is_bounded_even_if_file_grows_during_read(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_id = str(create_project(client, "Bounded 3D original read")["id"])
    base = f"/api/v1/projects/{project_id}"
    imported = client.post(f"{base}/spatial/assets", files={"file": ("coral.obj", OBJ)})
    assert imported.status_code == 201, imported.text
    asset_id = imported.json()["id"]
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        record = session.get(SpatialSourceAsset, asset_id)
        assert record is not None
        original_path = resolve_managed_project_path(app.state.settings, record.managed_path)

    # Simulate replacement between path checks and the actual file read.
    read_sizes: list[int] = []

    class TrackedBytesIO(BytesIO):
        def read(self, size: int = -1) -> bytes:
            read_sizes.append(size)
            return super().read(size)

    oversized_stream = TrackedBytesIO(b"x" * (MAX_BYTES + 2))
    original_open = Path.open

    def changed_open(path: Path, *args: object, **kwargs: object) -> BytesIO:
        if path == original_path:
            return oversized_stream
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", changed_open)
    response = client.get(f"{base}/spatial/assets/{asset_id}/content")
    assert response.status_code == 400, response.text
    assert read_sizes == [MAX_BYTES + 1]
