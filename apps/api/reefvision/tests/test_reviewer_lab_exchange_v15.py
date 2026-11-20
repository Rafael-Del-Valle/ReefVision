"""Exercise Reviewer Lab archive authenticity and restored local-role continuity."""

from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from typing import Any, cast
from uuid import uuid4
from zipfile import ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.reviewer_lab_v15 import reviewer_lab_report_sha256
from reefvision.tests.test_annotations import import_one
from reefvision.tests.test_reviewer_lab_v15 import judgement, make_round, role_fixture, successful
from reefvision.tests.test_scientific_project_exchange import (
    export_archive,
    import_archive,
    rewrite,
)


def _review_fixture(client: TestClient) -> dict[str, Any]:
    project, lab, roles = role_fixture(client)
    import_one(client, project)
    queued = successful(client.post(f"/api/v1/projects/{project}/review-queues", json={}), 201)
    queue_item = successful(client.get(f"/api/v1/review-queues/{queued['id']}/items"))["items"][0]
    sealed = make_round(client, lab, roles, [{"type": "queue_item", "id": queue_item["id"]}])
    open_ = make_round(client, lab, roles, [{"type": "queue_item", "id": queue_item["id"]}])
    manager = roles["Manager"][1]
    for plan in (sealed, open_):
        endpoint = f"{lab}/rounds/{plan['id']}/subjects/{plan['subjects'][0]['id']}"
        first = successful(
            client.post(
                f"{endpoint}/decision",
                json=judgement(plan, "usable", project),
                headers=roles["Reviewer A"][1],
            ),
            201,
        )
        if plan is not sealed:
            continue
        second = successful(
            client.post(
                f"{endpoint}/decision",
                json=judgement(plan, "unusable", "Separate original judgement"),
                headers=roles["Reviewer B"][1],
            ),
            201,
        )
        successful(
            client.post(
                f"{endpoint}/adjudication",
                json=judgement(
                    plan,
                    "uncertain",
                    "Original adjudication",
                    decision_ids=[first["id"], second["id"]],
                ),
                headers=roles["Adjudicator"][1],
            ),
            201,
        )
    report = successful(client.post(f"{lab}/rounds/{sealed['id']}/seal", headers=manager), 201)
    graph = {
        "graph_id": "reviewer-lab-exchange-fixture",
        "name": "Pinned original agreement",
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
                "edge_id": "link",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "agreement",
                "target_port_id": "project",
            }
        ],
    }
    graph_id = successful(
        client.post(
            f"/api/v1/projects/{project}/workflow-graphs",
            json={"graph": graph},
        ),
        201,
    )["id"]
    _replay(client, project, graph_id, report)
    return {
        "project": project,
        "lab": lab,
        "open": open_,
        "report": report,
        "roles": roles,
        "graph_id": graph_id,
    }


def _replay(client: TestClient, project: str, graph_id: str, report: dict[str, Any]) -> str:
    app = cast(FastAPI, client.app)
    queued = successful(
        client.post(
            f"/api/v1/projects/{project}/workflow-runs",
            json={"graph_record_id": graph_id},
        ),
        202,
    )
    assert process_workflow_run_job(app.state.settings, app.state.session_factory, queued["job_id"])
    detail = successful(client.get(f"/api/v1/workflow-runs/{queued['id']}"))
    assert detail["run"]["status"] == "succeeded", detail
    (matching,) = [
        a for a in detail["artifacts"] if a["data_type"] == "reviewer_lab_agreement_report"
    ]
    assert matching["payload_json"] == report
    return str(matching["payload_sha256"])


def _key() -> str:
    return sha256(str(uuid4()).encode()).hexdigest()


def _new_manager(client: TestClient, lab: str, name: str) -> dict[str, str]:
    key = _key()
    successful(
        client.post(
            f"{lab}/initialize",
            json={"name": name},
            headers={"X-ReefVision-Role-Key": key},
        ),
        201,
    )
    return {"Authorization": f"Bearer {key}"}


def _reissue(client: TestClient, lab: str, manager: dict[str, str], name: str) -> dict[str, str]:
    roster = client.get(f"{lab}/roles", headers=manager)
    assert roster.status_code == 200, roster.text
    role = next(row for row in roster.json() if row["name"] == name)
    key = _key()
    assert not role["active"]
    result = successful(
        client.post(
            f"{lab}/roles/{role['member_id']}/revisions",
            json={"base_revision_id": role["id"], "active": True},
            headers={**manager, "X-ReefVision-Role-Key": key},
        ),
        201,
    )
    assert result["revision"] == role["revision"] + 1
    return {"Authorization": f"Bearer {key}"}


def _assert_no_keys(raw: bytes, headers: list[dict[str, str]]) -> None:
    with ZipFile(BytesIO(raw)) as archive:
        assert not any("reviewer_lab_credentials" in name for name in archive.namelist())
        values = [
            archive.read(name) for name in archive.namelist() if name.endswith((".json", ".jsonl"))
        ]
        for authorization in headers:
            key = authorization["Authorization"].removeprefix("Bearer ")
            fingerprint = sha256(key.encode()).hexdigest()
            if any(key.encode() in value or fingerprint.encode() in value for value in values):
                raise AssertionError("Archive contained local Reviewer Lab authentication material")


def test_original_agreement_survives_two_copies_and_open_round_resumes(
    client: TestClient,
    test_settings: Settings,
) -> None:
    source = _review_fixture(client)
    old = source["project"]
    report = source["report"]
    old_headers = [row[1] for row in source["roles"].values()]
    first_archive = export_archive(client, test_settings, old)
    _assert_no_keys(first_archive, old_headers)
    first = successful(import_archive(client, first_archive), 201)
    live_first = first["project_id"]
    mapping = first["package"]["options_json"]["id_map"]
    lab = f"/api/v1/projects/{live_first}/reviewer-lab"
    assert not successful(client.get(f"{lab}/status"))["initialized"]
    for hdr in old_headers:
        assert client.get(f"{lab}/session", headers=hdr).status_code == 401
    duplicate = client.post(
        f"{lab}/initialize",
        json={"name": "Manager"},
        headers={"X-ReefVision-Role-Key": _key()},
    )
    assert duplicate.status_code == 409
    assert "distinct local manager name" in duplicate.json()["detail"]
    manager = _new_manager(client, lab, "First copy manager")
    second_reviewer = _reissue(client, lab, manager, "Reviewer B")
    copied_open = mapping[source["open"]["id"]]
    copied_subject = mapping[source["open"]["subjects"][0]["id"]]
    fresh_round = successful(client.get(f"{lab}/rounds/{copied_open}", headers=second_reviewer))
    assert fresh_round["subjects"][0]["id"] == copied_subject
    assert fresh_round["plan_sha256"] == source["open"]["plan_sha256"]
    assert fresh_round["subjects"][0]["image_id"] != source["open"]["subjects"][0]["image_id"]
    assert old not in str(fresh_round)  # First review used the original project UUID as its reason.
    endpoint = f"{lab}/rounds/{copied_open}/subjects/{copied_subject}"
    media = client.get(f"{endpoint}/image", headers=second_reviewer)
    assert media.status_code == 200
    assert sha256(media.content).hexdigest() == fresh_round["subjects"][0]["source_sha256"]
    successful(
        client.post(
            f"{endpoint}/decision",
            headers=second_reviewer,
            json=judgement(fresh_round, "unusable", "First-copy decision"),
        ),
        201,
    )
    assert successful(client.get(f"{lab}/reports/{mapping[report['id']]}/export")) == report
    first_hash = _replay(client, live_first, mapping[source["graph_id"]], report)
    second_archive = export_archive(client, test_settings, live_first)
    _assert_no_keys(second_archive, [*old_headers, manager, second_reviewer])
    twice = successful(import_archive(client, second_archive), 201)
    live_second = twice["project_id"]
    alias = twice["package"]["options_json"]["origin_id_map"]
    assert len({old, live_first, live_second}) == 3
    lab = f"/api/v1/projects/{live_second}/reviewer-lab"
    assert client.get(f"{lab}/session", headers=second_reviewer).status_code == 401
    manager_two = _new_manager(client, lab, "Second copy manager")
    adjudicator = _reissue(client, lab, manager_two, "Adjudicator")
    live_round = alias[source["open"]["id"]]
    open_view = successful(client.get(f"{lab}/rounds/{live_round}", headers=adjudicator))
    subject = open_view["subjects"][0]
    assert subject["id"] == alias[source["open"]["subjects"][0]["id"]]
    pair = subject["paired_decisions"]
    assert [d["reason"] for d in pair] == [old, "First-copy decision"]
    successful(
        client.post(
            f"{lab}/rounds/{live_round}/subjects/{subject['id']}/adjudication",
            headers=adjudicator,
            json=judgement(
                open_view,
                "uncertain",
                "Second-copy adjudication",
                decision_ids=[r["id"] for r in pair],
            ),
        ),
        201,
    )
    continued = successful(client.post(f"{lab}/rounds/{live_round}/seal", headers=manager_two), 201)
    assert continued["agreement"]["disagreements"] == 1
    assert continued["agreement"]["adjudicated_disagreements"] == 1
    assert continued["plan_sha256"] == source["open"]["plan_sha256"]
    assert successful(client.get(f"{lab}/reports/{alias[report['id']]}/export")) == report
    assert _replay(client, live_second, alias[source["graph_id"]], report) == first_hash
    third_archive = export_archive(client, test_settings, live_second)
    inspected = client.post(
        "/api/v1/exchange-packages/inspect",
        files={"file": ("continued.zip", third_archive, "application/zip")},
    )
    inspection = successful(inspected)
    assert inspection["compatible"], inspection["errors"]

    def change_queue(_: dict[str, Any], sections: dict[str, list[dict[str, Any]]]) -> None:
        (item,) = sections["review_queue_items"]
        item["score"] += 0.25

    damaged_queue = rewrite(third_archive, change_queue)
    before = client.get("/api/v1/projects").json()
    rejected = import_archive(client, damaged_queue)
    assert rejected.status_code == 400
    assert "differs from its pinned queue item" in rejected.json()["detail"]
    assert client.get("/api/v1/projects").json() == before


def test_rehashed_agreement_tampering_fails_before_project_mutation(
    client: TestClient,
    test_settings: Settings,
) -> None:
    source = _review_fixture(client)
    archive = export_archive(client, test_settings, source["project"])

    def forge(_: dict[str, Any], sections: dict[str, list[dict[str, Any]]]) -> None:
        (original,) = sections["reviewer_lab_reports"]
        body = deepcopy(original["content_json"])
        body["agreement"]["agreements"] = 1
        original["content_json"] = body
        original["content_sha256"] = reviewer_lab_report_sha256(body)

    damaged = rewrite(archive, forge)
    before = client.get("/api/v1/projects").json()
    inspected = client.post(
        "/api/v1/exchange-packages/inspect",
        files={"file": ("tampered.zip", damaged, "application/zip")},
    )
    inspection = successful(inspected)
    assert not inspection["compatible"]
    assert any("agreement does not match" in message for message in inspection["errors"])
    assert import_archive(client, damaged).status_code == 400
    assert client.get("/api/v1/projects").json() == before
