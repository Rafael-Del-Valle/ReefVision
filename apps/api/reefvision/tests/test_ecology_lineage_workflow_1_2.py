"""Paired-count lineage checks in standalone and saved Workflow Builder execution."""

from __future__ import annotations

from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_workflow_model_agreement_1_2 import _graph, _pairs


def _invalid_colony_pairs() -> list[dict[str, object]]:
    pairs = _pairs()
    for index, row in enumerate(pairs):
        row["experimental_unit_type"] = "colony"
        row["experimental_unit_id"] = "colony-unit-1"
        row["parent_colony_id"] = f"parent-{index}"
    return pairs


def test_standalone_rejects_mixed_parents_in_colony_unit(client: TestClient) -> None:
    response = client.post(
        "/api/v1/ecology/paired-count-comparison",
        json={"pairs": _invalid_colony_pairs(), "reference_kind": "human_consensus"},
    )
    assert response.status_code == 400, response.text
    assert "different parent colonies" in response.json()["detail"]


def test_saved_workflow_fails_closed_on_mixed_colony_lineage(client: TestClient) -> None:
    project = create_project(client, "Paired count colony-lineage review")
    project_id = str(project["id"])
    graph = _graph()
    graph["nodes"][1]["parameters"]["pairs"] = _invalid_colony_pairs()
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": graph, "create_new_revision": True},
    )
    assert saved.status_code == 201, saved.text
    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert queued.status_code == 202, queued.text
    app = cast(FastAPI, client.app)
    assert (
        process_workflow_run_job(
            app.state.settings,
            app.state.session_factory,
            str(queued.json()["job_id"]),
        )
        is False
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["run"]["status"] == "failed"
    assert "different parent colonies" in body["run"]["error_message"]
    assert not any(row["data_type"] == "paired_count_comparison" for row in body["artifacts"])


def test_saved_workflow_rejects_same_organism_in_two_tanks(client: TestClient) -> None:
    """Repeated images of one organism cannot create a second tank replicate."""
    project = create_project(client, "Cross-tank organism identity guard")
    project_id = str(project["id"])
    pairs = _pairs()
    pairs[1]["organism_id"] = pairs[0]["organism_id"]
    pairs[1]["experimental_unit_id"] = "tank-B"
    standalone = client.post(
        "/api/v1/ecology/paired-count-comparison",
        json={"pairs": pairs, "reference_kind": "human_consensus"},
    )
    assert standalone.status_code == 400, standalone.text
    assert "change experimental units" in standalone.json()["detail"]

    graph = _graph()
    graph["nodes"][1]["parameters"]["pairs"] = pairs
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": graph, "create_new_revision": True},
    )
    assert saved.status_code == 201, saved.text
    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert queued.status_code == 202, queued.text
    app = cast(FastAPI, client.app)
    assert (
        process_workflow_run_job(
            app.state.settings,
            app.state.session_factory,
            str(queued.json()["job_id"]),
        )
        is False
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["run"]["status"] == "failed"
    assert "change experimental units" in body["run"]["error_message"]
    assert not any(row["data_type"] == "paired_count_comparison" for row in body["artifacts"])


def test_standalone_accepts_parent_fragments_in_separate_tanks(client: TestClient) -> None:
    pairs = _pairs()
    for index, row in enumerate(pairs):
        row["parent_colony_id"] = "same-parent"
        row["experimental_unit_id"] = f"tank-{index}"
    response = client.post(
        "/api/v1/ecology/paired-count-comparison",
        json={"pairs": pairs, "reference_kind": "human_consensus"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["declared_independent_unit_count"] == 2
    assert payload["evidence_level"] == "caller_supplied_unverified"
    assert payload["review_status"] == "requires_source_verification"
    assert payload["analysis_provenance"]["algorithm_version"] == "ecology-paired-count-0007"
    assert payload["overcount_pair_count"] == 1
    assert payload["undercount_pair_count"] == 1
    assert payload["exact_match_pair_count"] == 0
    assert payload["percent_contributing_independent_unit_count"] == 2
    assert payload["mean_signed_percent_deviation"] == 0
    assert payload["unit_balanced_mean_signed_percent_deviation"] == 0
    assert payload["cross_unit_shared_parent_colony_ids"] == ["same-parent"]


def test_parent_lineage_changes_canonical_fingerprint(client: TestClient) -> None:
    pairs = _pairs()
    for row in pairs:
        row["parent_colony_id"] = "parent-A"
    before = client.post(
        "/api/v1/ecology/paired-count-comparison",
        json={"pairs": pairs, "reference_kind": "human_consensus"},
    )
    assert before.status_code == 200, before.text
    pairs[0]["parent_colony_id"] = "parent-B"
    after = client.post(
        "/api/v1/ecology/paired-count-comparison",
        json={"pairs": pairs, "reference_kind": "human_consensus"},
    )
    assert after.status_code == 200, after.text
    assert (
        before.json()["analysis_provenance"]["canonical_input_sha256"]
        != after.json()["analysis_provenance"]["canonical_input_sha256"]
    )


def test_saved_workflow_discloses_shared_parent_across_tanks(client: TestClient) -> None:
    """A shared parent is disclosed, without collapsing two declared tank units."""
    project = create_project(client, "Shared-parent tank agreement audit")
    project_id = str(project["id"])
    pairs = _pairs()
    for index, row in enumerate(pairs):
        row["parent_colony_id"] = "same-parent"
        row["experimental_unit_id"] = f"tank-{index}"
    standalone = client.post(
        "/api/v1/ecology/paired-count-comparison",
        json={"pairs": pairs, "reference_kind": "human_consensus"},
    )
    assert standalone.status_code == 200, standalone.text

    graph = _graph()
    graph["nodes"][1]["parameters"]["pairs"] = pairs
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": graph, "create_new_revision": True},
    )
    assert saved.status_code == 201, saved.text
    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert queued.status_code == 202, queued.text
    app = cast(FastAPI, client.app)
    assert (
        process_workflow_run_job(
            app.state.settings,
            app.state.session_factory,
            str(queued.json()["job_id"]),
        )
        is True
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifacts = [
        row["payload_json"]
        for row in detail.json()["artifacts"]
        if row["data_type"] == "paired_count_comparison"
    ]
    assert len(artifacts) == 1
    payload = artifacts[0]
    assert payload["project_id"] == project_id
    assert payload["declared_independent_unit_count"] == 2
    assert {unit["experimental_unit_id"] for unit in payload["unit_summaries"]} == {
        "tank-0",
        "tank-1",
    }
    assert payload["observed_organism_count"] == 2
    assert payload["paired_observation_count"] == 2
    assert payload["repeated_pair_count_beyond_first_per_organism"] == 0
    assert payload["cross_unit_shared_parent_colony_ids"] == ["same-parent"]
    assert payload["analysis_provenance"]["algorithm_version"] == "ecology-paired-count-0007"
    assert payload["evidence_level"] == "caller_supplied_unverified"
    assert payload["review_status"] == "requires_source_verification"
    assert payload["overcount_pair_count"] == 1
    assert payload["undercount_pair_count"] == 1
    assert payload["exact_match_pair_count"] == 0
    assert (payload["overcount_organism_count"], payload["undercount_organism_count"], payload["balanced_organism_count"]) == (1, 1, 0)
    assert payload["percent_contributing_independent_unit_count"] == 2
    assert payload["unit_balanced_mean_signed_percent_deviation"] == 0
    assert all(unit["organism_count"] == 1 for unit in payload["unit_summaries"])
    assert [
        (unit["overcount_pair_count"], unit["undercount_pair_count"])
        for unit in payload["unit_summaries"]
    ] == [(1, 0), (0, 1)]
    for key in (
        "analysis_provenance",
        "cross_unit_shared_parent_colony_ids",
        "unit_summaries",
        "organism_and_unit_balanced_mean_signed_bias",
        "overcount_pair_count",
        "undercount_pair_count",
        "exact_match_pair_count",
        "percent_contributing_independent_unit_count",
        "unit_balanced_mean_signed_percent_deviation",
    ):
        assert payload[key] == standalone.json()[key]
