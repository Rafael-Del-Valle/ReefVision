from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from reefvision.db.models import ActiveLearningCycle, DatasetVersion, ImageAsset, ReviewQueue
from reefvision.schemas.active_learning import ActiveLearningQueuePromotionRequest
from reefvision.schemas.dataset_versions import DatasetVersionCreateRequest
from reefvision.services.active_learning_queues import ActiveLearningQueueService
from reefvision.services.measurement_aware_dataset_versions import (
    MeasurementAwareDatasetVersionService,
)
from reefvision.tests.test_annotations import create_project, import_one


def _images(client: TestClient, project_id: str, count: int) -> list[str]:
    return [
        str(
            import_one(
                client,
                project_id,
                filename=f"candidate-{index}.png",
                relative_path=f"fragment-{index % 2}/candidate-{index}.png",
                size=(80 + index, 60),
            )["successful"][0]["image_id"]
        )
        for index in range(count)
    ]


def _write_embedding(
    client: TestClient,
    image_id: str,
    vector: list[float],
    *,
    checksum: str = "a" * 64,
) -> dict[str, Any]:
    response = client.put(
        f"/api/v1/images/{image_id}/embedding",
        json={
            "embedding_model_id": "local-encoder",
            "embedding_model_checksum": checksum,
            "provider_id": "manual",
            "model_version": "1.0",
            "preprocessing_version": "rgb-v1",
            "replace_existing": False,
            "vector": vector,
        },
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def _queue_payload(**overrides: object) -> dict[str, object]:
    return {
        "max_items": 3,
        "selection_strategy": "k_center",
        "embedding_provider_id": "manual",
        "embedding_model_id": "local-encoder",
        "embedding_model_checksum": "a" * 64,
        "embedding_preprocessing_version": "rgb-v1",
        "uncertainty_weight": 0.4,
        "novelty_weight": 0.5,
        "base_priority_weight": 0.1,
        **overrides,
    }


def test_persisted_embedding_queue_is_explainable_revisioned_and_idempotent(
    client: TestClient,
) -> None:
    project = create_project(client, "Persisted active-learning queue")
    image_ids = _images(client, str(project["id"]), 4)
    for image_id, vector in zip(
        image_ids,
        ([1.0, 0.0], [0.9999, 0.0001], [0.0, 1.0], [-1.0, 0.0]),
        strict=True,
    ):
        _write_embedding(client, image_id, list(vector))

    payload = _queue_payload(
        manual_include_image_ids=[image_ids[1]],
        near_duplicate_cosine_similarity=0.99,
    )
    first = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-queues",
        json=payload,
    )
    assert first.status_code == 201, first.text
    first_queue = first.json()
    assert first_queue["revision"] == 1
    assert first_queue["generation_key"]
    assert first_queue["formula_version"] == "2.0.0"
    assert first_queue["summary_json"]["embedding_configuration"]["model_checksum"] == "a" * 64
    assert first_queue["summary_json"]["cycle_id"]

    repeated = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-queues",
        json=payload,
    )
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["id"] == first_queue["id"]
    assert repeated.json()["revision"] == 1

    items = client.get(f"/api/v1/review-queues/{first_queue['id']}/items").json()["items"]
    assert items
    assert items[0]["manual_state"] == "included"
    assert "Manual priority" in items[0]["selection_reasons_json"]
    assert all(item["near_duplicate_key"] for item in items)
    assert all(item["selection_reasons_json"] for item in items)
    assert all(
        sum(component["contribution"] for component in item["score_breakdown_json"])
        == pytest.approx(item["score"], abs=0.05)
        for item in items
    )

    changed = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-queues",
        json=_queue_payload(novelty_weight=0.4),
    )
    assert changed.status_code == 201, changed.text
    assert changed.json()["id"] != first_queue["id"]
    assert changed.json()["revision"] == 2


def test_queue_reports_and_excludes_stale_or_missing_embeddings(client: TestClient) -> None:
    project = create_project(client, "Stale active-learning embeddings")
    image_ids = _images(client, str(project["id"]), 3)
    _write_embedding(client, image_ids[0], [1.0, 0.0])
    _write_embedding(client, image_ids[1], [0.0, 1.0])
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        stale_image = session.get(ImageAsset, image_ids[1])
        assert stale_image is not None
        stale_image.sha256 = "f" * 64
        session.commit()

    response = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-queues",
        json=_queue_payload(max_items=3, create_cycle=False),
    )
    assert response.status_code == 201, response.text
    summary = response.json()["summary_json"]
    assert summary["selected_count"] == 1
    assert summary["missing_embedding_count"] == 2
    assert summary["stale_embedding_count"] == 1
    assert summary["excluded_missing_embedding_count"] == 2
    assert any("stale embeddings" in warning for warning in summary["warnings"])


def _review_queue_images(
    client: TestClient,
    project: dict[str, Any],
    queue_id: str,
) -> list[str]:
    items = client.get(f"/api/v1/review-queues/{queue_id}/items").json()["items"]
    for index, item in enumerate(items):
        image_id = str(item["image_id"])
        annotation = client.put(
            f"/api/v1/images/{image_id}/annotations",
            json={
                "base_revision": 0,
                "annotation_status": "reviewed",
                "annotations": [
                    {
                        "id": f"00000000-0000-4000-8000-{index + 1:012d}",
                        "label_class_id": project["label_classes"][0]["id"],
                        "x_min": 1,
                        "y_min": 1,
                        "x_max": 20,
                        "y_max": 20,
                    }
                ],
            },
        )
        assert annotation.status_code == 200, annotation.text
        completed = client.post(f"/api/v1/review-queue-items/{item['id']}/complete")
        assert completed.status_code == 200, completed.text
    return [str(item["image_id"]) for item in items]


def test_completed_queue_promotes_once_and_updates_cycle_provenance(
    client: TestClient,
) -> None:
    project = create_project(client, "Active-learning promotion")
    image_ids = _images(client, str(project["id"]), 2)
    queue_response = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-queues",
        json={"max_items": 2},
    )
    assert queue_response.status_code == 201, queue_response.text
    queue = queue_response.json()

    blocked = client.post(
        f"/api/v1/active-learning-queues/{queue['id']}/promote",
        json={"name": "Reviewed cycle one"},
    )
    assert blocked.status_code == 409, blocked.text
    assert set(_review_queue_images(client, project, queue["id"])) == set(image_ids)

    promoted = client.post(
        f"/api/v1/active-learning-queues/{queue['id']}/promote",
        json={"name": "Reviewed cycle one", "split_method": "group_random"},
    )
    assert promoted.status_code == 200, promoted.text
    result = promoted.json()
    assert result["dataset_version_id"]
    assert result["cycle_id"] == queue["summary_json"]["cycle_id"]
    assert not result["idempotent_replay"]

    repeated = client.post(
        f"/api/v1/active-learning-queues/{queue['id']}/promote",
        json={"name": "Ignored retry name"},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["dataset_version_id"] == result["dataset_version_id"]
    assert repeated.json()["idempotent_replay"]

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        cycle = session.get(ActiveLearningCycle, result["cycle_id"])
        assert cycle is not None
        assert cycle.status == "dataset_frozen"
        assert cycle.queue_revision == queue["revision"]
        assert cycle.embedding_model_id is None
        assert cycle.accepted_annotation_ids_json
        assert cycle.dataset_version_id == result["dataset_version_id"]
        assert set(cycle.selection_result_json["reviewed_image_ids"]) == set(image_ids)
        assert set(cycle.selection_result_json["completed_review_image_ids"]) == set(image_ids)
        assert cycle.selection_result_json["skipped_image_ids"] == []


def test_failed_promotion_rolls_back_dataset_and_queue_link(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Promotion rollback")
    _images(client, str(project["id"]), 1)
    queue_response = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-queues",
        json={"max_items": 1},
    )
    queue = queue_response.json()
    _review_queue_images(client, project, queue["id"])
    app = cast(FastAPI, client.app)
    original = MeasurementAwareDatasetVersionService.create_version

    def fail_after_snapshot(
        service: MeasurementAwareDatasetVersionService,
        project_id: str,
        request: DatasetVersionCreateRequest,
        *,
        commit: bool = True,
    ) -> object:
        original(service, project_id, request, commit=False)
        raise RuntimeError("simulated promotion failure")

    monkeypatch.setattr(
        MeasurementAwareDatasetVersionService, "create_version", fail_after_snapshot
    )
    with app.state.session_factory() as session:
        before = int(
            session.scalar(
                select(func.count(DatasetVersion.id)).where(
                    DatasetVersion.project_id == project["id"]
                )
            )
            or 0
        )
        service = ActiveLearningQueueService(session, app.state.settings)
        with pytest.raises(RuntimeError, match="simulated promotion failure"):
            service.promote(
                queue["id"],
                ActiveLearningQueuePromotionRequest(name="Must roll back"),
            )
    with app.state.session_factory() as session:
        after = int(
            session.scalar(
                select(func.count(DatasetVersion.id)).where(
                    DatasetVersion.project_id == project["id"]
                )
            )
            or 0
        )
        persisted_queue = session.get(ReviewQueue, queue["id"])
        assert persisted_queue is not None
        assert after == before
        assert persisted_queue.promoted_dataset_version_id is None
