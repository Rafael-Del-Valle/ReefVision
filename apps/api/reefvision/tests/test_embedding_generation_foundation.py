from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import ImageAsset, ImageEmbedding, Job
from reefvision.jobs.image_embeddings import process_image_embedding_job
from reefvision.schemas.image_embeddings import ImageEmbeddingGenerateRequest
from reefvision.tests.test_annotations import create_project, import_one


def test_batched_generation_persists_every_image_and_retry_reuses_job(
    client: TestClient,
) -> None:
    project = create_project(client, "Batched embedding job")
    image_ids = [
        str(
            import_one(
                client,
                str(project["id"]),
                filename=f"batch-{index}.png",
                relative_path=f"batch/batch-{index}.png",
                size=(64 + index, 48),
            )["successful"][0]["image_id"]
        )
        for index in range(5)
    ]
    payload = {
        "provider_id": "color_texture_v1",
        "model_id": "reefvision-color-texture-v1",
        "device": "cpu",
        "batch_size": 2,
    }
    queued = client.post(
        f"/api/v1/projects/{project['id']}/embedding-jobs",
        json=payload,
    )
    assert queued.status_code == 202, queued.text
    job_id = str(queued.json()["job"]["id"])
    app = cast(FastAPI, client.app)
    assert process_image_embedding_job(
        app.state.settings,
        app.state.session_factory,
        job_id,
    )
    with app.state.session_factory() as session:
        embeddings = list(
            session.scalars(
                select(ImageEmbedding).where(
                    ImageEmbedding.project_id == project["id"],
                    ImageEmbedding.source_kind == "image",
                )
            )
        )
        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == "succeeded"
        assert job.progress_current == len(image_ids)
        assert len(embeddings) == len(image_ids)
        assert {item.image_id for item in embeddings} == set(image_ids)
        assert all(item.normalization == "l2" for item in embeddings)

    retried = client.post(
        f"/api/v1/projects/{project['id']}/embedding-jobs",
        json=payload,
    )
    assert retried.status_code == 202, retried.text
    assert retried.json()["job"]["id"] == job_id


def test_embedding_versions_are_preserved_and_source_changes_become_stale(
    client: TestClient,
) -> None:
    project = create_project(client, "Versioned embeddings")
    image_id = str(import_one(client, str(project["id"]))["successful"][0]["image_id"])
    for model_version, vector in (("1", [1, 0]), ("2", [0, 1])):
        response = client.put(
            f"/api/v1/images/{image_id}/embedding",
            json={
                "provider_id": "manual",
                "embedding_model_id": "versioned-encoder",
                "embedding_model_checksum": model_version * 64,
                "model_version": model_version,
                "preprocessing_version": "rgb-v1",
                "vector": vector,
                "replace_existing": False,
            },
        )
        assert response.status_code == 200, response.text
    listed = client.get(
        f"/api/v1/projects/{project['id']}/embeddings",
        params={"embedding_model_id": "versioned-encoder"},
    )
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 2

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        image = session.get(ImageAsset, image_id)
        assert image is not None
        image.sha256 = "e" * 64
        session.commit()
    coverage = client.get(
        f"/api/v1/projects/{project['id']}/embedding-coverage",
        params={
            "provider_id": "manual",
            "embedding_model_id": "versioned-encoder",
            "embedding_model_checksum": "2" * 64,
            "preprocessing_version": "rgb-v1",
        },
    )
    assert coverage.status_code == 200, coverage.text
    assert coverage.json()["stale_image_count"] == 1
    assert coverage.json()["ready_image_count"] == 0


def test_embedding_inference_never_downloads_model_weights() -> None:
    with pytest.raises(ValueError, match="cannot download weights"):
        ImageEmbeddingGenerateRequest(
            provider_id="transformers_vision",
            model_id="remote/vision-model",
            local_files_only=False,
        )
