"""Saved 1.4 longitudinal graphs must enforce the same review chronology as the API."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project


def _observation(observation_id: str, observed_at_utc: str) -> dict:
    return {
        "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
        "faces": [[0, 1, 2]],
        "meters_per_unit": 1,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified field ruler",
        "relative_scale_uncertainty": 0.1,
        "specimen_id": "colony-16",
        "observation_id": observation_id,
        "observed_at_utc": observed_at_utc,
        "coordinate_frame_id": "survey-local",
    }


def _review(evidence_key: str, project_id: str, reviewed_at_utc: str) -> dict:
    shared = {
        "independent_reviewer_id": "reviewer-2",
        "independent_review_note": "Provisional review, not certification",
        "independent_reviewed_at_utc": reviewed_at_utc,
    }
    if evidence_key == "registration_evidence":
        return {
            **shared,
            "project_id": project_id,
            "source_frame_id": "survey-local",
            "target_frame_id": "survey-local",
            "source_observation_id": "survey-1",
            "target_observation_id": "survey-2",
            "source_observed_at_utc": "2026-10-01T12:00:00Z",
            "target_observed_at_utc": "2026-10-02T12:00:00Z",
            "method": "landmark",
            "rms_residual_m": 0.02,
            "correspondence_count": 6,
            "evidence_note": "Provisional landmark fit",
            "registration_operator_id": "operator-1",
            "independent_review_decision": "supports_alignment",
        }
    return {
        **shared,
        "project_id": project_id,
        "specimen_id": "colony-16",
        "before_observation_id": "survey-1",
        "after_observation_id": "survey-2",
        "before_observed_at_utc": "2026-10-01T12:00:00Z",
        "after_observed_at_utc": "2026-10-02T12:00:00Z",
        "method": "photo_match",
        "observer_id": "observer-1",
        "evidence_note": "Provisional visual match",
        "independent_review_decision": "supports_match",
    }


@pytest.mark.parametrize("evidence_key", ["registration_evidence", "reidentification_evidence"])
@pytest.mark.parametrize(
    ("reviewed_at_utc", "valid", "case_variant_self_review"),
    [
        ("2026-10-02T06:59:59-05:00", False, False),
        ("2026-10-02T07:00:00-05:00", True, False),
        ("2026-10-03T07:00:00-05:00", True, False),
        # A caller cannot impersonate an independent reviewer with a case-only alias.
        ("2026-10-03T07:00:00-05:00", False, True),
    ],
)
def test_saved_longitudinal_review_chronology_matches_standalone(
    client: TestClient,
    evidence_key: str,
    reviewed_at_utc: str,
    valid: bool,
    case_variant_self_review: bool,
) -> None:
    """Saved graphs reject impossible chronology and case-only reviewer impersonation."""
    project_id = str(create_project(client, "Independent review replay QC")["id"])
    base = f"/api/v1/projects/{project_id}"
    before = _observation("survey-1", "2026-10-01T12:00:00Z")
    after = _observation("survey-2", "2026-10-02T12:00:00Z")
    evidence = _review(evidence_key, project_id, reviewed_at_utc)
    if case_variant_self_review:
        evidence["independent_reviewer_id"] = (
            "OPERATOR-1" if evidence_key == "registration_evidence" else "OBSERVER-1"
        )
    standalone = client.post(
        f"{base}/spatial/mesh-longitudinal-comparison",
        json={"before": before, "after": after, evidence_key: evidence},
    )
    if valid:
        assert standalone.status_code == 200, standalone.text
        expected = standalone.json()
        recorded = expected["provenance"][evidence_key]
        assert recorded["independent_reviewed_at_utc"] == reviewed_at_utc
        assert expected["provenance"]["specimen_identity_verified"] is False
        assert expected["provenance"]["coordinate_registration_verified"] is False
    else:
        assert standalone.status_code in (400, 422), standalone.text
        if case_variant_self_review:
            assert "reviewer must differ" in standalone.text.lower()
        else:
            assert "cannot predate bound observations" in standalone.text

    graph = {
        "graph_id": f"review-chronology-{evidence_key}-{valid}",
        "name": "Provisional independent review chronology replay",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "early",
                "node_type": "mesh_surface_preview",
                "parameters": before,
            },
            {
                "node_id": "late",
                "node_type": "mesh_surface_preview",
                "parameters": after,
            },
            {
                "node_id": "compare",
                "node_type": "mesh_longitudinal_comparison",
                "parameters": {evidence_key: evidence},
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
    saved_parameters = saved.json()["graph_json"]["nodes"][3]["parameters"]
    assert saved_parameters[evidence_key] == evidence

    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    completed = process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    comparison_artifacts = [
        item
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_longitudinal_comparison"
    ]
    if valid:
        assert completed
        assert detail.json()["run"]["status"] == "succeeded"
        assert len(comparison_artifacts) == 1
        assert comparison_artifacts[0]["payload_json"] == expected
        assert len(comparison_artifacts[0]["payload_sha256"]) == 64
    else:
        assert not completed
        assert detail.json()["run"]["status"] == "failed"
        assert comparison_artifacts == []
