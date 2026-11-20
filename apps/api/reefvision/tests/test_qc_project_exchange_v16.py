"""Audit history and request identity survive independent Project Exchange copies."""

from __future__ import annotations

import json
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.tests.test_review_queue_bulk_16 import _queue_with_two_images
from reefvision.tests.test_scientific_project_exchange import (
    MANIFEST,
    database_counts,
    export_archive,
    import_archive,
    rewrite,
)


def _reviewed_archive(client: TestClient, settings: Settings):
    queue, items = _queue_with_two_images(client)
    project = client.get(f"/api/v1/review-queues/{queue}").json()["project_id"]
    history = f"/api/v1/review-queues/{queue}/items/{items[0]}/events"
    note = {
        "client_request_id": str(uuid4()),
        "event_type": "comment",
        "actor": items[1],
        "comment": project,
    }
    assigned = {
        "client_request_id": str(uuid4()),
        "event_type": "assign",
        "actor": items[1],
        "assignee": queue,
    }
    for event in (assigned, note):
        response = client.post(history, json=event)
        assert response.is_success, response.text
    operation = str(uuid4())
    request = {
        "client_request_id": operation,
        "actor": project,
        "action": "skip",
        "reason": items[0],
        "item_ids": items,
    }
    response = client.post(f"/api/v1/review-queues/{queue}/items/bulk", json=request)
    assert response.is_success, response.text
    raw = export_archive(client, settings, project)
    with ZipFile(BytesIO(raw)) as archive:
        manifest = json.loads(archive.read(MANIFEST))
    assert manifest["format_version"] == "1.6"
    assert manifest["sections"]["review_queue_item_events"]["count"] == 4
    assert manifest["sections"]["review_queue_bulk_requests"]["count"] == 1
    return raw, project, queue, items, operation, request


def test_reimported_qc_preserves_history_free_text_and_retry_identity(
    client: TestClient, test_settings: Settings
) -> None:
    raw, project, queue, items, operation, request = _reviewed_archive(client, test_settings)
    copies = set()
    for index in range(2):
        result = import_archive(client, raw)
        assert result.is_success, result.text
        mapping = result.json()["package"]["options_json"]["origin_id_map"]
        local = mapping[project]
        assert local not in copies and local != project
        copies.add(local)
        new_queue = mapping[queue]
        url = f"/api/v1/review-queues/{new_queue}/items/{mapping[items[0]]}/events"
        page = client.get(url).json()
        assert page["current_assignee"] == queue
        assert [
            (e["actor"], e["comment"]) for e in page["items"] if e["event_type"] == "comment"
        ] == [(items[1], project)]
        retried = client.post(
            f"/api/v1/review-queues/{new_queue}/items/bulk",
            json={
                **request,
                "item_ids": [mapping[item] for item in items],
                "client_request_id": mapping[operation],
            },
        )
        assert retried.is_success, retried.text
        assert client.get(url).json()["total"] == 3
        if index == 0:
            raw = export_archive(client, test_settings, local)


@pytest.mark.parametrize(
    "damage", ["wrong item", "duplicate request", "missing event", "wrong action"]
)
def test_exchange_refuses_inconsistent_qc_before_creating_project(
    client: TestClient, test_settings: Settings, damage: str
) -> None:
    raw, _, _, items, _, _ = _reviewed_archive(client, test_settings)

    def change(_, sections):
        events = sections["review_queue_item_events"]
        bulk = sections["review_queue_bulk_requests"][0]
        if damage == "wrong item":
            bulk["item_ids_json"] = [str(uuid4()), items[1]]
        elif damage == "duplicate request":
            event = dict(events[0], id=str(uuid4()))
            events.append(event)
        elif damage == "missing event":
            events.remove(next(e for e in events if e["event_type"] == "triage_skip"))
        else:
            bulk["action"] = "return"

    before = database_counts(client)
    refused = import_archive(client, rewrite(raw, change))
    assert refused.status_code == 400, refused.text
    assert database_counts(client) == before


def test_saved_qc_owns_same_imported_queue_and_reruns_twice(
    client: TestClient, test_settings: Settings
) -> None:
    from reefvision.tests.test_paired_growth_contrast import _run_graph
    from reefvision.tests.test_workflow_review_queue_16 import _graph

    base_queue, _ = _queue_with_two_images(client)
    project = client.get(f"/api/v1/review-queues/{base_queue}").json()["project_id"]
    response = client.post(f"/api/v1/projects/{project}/workflow-graphs", json={"graph": _graph()})
    assert response.is_success, response.text
    graph = response.json()["id"]
    detail = _run_graph(client, project, graph)
    assert detail["run"]["status"] == "succeeded", detail
    [artifact] = [a for a in detail["artifacts"] if a["data_type"] == "review_queue_reference"]
    source = artifact["payload_json"]
    raw = export_archive(client, test_settings, project)
    for _ in range(2):
        result = import_archive(client, raw)
        assert result.is_success, result.text
        mapping = result.json()["package"]["options_json"]["origin_id_map"]
        imported = client.get(f"/api/v1/workflow-runs/{mapping[source['workflow_run_id']]}").json()
        [restored] = [
            a for a in imported["artifacts"] if a["data_type"] == "review_queue_reference"
        ]
        payload = restored["payload_json"]
        assert payload["queue_id"] == mapping[source["queue_id"]]
        bound = client.get(f"/api/v1/review-queues/{payload['queue_id']}").json()
        assert (
            bound["created_by"]
            == f"workflow:{payload['workflow_run_id']}:{payload['workflow_node_run_id']}"
        )
        assert bound["input_checksums_json"] == payload["input_checksums"]
        for attempt in range(2):
            replay = _run_graph(client, mapping[project], mapping[graph])
            assert replay["run"]["status"] == "succeeded", (attempt, replay)
            [live] = [a for a in replay["artifacts"] if a["data_type"] == "review_queue_reference"]
            assert live["payload_json"]["item_count"] == source["item_count"]
        raw = export_archive(client, test_settings, mapping[project])
