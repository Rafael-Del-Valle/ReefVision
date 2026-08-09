from __future__ import annotations

from typing import Any, cast

import numpy
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import (
    Annotation,
    Job,
    ModelRegistration,
    PredictionProposal,
    WorkflowArtifact,
    WorkflowNodeRun,
    WorkflowRun,
)
from reefvision.ml.providers import AssistPrediction, PixelBox
from reefvision.services.workflow_prompt_assist import create_prompt_assist_mask_proposals
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project, import_one


class FakeAssistProvider:
    provider_name = "fake_assist"
    provider_version = "test-1"

    def __init__(self) -> None:
        self.loaded = False
        self.unloaded = False
        self.prepared_images = 0

    def load_model(self, model_path: Any, device: str) -> None:
        del model_path, device
        self.loaded = True

    def prepare_image(self, image_path: Any) -> dict[str, Any]:
        assert self.loaded is True
        self.prepared_images += 1
        return {"image_path": str(image_path)}

    def predict_from_points(self, *args: Any, **kwargs: Any) -> AssistPrediction:
        del args, kwargs
        raise AssertionError("Box-prompt workflow should not call point prompting")

    def predict_from_box(self, prepared_image: Any, box: PixelBox) -> AssistPrediction:
        assert prepared_image["image_path"]
        mask = numpy.zeros((80, 100), dtype=bool)
        mask[12:48, 10:42] = True
        return AssistPrediction(
            mask=mask,
            box=PixelBox(x_min=10.0, y_min=12.0, x_max=42.0, y_max=48.0),
            score=0.93,
        )

    def unload_model(self) -> None:
        self.unloaded = True


def _seed_reviewed_boxes(
    client: TestClient,
) -> tuple[dict[str, object], str, str, str, str]:
    project = create_project(client, "Prompt Assist workflow")
    imported = import_one(client, str(project["id"]), size=(100, 80))
    image_id = str(imported["successful"][0]["image_id"])
    class_id = str(project["label_classes"][0]["id"])

    graph = {
        "graph_id": "prompt-assist-seed",
        "name": "Prompt assist seed",
        "nodes": [{"node_id": "project", "node_type": "project_source"}],
        "edges": [],
    }
    saved = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs",
        json={"graph": graph},
    )
    assert saved.status_code == 201, saved.text
    queued = client.post(
        f"/api/v1/projects/{project['id']}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert queued.status_code == 202, queued.text
    run_id = str(queued.json()["id"])

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        annotation = Annotation(
            image_id=image_id,
            label_class_id=class_id,
            x_min=10.0,
            y_min=12.0,
            x_max=42.0,
            y_max=48.0,
            source_type="manual",
            provenance_json={"source": "test"},
            created_by="scientist",
            revision=1,
        )
        model = ModelRegistration(
            project_id=project["id"],
            purpose="assist",
            display_name="Prompt Assist model",
            source_filename="sam_vit_h_test.pth",
            managed_path=f"projects/{project['id']}/models/sam_vit_h_test.pth",
            sha256="a" * 64,
            file_size_bytes=10,
            framework="test",
            task="assist_segmentation",
            provider_name="fake_assist",
            provider_version="test-1",
            class_map_json={},
            input_size_json={},
            metadata_json={},
        )
        session.add_all([annotation, model])
        session.flush()
        node_run = session.scalar(
            select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run_id)
        )
        assert node_run is not None
        artifact = WorkflowArtifact(
            workflow_run_id=run_id,
            producer_node_run_id=node_run.id,
            producer_port_id="boxes",
            data_type="reviewed_boxes",
            payload_json={
                "schema_version": "workflow-reviewed-artifact-0001",
                "project_id": project["id"],
                "annotation_ids": [annotation.id],
                "count": 1,
            },
            payload_sha256="b" * 64,
        )
        session.add(artifact)
        session.commit()
        return project, annotation.id, model.id, artifact.id, run_id


def test_prompt_assist_creates_pending_raster_mask_proposals(client: TestClient) -> None:
    project, annotation_id, model_id, artifact_id, run_id = _seed_reviewed_boxes(client)
    app = cast(FastAPI, client.app)
    provider = FakeAssistProvider()

    with app.state.session_factory() as session:
        artifact = session.get(WorkflowArtifact, artifact_id)
        assert artifact is not None
        result = create_prompt_assist_mask_proposals(
            session,
            app.state.settings,
            project_id=str(project["id"]),
            boxes_artifact=artifact,
            model_id=model_id,
            device="cpu",
            provider_factory=lambda _: provider,
        )

        assert result["count"] == 1
        assert result["input_annotation_ids"] == [annotation_id]
        assert result["provider_name"] == "fake_assist"
        proposal = session.get(PredictionProposal, result["proposal_ids"][0])
        assert proposal is not None
        assert proposal.review_status == "pending"
        assert proposal.geometry_kind == "raster_mask"
        assert proposal.label_class_id == project["label_classes"][0]["id"]
        assert proposal.confidence == 0.93
        assert proposal.provenance_json["source"] == "workflow_prompt_assist"
        assert proposal.provenance_json["workflow_artifact_id"] == artifact_id
        assert proposal.provenance_json["workflow_run_id"] == run_id
        assert proposal.provenance_json["input_annotation_id"] == annotation_id
        assert len(str(proposal.mask_content_sha256)) == 64
        mask_path = resolve_managed_project_path(app.state.settings, str(proposal.mask_path))
        assert mask_path.is_file()

        job = session.get(Job, str(result["inference_job_id"]))
        assert job is not None
        assert job.status == "succeeded"
        assert job.request_json["workflow_operation"] == "prompt_assist_masks"
        assert job.result_json["proposal_count"] == 1

    assert provider.loaded is True
    assert provider.unloaded is True
    assert provider.prepared_images == 1
