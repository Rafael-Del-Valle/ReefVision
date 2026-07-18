from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

import reefvision.jobs.inference as inference_module
from reefvision.db.models import MaskAnnotationEvent, ModelRegistration, Project
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project, import_one


class FakeSemanticProvider:
    provider_id = "nnunet"
    provider_version = "test"

    def predict(
        self,
        checkpoint_path: Path,
        image_path: Path,
        *,
        device: str,
    ) -> Path:
        assert checkpoint_path.is_file()
        assert image_path.is_file()
        assert device in {"auto", "cpu", "cuda"}
        with Image.open(image_path) as source:
            width, height = source.size
        result = checkpoint_path.parent / "fake-semantic-output.png"
        mask = Image.new("L", (width, height), 0)
        for x in range(max(width // 4, 1), max(width // 2, 2)):
            for y in range(max(height // 4, 1), max(height // 2, 2)):
                mask.putpixel((x, y), 1)
        for x in range(max(width // 2, 1), max((3 * width) // 4, 2)):
            for y in range(max(height // 2, 1), max((3 * height) // 4, 2)):
                mask.putpixel((x, y), 2)
        mask.save(result)
        return result


def _seed_semantic_segmenter(
    client: TestClient,
    project_id: str,
    label_class_id: str,
) -> ModelRegistration:
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        project = session.get(Project, project_id)
        assert project is not None
        managed_path = f"{project.storage_root}/models/test-semantic.zip"
        checkpoint = resolve_managed_project_path(app.state.settings, managed_path)
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_bytes(b"semantic-model-bundle")
        model = ModelRegistration(
            project_id=project_id,
            purpose="semantic_segmenter",
            display_name="Test Semantic Segmenter",
            source_filename="test-semantic.zip",
            managed_path=managed_path,
            sha256="b" * 64,
            file_size_bytes=checkpoint.stat().st_size,
            framework="nnunetv2",
            task="semantic_segment",
            provider_name="nnunet",
            provider_version="test",
            class_map_json={
                "labels": ["soft coral", "soft coral secondary"],
                "mapping": {
                    "soft coral": label_class_id,
                    "soft coral secondary": label_class_id,
                },
                "pixel_values": {
                    "soft coral": 1,
                    "soft coral secondary": 2,
                },
            },
            input_size_json=None,
            metadata_json={
                "proposal_geometry": "raster_mask",
                "classes": [
                    {
                        "class_index": 0,
                        "pixel_value": 1,
                        "class_name": "soft coral",
                    },
                    {
                        "class_index": 1,
                        "pixel_value": 2,
                        "class_name": "soft coral secondary",
                    },
                ],
            },
        )
        session.add(model)
        session.commit()
        session.refresh(model)
        session.expunge(model)
        return model


def test_semantic_inference_creates_previewable_raster_proposals_and_reviews_them(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Semantic inference")
    report = import_one(client, project["id"])
    image_id = report["successful"][0]["image_id"]
    label_class_id = project["label_classes"][0]["id"]
    model = _seed_semantic_segmenter(client, project["id"], label_class_id)

    monkeypatch.setattr(
        inference_module,
        "semantic_provider_for_name",
        lambda _provider_name: FakeSemanticProvider(),
    )
    queued = client.post(
        f"/api/v1/projects/{project['id']}/inference-jobs",
        json={"model_id": model.id, "image_ids": [image_id], "device": "cpu"},
    )
    assert queued.status_code == 200, queued.text
    job = queued.json()
    assert job["request_json"]["model_task"] == "semantic_segment"

    app = cast(FastAPI, client.app)
    assert (
        inference_module.process_inference_job(
            app.state.settings,
            app.state.session_factory,
            job["id"],
        )
        is True
    )

    listed = client.get(f"/api/v1/images/{image_id}/prediction-proposals?review_status=pending")
    assert listed.status_code == 200, listed.text
    proposals = listed.json()["items"]
    assert len(proposals) == 2
    assert {item["geometry_kind"] for item in proposals} == {"raster_mask"}
    assert all(item["mask_content_sha256"] for item in proposals)

    preview = client.get(f"/api/v1/prediction-proposals/{proposals[0]['id']}/mask")
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/png")

    rejected = client.post(f"/api/v1/prediction-proposals/{proposals[0]['id']}/reject")
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["proposal"]["review_status"] == "rejected"

    accepted = client.post(
        f"/api/v1/prediction-proposals/{proposals[1]['id']}/accept",
        json={"label_class_id": label_class_id},
    )
    assert accepted.status_code == 200, accepted.text
    payload = accepted.json()
    assert payload["annotation"] is None
    assert payload["mask_annotation"]["geometry_kind"] == "raster_mask"
    assert payload["mask_annotation"]["source_type"] == "accepted_prediction"

    session_response = client.get(f"/api/v1/images/{image_id}/annotations")
    assert session_response.status_code == 200, session_response.text
    session_payload = session_response.json()
    assert len(session_payload["mask_annotations"]) == 1
    assert session_payload["mask_annotations"][0]["geometry_kind"] == "raster_mask"
    assert session_payload["image"]["annotation_revision"] == 1

    with app.state.session_factory() as session:
        events = session.query(MaskAnnotationEvent).filter_by(image_id=image_id).all()
        assert len(events) == 1
        assert events[0].event_type == "created"
        assert events[0].after_json["source_type"] == "accepted_prediction"
