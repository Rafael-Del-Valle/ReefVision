"""Reviewed taxon labeling and grouped, known-positive detectability at project API entry."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import import_one
from reefvision.tests.test_reviewer_lab_v15 import role_fixture, successful

START = datetime(2026, 2, 2, tzinfo=UTC)
PROTOCOL = "fixture cautious visual survey v1"


def source(client: TestClient, project: str, index: int) -> dict[str, Any]:
    row = import_one(
        client, project, size=(32 + index, 48), relative_path=f"generated/{index}.png"
    )["successful"][0]
    image = successful(client.get(f"/api/v1/images/{row['image_id']}"))
    return {"kind": "image", "id": row["image_id"], "sha256": image["sha256"]}


def organism(client: TestClient, base: str, index: int) -> dict[str, Any]:
    return successful(
        client.post(
            base + "/ecology/organisms",
            json={
                "organism_key": f"synthetic-colony-{index}",
                "kind": "colony",
                "experimental_unit_type": "tank",
                "experimental_unit_id": f"tank-{index}",
                "reason": "Declared generated control unit",
            },
        ),
        201,
    )


def proposal_body(identity: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "identity_revision_id": identity["id"],
        "scientific_name": "Plexaura homomalla",
        "rank": "species",
        "source": evidence,
        "reason": "Synthetic label to exercise local attribution",
    }


def test_taxon_proposal_needs_separate_attributed_revision(client: TestClient) -> None:
    project, _, roles = role_fixture(client)
    base = f"/api/v1/projects/{project}"
    endpoint = base + "/taxonomy/proposals"
    actor, actor_key = roles["Reviewer A"]
    reviewer, reviewer_key = roles["Reviewer B"]
    body = proposal_body(organism(client, base, 1), source(client, project, 1))
    assert client.post(endpoint, json=body).status_code == 401
    proposal = successful(client.post(endpoint, json=body, headers=actor_key), 201)
    assert proposal["state"] == "proposed"
    assert proposal["proposal"]["author"]["role_revision_id"] == actor["id"]
    reviews = endpoint + "/" + proposal["id"] + "/reviews"
    review_body = {
        "expected_revision": 0,
        "decision": "confirmed",
        "reason": "Reviewed pinned source independently",
    }
    assert client.post(reviews, json=review_body, headers=actor_key).status_code == 403
    accepted = successful(client.post(reviews, json=review_body, headers=reviewer_key), 201)
    assert accepted["review"]["reviewer"]["role_revision_id"] == reviewer["id"]
    assert accepted["review"]["reviewer"]["name"] == "Reviewer B"
    assert reviewer_key["Authorization"] not in str(accepted)
    assert client.post(reviews, json=review_body, headers=reviewer_key).status_code == 409
    dismissed = {**review_body, "expected_revision": 1, "decision": "dismissed"}
    successful(client.post(reviews, json=dismissed, headers=roles["Adjudicator"][1]), 201)
    history = successful(client.get(reviews))["items"]
    assert [row["review"]["decision"] for row in history] == ["confirmed", "dismissed"]
    after = successful(client.get(endpoint + "/" + proposal["id"]))
    assert after["state"] == "dismissed"
    assert (
        after["proposal_sha256"]
        == proposal["proposal_sha256"]
        == canonical_json_sha256(proposal["proposal"])
    )


def test_detectability_uses_repeated_known_positive_groups_and_excludes_gaps(
    client: TestClient,
) -> None:
    project, _, roles = role_fixture(client)
    base = f"/api/v1/projects/{project}"
    endpoint = base + "/taxonomy"
    author = roles["Manager"][1]
    reviewer = roles["Reviewer B"][1]
    assessment_request = {
        "scientific_name": "Plexaura homomalla",
        "rank": "species",
        "protocol": PROTOCOL,
        "unit_type": "tank",
        "minimum_effort_seconds": 5,
        "window_start": START.isoformat(),
        "window_end": (START + timedelta(hours=3)).isoformat(),
    }
    withheld = successful(client.post(endpoint + "/assessments", json=assessment_request), 201)
    assert withheld["result"]["estimate"] is None
    assert withheld["result"]["status"] == "withheld"

    for group in range(5):
        prop = successful(
            client.post(
                endpoint + "/proposals",
                json=proposal_body(
                    organism(client, base, group), source(client, project, group + 70)
                ),
                headers=author,
            ),
            201,
        )
        successful(
            client.post(
                f"{endpoint}/proposals/{prop['id']}/reviews",
                headers=reviewer,
                json={
                    "expected_revision": 0,
                    "decision": "confirmed",
                    "reason": "Separate fixture review",
                },
            ),
            201,
        )
        for repeat in range(2):
            index = 8 * group + repeat
            visit = successful(
                client.post(
                    endpoint + "/visits",
                    headers=author,
                    json={
                        "proposal_id": prop["id"],
                        "protocol": PROTOCOL,
                        "started_at": (START + timedelta(minutes=index)).isoformat(),
                        "effort_seconds": 6,
                        "outcome": "not_detected" if (group == 0 or repeat == 1) else "detected",
                        "source": source(client, project, index + 1),
                        "notes": "Full fixture protocol reviewed by observation author",
                    },
                ),
                201,
            )
            presence = {
                "expected_revision": 0,
                "decision": "confirmed",
                "source": source(client, project, index + 100),
                "reason": "Known presence independently attested by separate fixture source",
            }
            pres_url = f"{endpoint}/visits/{visit['id']}/presence-reviews"
            assert client.post(pres_url, json=presence, headers=author).status_code == 403
            successful(client.post(pres_url, json=presence, headers=reviewer), 201)
    successful(
        client.post(
            endpoint + "/visits",
            headers=author,
            json={
                "proposal_id": prop["id"],
                "protocol": PROTOCOL,
                "started_at": (START + timedelta(hours=1)).isoformat(),
                "effort_seconds": 0,
                "outcome": "unobserved",
                "notes": "No observation obtained",
            },
        ),
        201,
    )

    saved = successful(client.post(endpoint + "/assessments", json=assessment_request), 201)
    result = saved["result"]
    assert result["status"] == "estimated"
    assert result["estimate"] == pytest.approx(0.4)
    assert result["independent_groups"] == 5
    assert result["eligible_visits"] == 10
    assert result["observed_nondetections"] == 6
    assert result["total_recorded_visits"] == 11
    assert result["included_effort_seconds"] == 60
    assert [row["reason"] for row in result["exclusions"]] == ["unobserved"]
    assert result["confidence_interval"]["level"] == 0.95
    assert result["confidence_interval"]["lower"] < 0.4 < result["confidence_interval"]["upper"]
    assert canonical_json_sha256(result) == saved["result_sha256"]
    replay = successful(client.post(endpoint + "/assessments", json=assessment_request), 201)
    assert replay == saved
    export = client.get(f"{endpoint}/assessments/{saved['id']}/export")
    assert export.status_code == 200
    assert export.json() == saved
    assert "attachment" in export.headers["Content-Disposition"]

    prior = result["visits"][0]
    duplicated = successful(
        client.post(
            endpoint + "/visits",
            headers=author,
            json={
                "proposal_id": prior["proposal"]["id"],
                "protocol": PROTOCOL,
                "started_at": (START + timedelta(minutes=90)).isoformat(),
                "effort_seconds": 6,
                "outcome": "detected",
                "source": prior["visit"]["source"],
                "notes": "Reuses existing bytes",
            },
        ),
        201,
    )
    presence_url = f"{endpoint}/visits/{duplicated['id']}/presence-reviews"
    presence_body = {
        "expected_revision": 0,
        "decision": "confirmed",
        "source": prior["visit"]["source"],
        "reason": "Intentionally incompatible same-source evidence",
    }
    assert client.post(presence_url, headers=reviewer, json=presence_body).status_code == 409
    successful(
        client.post(
            presence_url,
            headers=reviewer,
            json={
                **presence_body,
                "source": source(client, project, 250),
                "reason": "Separate media does not make the observed visit original",
            },
        ),
        201,
    )
    new = successful(client.post(endpoint + "/assessments", json=assessment_request), 201)
    assert new["id"] != saved["id"]
    assert new["result"]["estimate"] is None
    assert new["result"]["independent_groups"] == 4
    assert [row["reason"] for row in new["result"]["exclusions"]].count("reused_source_bytes") == 2
    assert successful(client.get(f"{endpoint}/assessments/{saved['id']}")) == saved


def test_competing_taxon_decisions_preserve_one_initial_revision(client: TestClient) -> None:
    project, _, roles = role_fixture(client)
    base = f"/api/v1/projects/{project}"
    endpoint = base + "/taxonomy/proposals"
    proposal = successful(
        client.post(
            endpoint,
            json=proposal_body(organism(client, base, 1), source(client, project, 1)),
            headers=roles["Manager"][1],
        ),
        201,
    )
    path = endpoint + "/" + proposal["id"] + "/reviews"

    def decide(name: str, choice: str) -> int:
        return client.post(
            path,
            headers=roles[name][1],
            json={
                "decision": choice,
                "expected_revision": 0,
                "reason": "Synthetic concurrent local decision",
            },
        ).status_code

    with ThreadPoolExecutor(2) as executor:
        confirmed = executor.submit(decide, "Reviewer A", "confirmed")
        unresolved = executor.submit(decide, "Reviewer B", "unresolved")
        assert sorted([confirmed.result(), unresolved.result()]) == [201, 409]
    history = successful(client.get(path))
    assert len(history["items"]) == 1 and history["items"][0]["revision"] == 1


def test_saved_detectability_replays_same_cached_payload_twice(client: TestClient) -> None:
    from reefvision.jobs.workflow import process_workflow_run_job
    from reefvision.tests.test_workflow_execution_phase10 import _queue_run, _save_graph

    project, _, _ = role_fixture(client)
    root = f"/api/v1/projects/{project}"
    result = successful(
        client.post(
            root + "/taxonomy/assessments",
            json={
                "scientific_name": "Plexaura homomalla",
                "rank": "species",
                "protocol": PROTOCOL,
                "unit_type": "tank",
                "minimum_effort_seconds": 5,
                "window_start": START.isoformat(),
                "window_end": (START + timedelta(hours=3)).isoformat(),
            },
        ),
        201,
    )
    graph = {
        "graph_id": "repeat-known-positive-assessment",
        "name": "Repeat known-positive assessment",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "detectability",
                "node_type": "detectability_assessment",
                "parameters": {
                    "assessment_id": result["id"],
                    "assessment_sha256": result["result_sha256"],
                },
            },
        ],
        "edges": [
            {
                "edge_id": "project-detectability",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "detectability",
                "target_port_id": "project",
            }
        ],
    }
    saved = _save_graph(client, project, graph)
    state = client.app.state
    evidence_hashes = set()
    for _ in range(2):
        queued = _queue_run(client, project, saved["id"])
        job_id, run_id = str(queued["job_id"]), str(queued["id"])
        assert process_workflow_run_job(state.settings, state.session_factory, job_id)
        detail = successful(client.get("/api/v1/workflow-runs/" + run_id))
        [artifact] = [
            a for a in detail["artifacts"] if a["data_type"] == "detectability_assessment"
        ]
        assert artifact["payload_json"] == result
        evidence_hashes.add(artifact["payload_sha256"])
    assert evidence_hashes == {canonical_json_sha256(result)}
