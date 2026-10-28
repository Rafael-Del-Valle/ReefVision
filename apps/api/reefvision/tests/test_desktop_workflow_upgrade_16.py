"""Real 0037-to-0041 desktop upgrade: executable QC workflow and reviewer audit.

This test uses Alembic migrations on disk, not Base.metadata.create_all.
It exercises the isolated 1.6 lineage only; it does not reconcile the
independently numbered 1.1 scientific-data revision 0038.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.desktop import resolve_alembic_paths, run_pending_migrations
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.main import create_app
from reefvision.tests.test_annotations import import_one


def test_upgraded_desktop_persists_executable_qc_and_manual_review(tmp_path: Path) -> None:
    """Upgrade legacy data, run a saved graph, then reopen without losing evidence."""
    data_dir = tmp_path / "installed-desktop"
    settings = Settings(
        env="test",
        data_dir=data_dir,
        database_url=f"sqlite:///{(data_dir / 'reefvision.db').as_posix()}",
        background_worker_enabled=False,
    )
    settings.ensure_directories()

    alembic_ini, migrations_dir = resolve_alembic_paths()
    config = Config(str(alembic_ini))
    config.attributes["configure_logger"] = False
    config.attributes["desktop_database_url"] = settings.resolved_database_url
    config.set_main_option("script_location", str(migrations_dir))
    config.set_main_option("sqlalchemy.url", settings.resolved_database_url)
    command.upgrade(config, "0037")

    # Create legacy research records before introducing 1.6 QC audit tables.
    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/v1/projects",
            json={"name": "Legacy Swiftia review", "template": "blank"},
        )
        assert created.status_code == 201, created.text
        project_id = created.json()["id"]
        label = client.post(
            f"/api/v1/projects/{project_id}/classes",
            json={"class_index": 0, "name": "Swiftia exserta", "display_color": "#2288AA"},
        )
        assert label.status_code == 201, label.text
        class_id = label.json()["id"]
        default = client.put(
            f"/api/v1/projects/{project_id}/class-visibility/defaults/annotations",
            json={"hidden_class_ids": [class_id]},
        )
        assert default.status_code == 200, default.text
        override = client.put(
            f"/api/v1/projects/{project_id}/class-visibility/preferences/annotations",
            json={"hidden_class_ids": []},
        )
        assert override.status_code == 200, override.text

    run_pending_migrations(settings)

    graph = {
        "graph_id": "upgraded-qc-16",
        "name": "Upgraded QC review",
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
    with TestClient(create_app(settings)) as client:
        imported = import_one(
            client,
            project_id,
            filename="legacy-swiftia.png",
            relative_path="legacy/legacy-swiftia.png",
        )
        image_id = imported["successful"][0]["image_id"]
        planned = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
        assert planned.status_code == 200, planned.text
        assert planned.json()["valid"] and planned.json()["executable"]
        saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
        assert saved.status_code == 201, saved.text
        graph_id = saved.json()["id"]
        queued = client.post(
            f"/api/v1/projects/{project_id}/workflow-runs",
            json={"graph_record_id": graph_id},
        )
        assert queued.status_code == 202, queued.text
        run_id = queued.json()["id"]
        app = cast(FastAPI, client.app)
        assert process_workflow_run_job(
            app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
        )

        detail = client.get(f"/api/v1/workflow-runs/{run_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["run"]["status"] == "succeeded"
        artifacts = [
            artifact
            for artifact in detail.json()["artifacts"]
            if artifact["data_type"] == "review_queue_reference"
        ]
        assert len(artifacts) == 1
        artifact = artifacts[0]
        assert artifact["payload_json"]["priority_score_unit"] == "dimensionless"
        assert artifact["payload_json"]["review_status"] == "requires_researcher_review"
        queue_id = artifact["payload_json"]["queue_id"]
        items = client.get(f"/api/v1/review-queues/{queue_id}/items")
        assert items.status_code == 200, items.text
        assert len(items.json()["items"]) == 1
        item_id = items.json()["items"][0]["id"]
        events_url = f"/api/v1/review-queues/{queue_id}/items/{item_id}/events"
        comment_payload = {
            "client_request_id": str(uuid4()),
            "event_type": "comment",
            "actor": "local marine researcher",
            "comment": "Verify Swiftia polyp boundaries",
        }
        comment = client.post(events_url, json=comment_payload)
        assert comment.status_code == 201, comment.text
        comment_id = comment.json()["id"]
        assigned = client.post(
            events_url,
            json={
                "client_request_id": str(uuid4()),
                "event_type": "assign",
                "actor": "local marine researcher",
                "assignee": "second reviewer",
            },
        )
        assert assigned.status_code == 201, assigned.text
        start = client.post(
            f"/api/v1/review-queues/{queue_id}/items/bulk",
            json={
                "item_ids": [item_id],
                "action": "start",
                "actor": "second reviewer",
                "client_request_id": str(uuid4()),
            },
        )
        assert start.status_code == 200, start.text
        # Workflow generation and bulk triage cannot silently approve observations.
        annotations = client.get(f"/api/v1/images/{image_id}/annotations")
        assert annotations.status_code == 200, annotations.text
        assert annotations.json()["annotations"] == []
        denied = client.post(f"/api/v1/review-queue-items/{item_id}/complete")
        assert denied.status_code == 422, denied.text
        assert client.get(events_url).json()["total"] == 3

    # A second installed-desktop launch must retain saved graphs, artifacts,
    # reviewer assignment, comments, triage state and original visibility.
    run_pending_migrations(settings)
    with TestClient(create_app(settings)) as client:
        detail = client.get(f"/api/v1/workflow-runs/{run_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["run"]["status"] == "succeeded"
        persisted = [
            item
            for item in detail.json()["artifacts"]
            if item["data_type"] == "review_queue_reference"
        ]
        assert len(persisted) == 1
        assert persisted[0]["id"] == artifact["id"]
        assert persisted[0]["payload_sha256"] == artifact["payload_sha256"]
        assert persisted[0]["payload_json"] == artifact["payload_json"]
        history = client.get(events_url)
        assert history.status_code == 200, history.text
        assert history.json()["requires_researcher_review"] is True
        assert history.json()["current_assignee"] == "second reviewer"
        assert [event["event_type"] for event in history.json()["items"]] == [
            "comment",
            "assign",
            "triage_start",
        ]
        assert history.json()["items"][0]["id"] == comment_id
        assert client.post(events_url, json=comment_payload).json()["id"] == comment_id
        assert client.get(events_url).json()["total"] == 3
        item = client.get(f"/api/v1/review-queues/{queue_id}/items")
        assert item.status_code == 200, item.text
        assert item.json()["items"][0]["review_state"] == "in_progress"
        visibility = client.get(f"/api/v1/projects/{project_id}/class-visibility")
        assert visibility.status_code == 200, visibility.text
        assert visibility.json()["project_defaults"]["annotations"]["hidden_class_ids"] == [
            class_id
        ]
        assert visibility.json()["user_preferences"]["annotations"]["saved"] is True
        assert visibility.json()["user_preferences"]["annotations"]["hidden_class_ids"] == []
        annotations = client.get(f"/api/v1/images/{image_id}/annotations")
        assert annotations.status_code == 200, annotations.text
        assert annotations.json()["annotations"] == []
