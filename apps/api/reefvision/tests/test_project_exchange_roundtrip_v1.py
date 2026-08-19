from __future__ import annotations

from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.config import Settings
from reefvision.db.models import ImageAsset, WorkflowGraphRecord
from reefvision.jobs.project_exchange import process_project_exchange_export_job
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_images import create_project, image_bytes, import_one


def test_project_exchange_round_trip_remaps_ids_media_and_workflow_graphs(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project = create_project(client, "Round-trip reef project")
    report = import_one(
        client,
        project["id"],
        filename="reef.png",
        relative_path="survey/reef.png",
    )
    image_id = str(report["successful"][0]["image_id"])

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        graph_json = {
            "schema_version": "workflow-graph-0001",
            "nodes": [
                {
                    "id": "source-image",
                    "type": "current_project",
                    "parameters": {
                        "project_id": project["id"],
                        "selected_image_id": image_id,
                    },
                }
            ],
            "edges": [],
        }
        graph = WorkflowGraphRecord(
            project_id=str(project["id"]),
            graph_key="round-trip-graph",
            name="Round-trip graph",
            schema_version="workflow-graph-0001",
            revision=1,
            graph_json=graph_json,
            graph_sha256=canonical_json_sha256(graph_json),
        )
        session.add(graph)
        session.commit()
        source_graph_id = graph.id
        source_graph_sha = graph.graph_sha256

    created = client.post(
        f"/api/v1/projects/{project['id']}/exchange-packages",
        json={
            "include_media": True,
            "include_model_weights": False,
            "include_generated_artifacts": False,
            "notes": "1.0 round-trip acceptance",
        },
    )
    assert created.status_code == 202, created.text
    export_payload = created.json()
    assert process_project_exchange_export_job(
        test_settings,
        app.state.session_factory,
        export_payload["job_id"],
    )

    package_response = client.get(
        f"/api/v1/exchange-packages/{export_payload['package']['id']}"
    )
    assert package_response.status_code == 200, package_response.text
    package = package_response.json()
    assert package["manifest_json"]["import_policy"]["mode"] == (
        "import_as_new_project"
    )
    assert package["manifest_json"]["sections"]["workflow_graphs"]["count"] == 1
    assert "jobs" in package["manifest_json"]["sections"]

    archive_path = test_settings.resolved_data_dir / Path(package["archive_path"])
    archive_bytes = archive_path.read_bytes()
    imported = client.post(
        "/api/v1/exchange-packages/import",
        files={
            "file": (
                "round-trip.reefvision.zip",
                archive_bytes,
                "application/zip",
            )
        },
        data={"project_name": "Round-trip reef project imported"},
    )
    assert imported.status_code == 201, imported.text
    result = imported.json()
    imported_project_id = str(result["project_id"])
    assert imported_project_id != project["id"]
    assert result["project_name"] == "Round-trip reef project imported"
    assert result["imported_counts"]["images"] == 1
    assert result["imported_counts"]["workflow_graphs"] == 1
    assert result["copied_media_count"] == 1
    assert result["package"]["direction"] == "import"
    assert result["package"]["status"] == "complete"

    imported_images = client.get(
        f"/api/v1/projects/{imported_project_id}/images"
    )
    assert imported_images.status_code == 200, imported_images.text
    assert imported_images.json()["total"] == 1
    imported_image_id = str(imported_images.json()["items"][0]["id"])
    assert imported_image_id != image_id

    imported_content = client.get(f"/api/v1/images/{imported_image_id}/content")
    assert imported_content.status_code == 200, imported_content.text
    assert imported_content.content == image_bytes()

    with app.state.session_factory() as session:
        imported_image = session.get(ImageAsset, imported_image_id)
        assert imported_image is not None
        assert imported_image.project_id == imported_project_id
        assert imported_image.thumbnail_path is None
        assert (test_settings.resolved_data_dir / imported_image.managed_path).is_file()

        imported_graph = session.scalar(
            select(WorkflowGraphRecord).where(
                WorkflowGraphRecord.project_id == imported_project_id,
                WorkflowGraphRecord.graph_key == "round-trip-graph",
            )
        )
        assert imported_graph is not None
        assert imported_graph.id != source_graph_id
        assert imported_graph.graph_json["nodes"][0]["parameters"]["project_id"] == (
            imported_project_id
        )
        assert imported_graph.graph_json["nodes"][0]["parameters"][
            "selected_image_id"
        ] == imported_image_id
        assert imported_graph.graph_sha256 != source_graph_sha
        assert imported_graph.graph_sha256 == canonical_json_sha256(
            imported_graph.graph_json
        )
