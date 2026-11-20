from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from reefvision.tests.test_annotations import create_project


def _site(client: TestClient, name: str, values: list[float], **parameters: Any) -> tuple[str, str]:
    project = create_project(client, name)["id"]
    base = f"/api/v1/projects/{project}"
    readings = [
        {
            "variable": "water_temperature",
            "value": value,
            "unit": "degC",
            "qc": "accepted",
            "source_kind": "observed",
            "observed_at": f"2026-11-19T13:0{i}:00Z",
            "provenance": {
                "source": name,
                "acquired_at": f"2026-11-19T13:0{i}:00Z",
                "source_metadata": {"protocol": "reef-minute"},
            },
        }
        for i, value in enumerate(values)
    ]
    samples = client.post(base + "/scientific-records", json={"records": readings})
    assert samples.is_success, samples.text
    rule = client.post(
        base + "/monitoring/rules",
        json={
            "kind": "environmental",
            "label": name,
            "protocol": "reef-minute",
            "metric": "water_temperature",
            "unit": "degC",
            "parameters": {"cadence_seconds": 60, "upper_limit": 21, **parameters},
        },
    )
    assert rule.status_code == 201, rule.text
    assessment = client.post(
        base + "/monitoring/assessments",
        json={
            "rule_id": rule.json()["id"],
            "rule_sha256": rule.json()["rule_sha256"],
            "window_start": "2026-11-19T13:00:00Z",
            "window_end": "2026-11-19T13:02:00Z",
        },
    )
    assert assessment.status_code == 201, assessment.text
    return project, assessment.json()["id"]


def _selections(*sites: tuple[str, str]) -> dict[str, Any]:
    return {"selections": [{"project_id": p, "assessment_id": a} for p, a in sites]}


def test_summary_requires_distinct_projects_and_the_owning_reference(client: TestClient) -> None:
    a = create_project(client, "Reference")["id"]
    endpoint = f"/api/v1/projects/{a}/monitoring/summaries"
    assert (
        client.post(endpoint, json=_selections((a, str(uuid4())), (a, str(uuid4())))).status_code
        == 422
    )
    foreign = str(uuid4())
    assert (
        client.post(
            endpoint, json=_selections((foreign, str(uuid4())), (a, str(uuid4())))
        ).status_code
        == 400
    )


def test_review_changes_create_new_comparisons_and_leave_the_old_export_unchanged(
    client: TestClient,
) -> None:
    reference = _site(client, "Tank A", [20, 20])
    other = _site(client, "Tank B", [20, 22])
    incompatible = _site(client, "Third protocol", [20, 20], upper_limit=23)
    endpoint = f"/api/v1/projects/{reference[0]}/monitoring/summaries"
    selected = _selections(reference, other, incompatible)
    before = client.post(endpoint, json=selected)
    assert before.status_code == 201, before.text
    original = before.json()
    a, b, c = original["snapshot"]["rows"]
    assert a["status"] == "included" and a["effort"]["accepted_observations"] == 2
    assert b["status"] == "excluded" and b["review"]["proposed"] == 1
    assert c["status"] == "excluded" and any("rule parameters" in reason for reason in c["reasons"])
    export = endpoint + "/" + original["id"] + "/export"
    old_export = client.get(export)
    assert old_export.json()["content_sha256"] == original["content_sha256"]
    peer = f"/api/v1/projects/{other[0]}/monitoring/alerts"
    alert = client.get(peer, params={"assessment_id": other[1]}).json()["items"][0]
    reviewed = client.post(
        f"{peer}/{alert['id']}/reviews",
        json={
            "decision": "confirmed",
            "expected_revision": 0,
            "reason": "Compared with the generated logger reference.",
        },
    )
    assert reviewed.is_success, reviewed.text
    refreshed = client.post(endpoint, json=selected).json()
    assert (
        refreshed["id"] != original["id"]
        and refreshed["content_sha256"] != original["content_sha256"]
    )
    assert client.post(endpoint, json=selected).json()["id"] == refreshed["id"]
    new_peer = refreshed["snapshot"]["rows"][1]
    assert (
        new_peer["project_id"] == other[0]
        and new_peer["status"] == "included"
        and new_peer["review"]["confirmed"] == 1
    )
    assert new_peer["review"]["alerts"][0]["latest_review"]["reviewer"]
    assert client.get(export).content == old_export.content
    assert client.get(endpoint, params={"limit": 1, "offset": 1}).json()["total"] == 2
    assert (
        client.get(f"/api/v1/projects/{other[0]}/monitoring/summaries/{original['id']}").status_code
        == 404
    )
    wrong = client.post(endpoint, json=_selections(reference, (other[0], reference[1])))
    assert wrong.status_code == 404, wrong.text
