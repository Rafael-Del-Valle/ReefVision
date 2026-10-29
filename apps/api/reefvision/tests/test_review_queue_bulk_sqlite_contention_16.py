"""Real SQLite writer contention must not partially apply manual QC triage.

Exercise both standalone queues and queues produced by a persisted, executable
Workflow Builder graph. All database files are disposable pytest fixtures.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.review_queue_bulk import _is_sqlite_writer_contention
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_workflow_review_queue_16 import _graph


def _make_queue(client: TestClient, *, saved_workflow: bool) -> tuple[str, list[str]]:
    project = create_project(client, "SQLite reviewer contention")
    project_id = project["id"]
    for index in range(2):
        imported = import_one(
            client,
            project_id,
            filename=f"coral-{index}.png",
            relative_path=f"review/coral-{index}.png",
            size=(80 + index, 60),
        )
        assert len(imported["successful"]) == 1

    if saved_workflow:
        graph = _graph()
        plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
        assert plan.status_code == 200, plan.text
        assert plan.json()["valid"] and plan.json()["executable"]
        saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
        assert saved.status_code == 201, saved.text
        queued = client.post(
            f"/api/v1/projects/{project_id}/workflow-runs",
            json={"graph_record_id": saved.json()["id"]},
        )
        assert queued.status_code == 202, queued.text
        app = cast(FastAPI, client.app)
        assert process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
        )
        detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["run"]["status"] == "succeeded"
        artifacts = [
            item
            for item in detail.json()["artifacts"]
            if item["data_type"] == "review_queue_reference"
        ]
        assert len(artifacts) == 1
        payload = artifacts[0]["payload_json"]
        assert payload["priority_score_unit"] == "dimensionless"
        assert payload["review_status"] == "requires_researcher_review"
        queue_id = payload["queue_id"]
    else:
        created = client.post(f"/api/v1/projects/{project_id}/review-queues", json={})
        assert created.status_code == 201, created.text
        queue_id = created.json()["id"]

    items = client.get(f"/api/v1/review-queues/{queue_id}/items")
    assert items.status_code == 200, items.text
    ids = [item["id"] for item in items.json()["items"]]
    assert len(ids) == 2
    return queue_id, ids


@pytest.mark.parametrize("saved_workflow", [False, True])
@pytest.mark.parametrize("lock_mode", ["IMMEDIATE", "EXCLUSIVE"])
def test_sqlite_lock_fails_closed_then_same_bulk_request_retries(
    client: TestClient, saved_workflow: bool, lock_mode: str
) -> None:
    queue_id, item_ids = _make_queue(client, saved_workflow=saved_workflow)
    app = cast(FastAPI, client.app)
    db_path = make_url(app.state.settings.resolved_database_url).database
    assert db_path is not None and Path(db_path).is_file()

    payload = {
        "item_ids": item_ids,
        "action": "start",
        "actor": "local researcher",
        "client_request_id": str(uuid4()),
    }
    url = f"/api/v1/review-queues/{queue_id}/items/bulk"

    # BEGIN IMMEDIATE permits SELECT but reserves the writer slot. BEGIN
    # EXCLUSIVE also blocks the initial queue SELECT (before session.commit).
    # Neither path may report a 500, apply partial triage, or create an event.
    blocker = sqlite3.connect(db_path, timeout=0.2, isolation_level=None)
    try:
        blocker.execute("BEGIN IMMEDIATE" if lock_mode == "IMMEDIATE" else "BEGIN EXCLUSIVE")
        blocked = client.post(url, json=payload)
        assert blocked.status_code == 409, blocked.text
        assert "busy" in blocked.text.lower()
    finally:
        blocker.rollback()
        blocker.close()

    before = client.get(f"/api/v1/review-queues/{queue_id}/items")
    assert before.status_code == 200, before.text
    assert {item["review_state"] for item in before.json()["items"]} == {"pending"}
    for item_id in item_ids:
        events = client.get(f"/api/v1/review-queues/{queue_id}/items/{item_id}/events")
        assert events.status_code == 200, events.text
        assert events.json()["total"] == 0

    committed = client.post(url, json=payload)
    assert committed.status_code == 200, committed.text
    assert committed.json()["changed_count"] == 2
    assert committed.json()["requires_researcher_review"] is True
    replay = client.post(url, json=payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["changed_count"] == 0
    for item_id in item_ids:
        events = client.get(f"/api/v1/review-queues/{queue_id}/items/{item_id}/events")
        assert events.status_code == 200, events.text
        assert events.json()["total"] == 1
        assert events.json()["items"][0]["actor"] == "local researcher"
        assert events.json()["requires_researcher_review"] is True
        item = next(item for item in replay.json()["items"] if item["id"] == item_id)
        annotations = client.get(f"/api/v1/images/{item['image_id']}/annotations")
        assert annotations.status_code == 200, annotations.text
        assert annotations.json()["annotations"] == []


def test_sqlite_busy_classifier_does_not_mask_unrelated_database_errors() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        with pytest.raises(sqlite3.OperationalError) as missing:
            connection.execute("SELECT * FROM missing_research_table")
        assert not _is_sqlite_writer_contention(OperationalError("SELECT", {}, missing.value))
    finally:
        connection.close()
    assert not _is_sqlite_writer_contention(
        OperationalError("INSERT", {}, RuntimeError("unrelated database failure"))
    )
