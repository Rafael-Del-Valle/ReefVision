"""SQLite writer contention must not replace saved QC evidence or reviewer work."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError

from reefvision.db.models import ReviewQueue, WorkflowArtifact, WorkflowNodeRun
from reefvision.domain.errors import ValidationError
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.review_queues import ReviewQueueService
from reefvision.services.workflow_review_queue import (
    _is_sqlite_queue_identity_collision,
    _is_sqlite_writer_contention,
    create_review_queue_workflow_artifact,
)
from reefvision.tests.test_annotations import create_project, import_one


def test_sqlite_busy_is_distinguished_from_unrelated_database_errors(tmp_path: Path) -> None:
    database = tmp_path / "contention.db"
    writer = sqlite3.connect(database, isolation_level=None)
    competing = sqlite3.connect(database, timeout=0.05)
    try:
        writer.execute("CREATE TABLE queue_identity (id INTEGER PRIMARY KEY)")
        writer.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError) as busy:
            competing.execute("INSERT INTO queue_identity VALUES (1)")
        assert _is_sqlite_writer_contention(OperationalError("INSERT", {}, busy.value))

        with pytest.raises(sqlite3.OperationalError) as unrelated:
            competing.execute("SELECT * FROM missing_table")
        assert not _is_sqlite_writer_contention(OperationalError("SELECT", {}, unrelated.value))
    finally:
        writer.rollback()
        writer.close()
        competing.close()


def _sqlite_constraint_error(*, duplicate_id: bool) -> sqlite3.IntegrityError:
    """Use real SQLite extended error codes, not fabricated exception text."""
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE review_queues (id TEXT PRIMARY KEY, created_by TEXT UNIQUE)")
        db.execute("INSERT INTO review_queues VALUES ('first', 'researcher')")
        try:
            if duplicate_id:
                db.execute("INSERT INTO review_queues VALUES ('first', 'other')")
            else:
                db.execute("INSERT INTO review_queues VALUES ('second', 'researcher')")
        except sqlite3.IntegrityError as exc:
            return exc
    raise AssertionError("Expected a SQLite constraint failure")


def test_only_review_queue_primary_key_collision_is_retryable() -> None:
    identity_error = _sqlite_constraint_error(duplicate_id=True)
    unrelated_error = _sqlite_constraint_error(duplicate_id=False)
    assert identity_error.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY
    assert unrelated_error.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_UNIQUE
    assert _is_sqlite_queue_identity_collision(IntegrityError("INSERT", {}, identity_error))
    assert not _is_sqlite_queue_identity_collision(IntegrityError("INSERT", {}, unrelated_error))
    assert not _is_sqlite_queue_identity_collision(
        IntegrityError("INSERT", {}, RuntimeError("review_queues.id"))
    )


def test_saved_qc_workflow_retries_after_real_sqlite_writer_lock(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client, "SQLite QC contention regression")
    project_id = project["id"]
    imported = import_one(
        client,
        project_id,
        filename="qc-lock-swiftia.png",
        relative_path="qc/qc-lock-swiftia.png",
    )
    assert len(imported["successful"]) == 1

    # Independent manual review history must survive a failed workflow writer.
    standalone = client.post(f"/api/v1/projects/{project_id}/review-queues", json={})
    assert standalone.status_code == 201, standalone.text
    manual_id = standalone.json()["id"]
    manual_items = client.get(f"/api/v1/review-queues/{manual_id}/items")
    assert manual_items.status_code == 200
    item_id = manual_items.json()["items"][0]["id"]
    events_url = f"/api/v1/review-queues/{manual_id}/items/{item_id}/events"
    comment = client.post(
        events_url,
        json={
            "client_request_id": str(uuid4()),
            "event_type": "comment",
            "actor": "researcher",
            "comment": "Manual QC evidence is not workflow output",
        },
    )
    assert comment.status_code == 201, comment.text

    graph = {
        "graph_id": "qc-sqlite-lock-16",
        "name": "QC writer contention",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "qc", "node_type": "qc_review_queue"},
        ],
        "edges": [
            {
                "edge_id": "project-qc",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "qc",
                "target_port_id": "project",
            }
        ],
    }
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200 and plan.json()["valid"] and plan.json()["executable"]
    saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert queued.status_code == 202, queued.text
    run_id = queued.json()["id"]
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
    )

    # Synthetic interrupted-create fixture: remove only the workflow's own
    # generated queue and its output binding, never the standalone queue.
    with app.state.session_factory() as session:
        node = session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.workflow_run_id == run_id,
                WorkflowNodeRun.node_type == "qc_review_queue",
            )
        )
        source = session.scalar(
            select(WorkflowArtifact).where(
                WorkflowArtifact.workflow_run_id == run_id,
                WorkflowArtifact.data_type == "project_reference",
            )
        )
        assert node is not None and source is not None
        queue = session.scalar(
            select(ReviewQueue).where(
                ReviewQueue.project_id == project_id,
                ReviewQueue.created_by == f"workflow:{run_id}:{node.id}",
            )
        )
        assert queue is not None
        expected_id = queue.id
        params = {
            **dict(node.parameters_json or {}),
            "__workflow_run_id": run_id,
            "__workflow_node_run_id": node.id,
        }
        source_id = source.id
        node.output_artifact_ids_json = []
        session.delete(queue)
        session.commit()

    # A distinct SQLite UNIQUE violation must propagate; it is not a
    # competing writer for this workflow's deterministic queue identity.
    unrelated = IntegrityError("INSERT", {}, _sqlite_constraint_error(duplicate_id=False))

    def raise_unrelated_constraint(*_args: object, **_kwargs: object) -> None:
        raise unrelated

    with app.state.session_factory() as session:
        source = session.get(WorkflowArtifact, source_id)
        assert source is not None
        with monkeypatch.context() as patch:
            patch.setattr(
                ReviewQueueService,
                "create_queue_for_project",
                raise_unrelated_constraint,
            )
            with pytest.raises(IntegrityError, match=r"review_queues\.created_by"):
                create_review_queue_workflow_artifact(
                    session=session,
                    settings=app.state.settings,
                    project_id=project_id,
                    parameters=params,
                    inputs={"project": [source]},
                )

    database_path = app.state.engine.url.database
    assert database_path is not None
    blocker = sqlite3.connect(database_path, isolation_level=None, timeout=0.05)
    try:
        blocker.execute("BEGIN IMMEDIATE")
        with app.state.session_factory() as session:
            session.execute(text("PRAGMA busy_timeout = 75"))
            source = session.get(WorkflowArtifact, source_id)
            assert source is not None
            with pytest.raises(ValidationError, match="SQLite QC review-queue writer contention"):
                create_review_queue_workflow_artifact(
                    session=session,
                    settings=app.state.settings,
                    project_id=project_id,
                    parameters=params,
                    inputs={"project": [source]},
                )
            assert not session.in_transaction()
    finally:
        blocker.rollback()
        blocker.close()

    with app.state.session_factory() as session:
        source = session.get(WorkflowArtifact, source_id)
        assert source is not None
        for _ in range(2):
            output = create_review_queue_workflow_artifact(
                session=session,
                settings=app.state.settings,
                project_id=project_id,
                parameters=params,
                inputs={"project": [source]},
            )
            assert len(output) == 1
            assert output[0]["data_type"] == "review_queue_reference"
            assert output[0]["payload"]["queue_id"] == expected_id
            assert output[0]["payload"]["priority_score_unit"] == "dimensionless"
            assert output[0]["payload"]["review_status"] == "requires_researcher_review"
        workflow_queues = session.scalars(
            select(ReviewQueue).where(
                ReviewQueue.project_id == project_id,
                ReviewQueue.created_by == f"workflow:{run_id}:{params['__workflow_node_run_id']}",
            )
        ).all()
        assert [queue.id for queue in workflow_queues] == [expected_id]

    history = client.get(events_url)
    assert history.status_code == 200 and history.json()["total"] == 1
    assert history.json()["items"][0]["id"] == comment.json()["id"]
    annotations = client.get(f"/api/v1/images/{imported['successful'][0]['image_id']}/annotations")
    assert annotations.status_code == 200
    assert annotations.json()["annotations"] == []
