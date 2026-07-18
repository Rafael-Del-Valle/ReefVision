from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from fastapi.testclient import TestClient

from reefvision.db.models import ImageAsset, ReviewQueueItem
from reefvision.services.active_learning_queues import (
    ActiveLearningCandidate,
    select_diverse_candidates,
)
from reefvision.tests.test_annotations import create_project, import_one


def _candidate(
    image_id: str,
    *,
    score: float,
    rank: int,
    group_key: str | None,
    class_ids: list[str],
    model_ids: list[str] | None = None,
) -> ActiveLearningCandidate:
    item = cast(
        ReviewQueueItem,
        SimpleNamespace(
            id=f"item-{image_id}",
            image_id=image_id,
            score=score,
            rank_position=rank,
            label_class_ids_json=class_ids,
            model_ids_json=model_ids or [],
            split="train",
            highest_qc_severity=None,
        ),
    )
    image = cast(
        ImageAsset,
        SimpleNamespace(id=image_id, group_key=group_key),
    )
    return ActiveLearningCandidate(item=item, image=image)


def test_diversity_selection_can_prefer_a_novel_group_and_class() -> None:
    candidates = [
        _candidate(
            "highest",
            score=95.0,
            rank=1,
            group_key="colony-a",
            class_ids=["class-a"],
        ),
        _candidate(
            "redundant",
            score=94.0,
            rank=2,
            group_key="colony-a",
            class_ids=["class-a"],
        ),
        _candidate(
            "novel",
            score=75.0,
            rank=3,
            group_key="colony-b",
            class_ids=["class-b"],
        ),
    ]

    selected = select_diverse_candidates(
        candidates,
        max_items=2,
        diversity_weight=0.8,
        max_items_per_group=None,
    )

    assert [item.candidate.item.image_id for item in selected] == ["highest", "novel"]
    assert selected[1].diversity_score > 0.0
    assert selected[1].selection_score > 60.0


def test_diversity_selection_enforces_per_group_limit() -> None:
    candidates = [
        _candidate(
            "first-a",
            score=90.0,
            rank=1,
            group_key="colony-a",
            class_ids=["class-a"],
        ),
        _candidate(
            "second-a",
            score=89.0,
            rank=2,
            group_key="colony-a",
            class_ids=["class-b"],
        ),
        _candidate(
            "first-b",
            score=70.0,
            rank=3,
            group_key="colony-b",
            class_ids=["class-c"],
        ),
    ]

    selected = select_diverse_candidates(
        candidates,
        max_items=3,
        diversity_weight=0.0,
        max_items_per_group=1,
    )

    assert [item.candidate.item.image_id for item in selected] == ["first-a", "first-b"]


def test_project_active_learning_queue_is_compact_and_excludes_reviewed_images(
    client: TestClient,
) -> None:
    project = create_project(client, "Active learning project")
    first = import_one(
        client,
        project["id"],
        filename="first.png",
        relative_path="colony-a/first.png",
        size=(80, 60),
    )
    second = import_one(
        client,
        project["id"],
        filename="second.png",
        relative_path="colony-a/second.png",
        size=(81, 60),
    )
    third = import_one(
        client,
        project["id"],
        filename="third.png",
        relative_path="colony-b/third.png",
        size=(82, 60),
    )
    first_id = first["successful"][0]["image_id"]
    second_id = second["successful"][0]["image_id"]
    third_id = third["successful"][0]["image_id"]

    for image_id, group_key in (
        (first_id, "colony-a"),
        (second_id, "colony-a"),
        (third_id, "colony-b"),
    ):
        response = client.patch(
            f"/api/v1/images/{image_id}",
            json={"group_key": group_key},
        )
        assert response.status_code == 200, response.text

    reviewed = client.patch(
        f"/api/v1/images/{second_id}",
        json={"annotation_status": "reviewed"},
    )
    assert reviewed.status_code == 200, reviewed.text

    response = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-queues",
        json={
            "max_items": 1,
            "diversity_weight": 0.5,
            "max_items_per_group": 1,
            "include_reviewed": False,
        },
    )

    assert response.status_code == 201, response.text
    queue = response.json()
    assert queue["formula_id"] == "active_learning_diversity_v1"
    assert queue["item_count"] == 1
    assert queue["summary_json"]["candidate_count"] == 2
    assert queue["summary_json"]["reviewed_excluded"] == 1
    assert queue["configuration_json"]["active_learning"]["max_items"] == 1

    items_response = client.get(f"/api/v1/review-queues/{queue['id']}/items")
    assert items_response.status_code == 200, items_response.text
    items = items_response.json()["items"]
    assert len(items) == 1
    assert items[0]["rank_position"] == 1
    assert "active_learning_diversity" in items[0]["normalized_signals_json"]
    assert "Active-learning score" in items[0]["reason_summary"]

    regenerated_response = client.post(
        f"/api/v1/review-queues/{queue['id']}/regenerate"
    )
    assert regenerated_response.status_code == 200, regenerated_response.text
    regenerated = regenerated_response.json()
    assert regenerated["formula_id"] == "active_learning_diversity_v1"
    assert regenerated["regenerated_from_queue_id"] == queue["id"]
    assert regenerated["item_count"] == 1
    assert (
        regenerated["configuration_json"]["active_learning"]
        == queue["configuration_json"]["active_learning"]
    )
