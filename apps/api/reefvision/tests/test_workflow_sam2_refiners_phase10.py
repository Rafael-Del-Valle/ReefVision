from __future__ import annotations

from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

import reefvision.jobs.workflow_sam2_refiners as workflow_sam2_refiners
from reefvision.db.models import ModelRegistration
from reefvision.tests.test_annotations import create_project


def test_registered_sam2_sidecar_is_injected_into_exact_pipeline(
    client: TestClient,
    monkeypatch,
) -> None:
    project = create_project(client, "SAM 2 workflow injection")
    registered = client.post(
        f"/api/v1/projects/{project['id']}/sam2-sidecar-models",
        json={
            "display_name": "SAM 2 sidecar",
            "endpoint": "http://127.0.0.1:8766",
        },
    )
    assert registered.status_code == 201, registered.text
    model_id = registered.json()["id"]
    app = cast(FastAPI, client.app)
    observed: dict[str, Any] = {}

    def fake_pipeline(settings, factory, **kwargs):
        observed.update(kwargs)
        return "pipeline-result"

    monkeypatch.setattr(workflow_sam2_refiners, "_ORIGINAL_PIPELINE", fake_pipeline)
    result = workflow_sam2_refiners.run_pipeline_with_registered_sam2(
        app.state.settings,
        app.state.session_factory,
        sam2_model_id=model_id,
        device="cuda:0",
    )

    assert result == "pipeline-result"
    refiner = observed["refiner"]
    assert isinstance(refiner, workflow_sam2_refiners.SidecarSAM2BoxRefiner)
    assert refiner.model_id == model_id


def test_non_sidecar_sam2_preserves_original_pipeline_path(
    client: TestClient,
    monkeypatch,
) -> None:
    project = create_project(client, "In-process SAM 2 workflow")
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        model = ModelRegistration(
            project_id=str(project["id"]),
            purpose="assist",
            display_name="In-process SAM 2",
            source_filename="sam2.pt",
            managed_path=f"projects/{project['id']}/models/sam2.pt",
            sha256="a" * 64,
            file_size_bytes=len(b"checkpoint"),
            framework="sam2",
            task="assist_segmentation",
            provider_name="sam2",
            provider_version="test",
            class_map_json={},
            metadata_json={},
        )
        session.add(model)
        session.commit()
        model_id = model.id

    observed: dict[str, Any] = {}

    def fake_pipeline(settings, factory, **kwargs):
        observed.update(kwargs)
        return "original-result"

    monkeypatch.setattr(workflow_sam2_refiners, "_ORIGINAL_PIPELINE", fake_pipeline)
    result = workflow_sam2_refiners.run_pipeline_with_registered_sam2(
        app.state.settings,
        app.state.session_factory,
        sam2_model_id=model_id,
        device="cuda:0",
    )

    assert result == "original-result"
    assert "refiner" not in observed
