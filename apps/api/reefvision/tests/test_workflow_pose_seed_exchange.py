"""Use verified native checkpoints with a destination project's frozen anatomy."""

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.config import Settings
from reefvision.db.models import ProjectExchangePackage
from reefvision.jobs.project_exchange import process_project_exchange_export_job
from reefvision.ml.reefpose.checkpoints import load_checkpoint
from reefvision.services.pose_training_exports import PoseTrainingExportService
from reefvision.storage.models import hash_model_file
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_project_exchange_reefpose_workflow import _execute
from reefvision.tests.test_workflow_pose_training_phase10 import (
    _frozen_dataset,
    _native_pose_workflow_graph,
    _synthetic_exact_frames,
)


def _save_and_run(client: TestClient, project_id: str, graph: dict[str, object]) -> dict[str, Any]:
    response = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert response.status_code == 201, response.text
    return _execute(client, project_id, response.json()["id"])


def _seed_graph(dataset_id: str, model_id: str) -> dict[str, object]:
    graph = _native_pose_workflow_graph(dataset_id)
    nodes = cast(list[dict[str, Any]], graph["nodes"])
    edges = cast(list[dict[str, str]], graph["edges"])
    nodes[1]["parameters"]["initialization_mode"] = "registered_model"
    graph["nodes"] = [
        *nodes[:2],
        {"node_id": "project", "node_type": "project_source"},
        {
            "node_id": "seed",
            "node_type": "registered_model_source",
            "parameters": {"model_id": model_id},
        },
    ]
    graph["edges"] = [
        edges[0],
        {
            "edge_id": "project-seed",
            "source_node_id": "project",
            "source_port_id": "project",
            "target_node_id": "seed",
            "target_port_id": "project",
        },
        {
            "edge_id": "seed-train",
            "source_node_id": "seed",
            "source_port_id": "model",
            "target_node_id": "train",
            "target_port_id": "initial_model",
        },
    ]
    return graph


def _exchange(client: TestClient, settings: Settings, project_id: str) -> dict[str, Any]:
    app = cast(FastAPI, client.app)
    queued = client.post(
        f"/api/v1/projects/{project_id}/exchange-packages",
        json={
            "include_media": True,
            "include_model_weights": True,
            "include_generated_artifacts": True,
        },
    )
    assert queued.status_code == 202, queued.text
    package = queued.json()
    assert process_project_exchange_export_job(
        settings, app.state.session_factory, package["job_id"]
    )
    export = client.get(f"/api/v1/exchange-packages/{package['package']['id']}/download")
    assert export.status_code == 200, export.text
    restored = client.post(
        "/api/v1/exchange-packages/import",
        files={"file": ("pose.reefvision.zip", export.content, "application/zip")},
    )
    assert restored.status_code == 201, restored.text
    return cast(dict[str, Any], restored.json())


def test_exchanged_native_seed_trains_with_the_destination_anatomy(
    client: TestClient, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Keep the real torch worker and substitute small decoded frames from the generated recording.
    monkeypatch.setattr(
        PoseTrainingExportService, "_extract_exact_frames", staticmethod(_synthetic_exact_frames)
    )
    source, dataset = _frozen_dataset(client, monkeypatch)
    source_id, dataset_id = str(source["id"]), str(dataset["id"])
    created = _save_and_run(client, source_id, _native_pose_workflow_graph(dataset_id))
    assert created["run"]["status"] == "succeeded", created["run"]["error_message"]
    [model] = [
        a["payload_json"] for a in created["artifacts"] if a["data_type"] == "model_reference"
    ]
    direct = _save_and_run(client, source_id, _seed_graph(dataset_id, model["model_id"]))
    assert direct["run"]["status"] == "succeeded", direct["run"]["error_message"]

    receipt = _exchange(client, test_settings, source_id)
    local_project = receipt["project_id"]
    mapping = receipt["package"]["options_json"]["id_map"]
    local_model = mapping[model["model_id"]]
    profile = client.get(f"/api/v1/models/{local_model}").json()
    seed = resolve_managed_project_path(test_settings, profile["managed_path"])
    original_sha = hash_model_file(seed)[0]
    assert original_sha == model["model_sha256"]
    source_schema = load_checkpoint(seed).schema
    assert source_schema.schema_id == dataset["pose_schema_id"]
    assert source_schema.schema_id != mapping[dataset["pose_schema_id"]]

    seeded = _seed_graph(mapping[dataset_id], local_model)
    trained = _save_and_run(client, local_project, seeded)
    assert trained["run"]["status"] == "succeeded", trained["run"]["error_message"]
    [training] = [
        a["payload_json"] for a in trained["artifacts"] if a["data_type"] == "training_result"
    ]
    assert training["initialization_mode"] == "registered_model"
    assert training["initial_checkpoint_model_id"] == local_model
    selected = resolve_managed_project_path(test_settings, training["result_checkpoint_path"])
    current_schema = load_checkpoint(selected).schema
    assert current_schema.schema_id == mapping[dataset["pose_schema_id"]]
    assert current_schema.landmarks == source_schema.landmarks
    assert current_schema.skeleton == source_schema.skeleton
    assert hash_model_file(seed)[0] == original_sha

    second = _exchange(client, test_settings, local_project)
    second_mapping = second["package"]["options_json"]["id_map"]
    retrained = _save_and_run(
        client,
        second["project_id"],
        _seed_graph(second_mapping[mapping[dataset_id]], second_mapping[local_model]),
    )
    assert retrained["run"]["status"] == "succeeded", retrained["run"]["error_message"]

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        imported = session.scalar(
            select(ProjectExchangePackage).where(
                ProjectExchangePackage.project_id == local_project,
                ProjectExchangePackage.direction == "import",
            )
        )
        assert imported is not None
        options = dict(imported.options_json)
        for field in ("id_map", "origin_id_map"):
            if field in options:
                options[field] = {
                    prior: local
                    for prior, local in options[field].items()
                    if prior != source_schema.schema_id
                }
        imported.options_json = options
        session.commit()

    refused = _save_and_run(client, local_project, seeded)
    assert refused["run"]["status"] == "failed"
    assert "Checkpoint anatomy differs" in refused["run"]["error_message"]
    assert hash_model_file(seed)[0] == original_sha
