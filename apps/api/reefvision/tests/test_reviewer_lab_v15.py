from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from typing import Any, cast
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project, import_one


def successful(response: Any, status: int = 200) -> dict[str, Any]:
    assert response.status_code == status, response.text
    return cast(dict[str, Any], response.json())


RoleFixtures = dict[str, tuple[dict[str, Any], dict[str, str]]]


def role_fixture(
    client: TestClient,
    project_id: str | None = None,
) -> tuple[str, str, RoleFixtures]:
    if project_id is None:
        project_id = create_project(client, "Independent acquisition review")["id"]
    lab = f"/api/v1/projects/{project_id}/reviewer-lab"
    roles: RoleFixtures = {}
    for name, kind in (
        ("Manager", "manager"),
        ("Reviewer A", "reviewer"),
        ("Reviewer B", "reviewer"),
        ("Adjudicator", "adjudicator"),
        ("Unassigned", "reviewer"),
    ):
        key = sha256(str(uuid4()).encode()).hexdigest()
        body = {"name": name}
        if kind == "manager":
            result = client.post(
                f"{lab}/initialize", json=body, headers={"X-ReefVision-Role-Key": key}
            )
        else:
            result = client.post(
                f"{lab}/roles",
                json={**body, "role": kind},
                headers={**roles["Manager"][1], "X-ReefVision-Role-Key": key},
            )
        assert key not in result.text
        roles[name] = (successful(result, 201), {"Authorization": f"Bearer {key}"})
    return project_id, lab, roles


def make_round(
    client: TestClient, lab: str, roles: RoleFixtures, subjects: list[dict[str, str]]
) -> dict[str, Any]:
    return successful(
        client.post(
            f"{lab}/rounds",
            headers=roles["Manager"][1],
            json={
                "operation_id": str(uuid4()),
                "title": "Blinded source suitability",
                "criterion": "Decide whether the source is suitable for the declared method.",
                "reviewer_member_ids": [
                    roles[name][0]["member_id"] for name in ("Reviewer A", "Reviewer B")
                ],
                "adjudicator_member_id": roles["Adjudicator"][0]["member_id"],
                "sources": subjects,
            },
        ),
        201,
    )


def judgement(plan: dict[str, Any], value: str, reason: str, **extra: Any) -> dict[str, Any]:
    return {
        "operation_id": str(uuid4()),
        "plan_sha256": plan["plan_sha256"],
        "value": value,
        "reason": reason,
        **extra,
    }


def test_independent_blinding_adjudication_and_replayed_report(client: TestClient) -> None:
    project_id, lab, roles = role_fixture(client)
    image = import_one(client, project_id)["successful"][0]["image_id"]
    queue = successful(client.post(f"/api/v1/projects/{project_id}/review-queues", json={}), 201)
    queue_item = successful(client.get(f"/api/v1/review-queues/{queue['id']}/items"))["items"][0]
    other = import_one(client, project_id, size=(90, 60))["successful"][0]["image_id"]
    plan = make_round(
        client,
        lab,
        roles,
        [
            {"type": "queue_item", "id": queue_item["id"]},
            {"type": "image", "id": other},
        ],
    )
    assert plan["subjects"][0]["image_id"] == image
    round_url = f"{lab}/rounds/{plan['id']}"
    _, manager = roles["Manager"]
    _, first = roles["Reviewer A"]
    _, second = roles["Reviewer B"]
    _, adjudicator = roles["Adjudicator"]
    _, outsider = roles["Unassigned"]
    assert client.get(round_url).status_code == 401
    assert client.get(round_url, headers=outsider).status_code == 404
    subject = plan["subjects"][0]["id"]
    endpoint = f"{round_url}/subjects/{subject}"
    assert (
        sha256(client.get(f"{endpoint}/image", headers=first).content).hexdigest()
        == plan["subjects"][0]["source_sha256"]
    )
    assert client.get(f"{endpoint}/image", headers=outsider).status_code == 404
    secret_reason = "First independent reading only"
    first_body = judgement(plan, "usable", secret_reason)
    first_decision = successful(
        client.post(f"{endpoint}/decision", json=first_body, headers=first), 201
    )
    assert (
        successful(client.post(f"{endpoint}/decision", json=first_body, headers=first), 201)
        == first_decision
    )
    assert (
        client.post(
            f"{endpoint}/decision", json={**first_body, "reason": "changed"}, headers=first
        ).status_code
        == 409
    )
    assert client.get(round_url, headers=manager).status_code == 200
    for headers in (second, adjudicator, manager):
        blinded = client.get(round_url, headers=headers)
        assert secret_reason not in blinded.text
        assert first_decision["id"] not in blinded.text
    assert client.post(f"{round_url}/seal", headers=manager).status_code == 409
    second_decision = successful(
        client.post(
            f"{endpoint}/decision",
            json=judgement(plan, "unusable", "Separate finding"),
            headers=second,
        ),
        201,
    )
    assert secret_reason not in client.get(round_url, headers=second).text
    assert secret_reason in client.get(round_url, headers=adjudicator).text
    resolution = judgement(
        plan,
        "uncertain",
        "Adjudicated without changing independent inputs",
        decision_ids=[first_decision["id"], second_decision["id"]],
    )
    assert (
        client.post(f"{endpoint}/adjudication", json=resolution, headers=first).status_code == 403
    )
    assert (
        client.post(
            f"{endpoint}/adjudication",
            json={**resolution, "decision_ids": [first_decision["id"], str(uuid4())]},
            headers=adjudicator,
        ).status_code
        == 409
    )
    successful(client.post(f"{endpoint}/adjudication", json=resolution, headers=adjudicator), 201)

    companion = f"{round_url}/subjects/{plan['subjects'][1]['id']}/decision"
    for headers in (first, second):
        successful(
            client.post(
                companion, json=judgement(plan, "usable", "Independent agreement"), headers=headers
            ),
            201,
        )
    report = successful(client.post(f"{round_url}/seal", headers=manager), 201)
    metrics = report["agreement"]
    assert (
        metrics["planned_subjects"],
        metrics["paired_subjects"],
        metrics["agreements"],
        metrics["disagreements"],
        metrics["adjudicated_disagreements"],
    ) == (2, 2, 1, 1, 1)
    assert metrics["observed_agreement"] == 0.5 and metrics["cohens_kappa"] == 0.0
    assert report["authority"] == "local_attribution"
    assert report["subjects"][0]["source"]["queue_input_sha256"] == queue_item["input_checksum"]
    assert report["subjects"][0]["first"]["id"] == first_decision["id"]
    assert report["subjects"][0]["resolution"]["value"] == "uncertain"
    assert successful(client.post(f"{round_url}/seal", headers=manager), 201) == report
    exported = client.get(f"{lab}/reports/{report['id']}/export")
    assert successful(exported) == report
    assert "attachment" in exported.headers["content-disposition"]
    assert exported.headers["x-reefvision-content-sha256"] == report["content_sha256"]
    assert successful(client.get(f"{lab}/reports/{report['id']}")) == report

    graph = {
        "name": "Pinned local reviewer agreement",
        "graph_id": "reviewer-lab-test",
        "nodes": [
            {
                "node_id": "project",
                "node_type": "project_source",
                "name": "Project",
                "parameters": {},
            },
            {
                "node_id": "agreement",
                "node_type": "reviewer_lab_agreement_report",
                "name": "Agreement",
                "parameters": {"report_id": report["id"]},
            },
        ],
        "edges": [
            {
                "edge_id": "project-agreement",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "agreement",
                "target_port_id": "project",
            }
        ],
    }
    project = f"/api/v1/projects/{project_id}"
    saved = successful(client.post(f"{project}/workflow-graphs", json={"graph": graph}), 201)
    replay_hashes = []
    app = cast(FastAPI, client.app)
    for _ in range(2):
        queued = successful(
            client.post(f"{project}/workflow-runs", json={"graph_record_id": saved["id"]}), 202
        )
        process_workflow_run_job(app.state.settings, app.state.session_factory, queued["job_id"])
        run = successful(client.get(f"/api/v1/workflow-runs/{queued['id']}"))
        assert run["run"]["status"] == "succeeded", run
        (result,) = [
            row for row in run["artifacts"] if row["data_type"] == "reviewer_lab_agreement_report"
        ]
        assert result["payload_json"] == report
        replay_hashes.append(result["payload_sha256"])
    assert replay_hashes[0] == replay_hashes[1]


def test_stale_plan_role_and_concurrent_idempotency(client: TestClient) -> None:
    project_id, lab, roles = role_fixture(client)
    image = import_one(client, project_id)["successful"][0]["image_id"]
    old, reviewer = roles["Reviewer A"]
    manager = roles["Manager"][1]
    duplicate = roles["Reviewer B"][0]["member_id"]
    assert (
        client.post(
            f"{lab}/rounds",
            headers=manager,
            json={
                "operation_id": str(uuid4()),
                "title": "Invalid round",
                "criterion": "Separate observations",
                "reviewer_member_ids": [duplicate, duplicate],
                "adjudicator_member_id": duplicate,
                "sources": [{"type": "image", "id": image}],
            },
        ).status_code
        == 422
    )

    plan = make_round(client, lab, roles, [{"type": "image", "id": image}])
    endpoint = f"{lab}/rounds/{plan['id']}/subjects/{plan['subjects'][0]['id']}/decision"
    first = judgement(plan, "usable", "Idempotent one-time submission")
    assert (
        client.post(endpoint, json={**first, "plan_sha256": "0" * 64}, headers=reviewer).status_code
        == 409
    )
    with ThreadPoolExecutor(max_workers=2) as concurrent:
        responses = list(
            concurrent.map(lambda _: client.post(endpoint, json=first, headers=reviewer), range(2))
        )
    assert all(result.status_code == 201 for result in responses), [
        result.text for result in responses
    ]
    assert responses[0].json() == responses[1].json()
    replacement = sha256(str(uuid4()).encode()).hexdigest()
    revision_url = f"{lab}/roles/{old['member_id']}/revisions"
    rotated = successful(
        client.post(
            revision_url,
            headers={**manager, "X-ReefVision-Role-Key": replacement},
            json={
                "base_revision_id": old["id"],
                "active": True,
            },
        ),
        201,
    )
    assert rotated["revision"] == 2 and rotated["previous_revision_id"] == old["id"]
    assert client.get(f"{lab}/session", headers=reviewer).status_code == 401
    assert (
        client.post(
            revision_url,
            headers=manager,
            json={
                "base_revision_id": old["id"],
                "active": False,
            },
        ).status_code
        == 409
    )
    assert (
        client.get(f"{lab}/session", headers={"Authorization": f"Bearer {replacement}"}).status_code
        == 200
    )

    assert (
        client.put(
            f"/api/v1/images/{image}/annotations",
            json={
                "base_revision": 0,
                "annotation_status": "reviewed",
                "annotations": [],
            },
        ).status_code
        == 200
    )
    second = roles["Reviewer B"][1]
    assert (
        client.post(
            endpoint, json=judgement(plan, "usable", "Stale source"), headers=second
        ).status_code
        == 409
    )
