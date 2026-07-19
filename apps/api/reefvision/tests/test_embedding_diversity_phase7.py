from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import ImageAsset
from reefvision.tests.test_annotations import create_project, import_one


def test_embedding_diversity_combines_priority_novelty_and_group_caps(
    client: TestClient,
) -> None:
    project = create_project(client, "Embedding diversity")
    imported = [
        import_one(
            client,
            str(project["id"]),
            filename=f"candidate-{index}.png",
            relative_path=f"candidates/candidate-{index}.png",
            size=(80 + index, 60),
        )
        for index in range(4)
    ]
    image_ids = [str(item["successful"][0]["image_id"]) for item in imported]
    first_id, similar_id, _orthogonal_id, opposite_id = image_ids
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        for image_id, group_key in zip(
            image_ids,
            ["fragment-a", "fragment-a", "fragment-b", "fragment-b"],
            strict=True,
        ):
            image = session.get(ImageAsset, image_id)
            assert image is not None
            image.group_key = group_key
        session.commit()

    vectors = {
        first_id: [1.0, 0.0],
        similar_id: [0.999, 0.001],
        opposite_id: [-1.0, 0.0],
    }
    for image_id, vector in vectors.items():
        saved = client.put(
            f"/api/v1/images/{image_id}/embedding",
            json={
                "embedding_model_id": "dinov3-test",
                "embedding_model_checksum": "a" * 64,
                "vector": vector,
                "source": {"provider": "test"},
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["dimension"] == 2
        assert len(saved.json()["vector_sha256"]) == 64

    listed = client.get(
        f"/api/v1/projects/{project['id']}/embeddings",
        params={"embedding_model_id": "dinov3-test"},
    )
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 3

    response = client.post(
        f"/api/v1/projects/{project['id']}/embedding-diversity-selection",
        json={
            "embedding_model_id": "dinov3-test",
            "embedding_model_checksum": "a" * 64,
            "candidate_image_ids": image_ids,
            "maximum_items": 3,
            "diversity_weight": 0.5,
            "base_scores": {first_id: 100.0},
            "maximum_items_per_group": 1,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["candidate_count"] == 4
    assert payload["skipped_missing_embedding_count"] == 1
    assert payload["selected_count"] == 2
    assert payload["vector_dimension"] == 2
    assert [item["image_id"] for item in payload["selections"]] == [
        first_id,
        opposite_id,
    ]
    assert payload["selections"][0]["novelty_score"] == pytest.approx(1)
    assert payload["selections"][0]["nearest_selected_image_id"] is None
    assert payload["selections"][1]["novelty_score"] == pytest.approx(1)
    assert payload["selections"][1]["nearest_selected_image_id"] == first_id
    assert any("matching embedding" in item for item in payload["warnings"])
    assert any("per-group" in item for item in payload["warnings"])


def test_embedding_upsert_replaces_vector_for_same_model(client: TestClient) -> None:
    project = create_project(client, "Embedding replacement")
    imported = import_one(client, str(project["id"]))
    image_id = str(imported["successful"][0]["image_id"])
    first = client.put(
        f"/api/v1/images/{image_id}/embedding",
        json={
            "embedding_model_id": "encoder",
            "vector": [1, 0],
        },
    )
    assert first.status_code == 200, first.text
    second = client.put(
        f"/api/v1/images/{image_id}/embedding",
        json={
            "embedding_model_id": "encoder",
            "vector": [0, 1],
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["vector_sha256"] != first.json()["vector_sha256"]
