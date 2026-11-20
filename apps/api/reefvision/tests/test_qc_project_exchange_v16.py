"""Audit history and request identity survive independent Project Exchange copies."""

from __future__ import annotations

import json
from io import BytesIO
from typing import cast
from uuid import UUID, uuid4
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.db.models import ReviewQueueItemEvent
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


def test_exchange_preserves_last_assignment_when_clocks_tie_and_ids_sort_backwards(
    client: TestClient, test_settings: Settings
) -> None:
    queue, items = _queue_with_two_images(client)
    project = client.get(f"/api/v1/review-queues/{queue}").json()["project_id"]
    path = f"/api/v1/review-queues/{queue}/items/{items[0]}/events"
    for kind in ("assign", "unassign"):
        response = client.post(
            path,
            json={
                "client_request_id": str(uuid4()),
                "actor": "curator",
                "event_type": kind,
                **({"assignee": "observer"} if kind == "assign" else {}),
            },
        )
        assert response.is_success, response.text
    history = client.get(path).json()["items"]
    with cast(FastAPI, client.app).state.session_factory() as session:
        first, last = (session.get(ReviewQueueItemEvent, entry["id"]) for entry in history)
        assert first is not None and last is not None
        first.id, last.id = str(UUID(int=2)), str(UUID(int=1))
        last.created_at = first.created_at
        session.commit()
    raw = export_archive(client, test_settings, project)
    for _ in range(2):
        with ZipFile(BytesIO(raw)) as archive:
            events = archive.read("records/review_queue_item_events.jsonl").splitlines()
            assert [json.loads(row)["event_type"] for row in events] == ["assign", "unassign"]
        result = import_archive(client, raw)
        assert result.is_success, result.text
        mapping = result.json()["package"]["options_json"]["origin_id_map"]
        copied = client.get(
            f"/api/v1/review-queues/{mapping[queue]}/items/{mapping[items[0]]}/events"
        )
        assert copied.json()["current_assignee"] is None
        assert [row["event_type"] for row in copied.json()["items"]] == ["assign", "unassign"]
        raw = export_archive(client, test_settings, mapping[project])


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


def test_frozen_qc_dataset_replays_after_two_generations_of_exchange(
    client: TestClient, test_settings: Settings
) -> None:
    from reefvision.tests.test_dataset_versions import create_version
    from reefvision.tests.test_workflow_review_queue_frozen_dataset_16 import (
        _frozen_graph,
        _run_frozen_graph,
        _study,
    )

    project, image, _, box = _study(client)
    mask = {
        "id": str(uuid4()),
        "label_class_id": box["label_class_id"],
        "geometry_kind": "polygon",
        "points": [{"x": 8, "y": 8}, {"x": 30, "y": 8}, {"x": 12, "y": 26}],
    }
    update = client.put(
        f"/api/v1/images/{image}/annotations",
        json={
            "base_revision": 1,
            "annotation_status": "reviewed",
            "annotations": [box],
            "mask_annotations": [mask],
        },
    )
    assert update.is_success, update.text
    version = create_version(client, project, name="Box and polygon at freeze")["id"]
    saved = client.post(
        f"/api/v1/projects/{project}/workflow-graphs", json={"graph": _frozen_graph(version)}
    )
    assert saved.is_success, saved.text
    graph = saved.json()["id"]
    _, source = _run_frozen_graph(client, project, graph)
    source_manifest = client.get(f"/api/v1/dataset-versions/{version}/manifest").json()
    raw = export_archive(client, test_settings, project)

    def damage(_, sections):
        item = next(
            i for i in sections["dataset_version_items"] if i["dataset_version_id"] == version
        )
        item["per_mask_class_counts_json"] = {str(uuid4()): 1}

    before = database_counts(client)
    rejected = import_archive(client, rewrite(raw, damage))
    assert rejected.status_code == 400, rejected.text
    assert database_counts(client) == before
    for _ in range(2):
        copied = import_archive(client, raw)
        assert copied.is_success, copied.text
        package = copied.json()["package"]["options_json"]
        mapping = package["origin_id_map"]
        copied_version = mapping[version]
        (item,) = client.get(f"/api/v1/dataset-versions/{copied_version}/items").json()
        counts = {mapping[box["label_class_id"]]: 1}
        assert item["per_class_counts_json"] == item["per_mask_class_counts_json"] == counts
        assert item["mask_annotation_snapshot_json"][0]["polygon_json"] == [
            [8, 8],
            [30, 8],
            [12, 26],
        ]
        first_run, first = _run_frozen_graph(client, mapping[project], mapping[graph])
        second_run, second = _run_frozen_graph(client, mapping[project], mapping[graph])
        assert first_run != second_run and first["queue_id"] != second["queue_id"]
        assert first["dataset_version_id"] == second["dataset_version_id"] == copied_version
        digest = first["dataset_manifest_sha256"]
        assert second["dataset_manifest_sha256"] == digest != source["dataset_manifest_sha256"]
        assert first["item_count"] == second["item_count"] == source["item_count"]
        raw = export_archive(client, test_settings, mapping[project])
    assert client.get(f"/api/v1/dataset-versions/{version}/manifest").json() == source_manifest
