from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import Job, ModelRegistration, PredictionProposal
from reefvision.tests.test_annotations import create_project, import_one


def _import_images(client: TestClient, project_id: str) -> tuple[str, str]:
    first = import_one(
        client,
        project_id,
        filename="first.png",
        relative_path="round/first.png",
    )
    second = import_one(
        client,
        project_id,
        filename="second.png",
        relative_path="round/second.png",
        size=(81, 60),
    )
    assert first["successful"] and second["successful"]
    return (
        str(first["successful"][0]["image_id"]),
        str(second["successful"][0]["image_id"]),
    )


def _seed_detector_proposals(
    client: TestClient,
    project: dict[str, Any],
    confidence_by_image: dict[str, float],
    checksum: str = "c" * 64,
) -> str:
    app = cast(FastAPI, client.app)
    label_class_id = str(project["label_classes"][0]["id"])
    with app.state.session_factory() as session:
        model = ModelRegistration(
            project_id=str(project["id"]),
            purpose="detector",
            display_name=f"Active-learning detector {checksum[:8]}",
            source_filename="active-learning.pt",
            managed_path=f"{project['storage_root']}/models/{checksum}.pt",
            sha256=checksum,
            file_size_bytes=123,
            framework="ultralytics",
            task="detect",
            provider_name="ultralytics",
            provider_version="test",
            class_map_json={"mapping": {"coral": label_class_id}},
            input_size_json={"width": 640, "height": 640},
            metadata_json={},
        )
        job = Job(
            project_id=str(project["id"]),
            job_type="inference",
            status="succeeded",
            progress_current=len(confidence_by_image),
            progress_total=len(confidence_by_image),
            request_json={},
            result_json={},
        )
        session.add_all([model, job])
        session.flush()
        for index, (image_id, confidence) in enumerate(confidence_by_image.items()):
            session.add(
                PredictionProposal(
                    project_id=str(project["id"]),
                    image_id=image_id,
                    model_id=model.id,
                    inference_job_id=job.id,
                    model_checksum=model.sha256,
                    label_class_id=label_class_id,
                    predicted_label="coral",
                    predicted_index=0,
                    confidence=confidence,
                    x_min=1 + index,
                    y_min=2,
                    x_max=20 + index,
                    y_max=25,
                    review_status="pending",
                    inference_settings_json={"confidence": 0.01},
                    provenance_json={"source": "phase7-acceptance"},
                )
            )
        session.commit()
        return model.id


def _mark_image_reviewed(
    client: TestClient,
    project: dict[str, Any],
    image_id: str,
) -> None:
    response = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [
                {
                    "id": "6ab320fc-4fe9-487a-b480-e151d879a2fe",
                    "label_class_id": str(project["label_classes"][0]["id"]),
                    "x_min": 5,
                    "y_min": 5,
                    "x_max": 30,
                    "y_max": 25,
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["image"]["annotation_status"] == "reviewed"


def test_uncertainty_uses_real_prediction_confidence_and_explains_selection(
    client: TestClient,
) -> None:
    project = create_project(client, "Active learning uncertainty")
    low_confidence_image, high_confidence_image = _import_images(client, project["id"])
    model_id = _seed_detector_proposals(
        client,
        project,
        {
            low_confidence_image: 0.15,
            high_confidence_image: 0.92,
        },
    )

    response = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-rounds",
        json={
            "name": "Confidence-driven round",
            "strategy": "uncertainty",
            "requested_size": 1,
            "model_ids": [model_id],
        },
    )
    assert response.status_code == 201, response.text
    round_record = response.json()
    selected = round_record["selection_manifest_json"]["items"]
    assert len(selected) == 1
    assert selected[0]["image_id"] == low_confidence_image
    assert selected[0]["reason_summary"]
    assert selected[0]["score_breakdown"]
    assert selected[0]["signal_values"]
    assert len(round_record["selection_sha256"]) == 64

    duplicate = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-rounds",
        json={
            "name": "Equivalent round",
            "strategy": "uncertainty",
            "requested_size": 1,
            "model_ids": [model_id],
        },
    )
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["id"] == round_record["id"]


@pytest.mark.parametrize("strategy", ["hybrid", "uncertainty", "rare_class", "quality"])
def test_every_acquisition_strategy_emits_explainable_manifest(
    client: TestClient,
    strategy: str,
) -> None:
    project = create_project(client, f"Active learning {strategy}")
    first_image, second_image = _import_images(client, project["id"])
    model_id = _seed_detector_proposals(
        client,
        project,
        {first_image: 0.35, second_image: 0.75},
    )

    response = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-rounds",
        json={
            "name": f"{strategy} round",
            "strategy": strategy,
            "requested_size": 1,
            "model_ids": [model_id],
        },
    )
    assert response.status_code == 201, response.text
    item = response.json()["selection_manifest_json"]["items"][0]
    assert item["reason_summary"]
    assert isinstance(item["score_breakdown"], list)
    assert isinstance(item["signal_values"], dict)


def test_completed_review_creates_idempotent_feedback_dataset(
    client: TestClient,
) -> None:
    project = create_project(client, "Active learning feedback")
    low_confidence_image, high_confidence_image = _import_images(client, project["id"])
    model_id = _seed_detector_proposals(
        client,
        project,
        {
            low_confidence_image: 0.10,
            high_confidence_image: 0.95,
        },
    )
    response = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-rounds",
        json={
            "name": "Feedback round",
            "strategy": "uncertainty",
            "requested_size": 1,
            "model_ids": [model_id],
        },
    )
    assert response.status_code == 201, response.text
    round_record = response.json()
    selected = round_record["selection_manifest_json"]["items"][0]
    assert selected["image_id"] == low_confidence_image

    item_id = selected["queue_item_id"]
    completed = client.post(f"/api/v1/review-queue-items/{item_id}/complete")
    assert completed.status_code == 200, completed.text

    feedback = client.get(f"/api/v1/active-learning-rounds/{round_record['id']}/feedback")
    assert feedback.status_code == 200, feedback.text
    assert feedback.json()["completed_count"] == 1
    assert feedback.json()["completion_fraction"] == 1.0
    assert feedback.json()["feedback_dataset_version_id"] is None

    premature = client.post(f"/api/v1/active-learning-rounds/{round_record['id']}/complete")
    assert premature.status_code == 409, premature.text
    assert "marked reviewed" in premature.json()["detail"].lower()

    _mark_image_reviewed(client, project, low_confidence_image)
    finalized = client.post(f"/api/v1/active-learning-rounds/{round_record['id']}/complete")
    assert finalized.status_code == 200, finalized.text
    finalized_payload = finalized.json()
    assert finalized_payload["status"] == "complete"
    feedback_dataset_id = finalized_payload["feedback_summary_json"]["feedback_dataset_version_id"]
    manifest_sha256 = finalized_payload["feedback_summary_json"]["feedback_manifest_sha256"]
    assert len(feedback_dataset_id) == 36
    assert len(manifest_sha256) == 64
    assert finalized_payload["feedback_summary_json"]["completed_image_ids"] == [
        low_confidence_image
    ]

    versions = client.get(f"/api/v1/projects/{project['id']}/dataset-versions")
    assert versions.status_code == 200, versions.text
    feedback_versions = [
        version for version in versions.json() if version["id"] == feedback_dataset_id
    ]
    assert len(feedback_versions) == 1
    feedback_version = feedback_versions[0]
    assert feedback_version["status"] == "complete"
    assert feedback_version["image_count"] == 1
    assert feedback_version["annotation_count"] == 1
    assert feedback_version["manifest_sha256"] == manifest_sha256

    refreshed_feedback = client.get(f"/api/v1/active-learning-rounds/{round_record['id']}/feedback")
    assert refreshed_feedback.status_code == 200, refreshed_feedback.text
    assert refreshed_feedback.json()["feedback_dataset_version_id"] == feedback_dataset_id
    assert refreshed_feedback.json()["feedback_manifest_sha256"] == manifest_sha256

    repeated = client.post(f"/api/v1/active-learning-rounds/{round_record['id']}/complete")
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["feedback_summary_json"]["feedback_dataset_version_id"] == (
        feedback_dataset_id
    )
    versions_after_repeat = client.get(f"/api/v1/projects/{project['id']}/dataset-versions")
    assert versions_after_repeat.status_code == 200, versions_after_repeat.text
    assert (
        sum(version["id"] == feedback_dataset_id for version in versions_after_repeat.json()) == 1
    )


def test_active_learning_rejects_foreign_models(client: TestClient) -> None:
    project = create_project(client, "Active learning scope")
    import_one(client, project["id"], filename="sample.png", relative_path="sample.png")

    response = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-rounds",
        json={
            "name": "Bad model scope",
            "strategy": "hybrid",
            "requested_size": 1,
            "model_ids": ["00000000-0000-0000-0000-000000000000"],
        },
    )
    assert response.status_code == 400


@pytest.mark.parametrize("freeze_pool", [False, True])
def test_model_filtered_round_ranks_only_its_model_and_opens_only_its_budget(
    client: TestClient, freeze_pool: bool
) -> None:
    project = create_project(client, "Two detector generations")
    project_url = f"/api/v1/projects/{project['id']}"
    first, second = _import_images(client, project["id"])
    version_id = None
    if freeze_pool:
        version = client.post(
            f"{project_url}/dataset-versions",
            json={
                "name": "Acquisition pool",
                "eligible_annotation_statuses": ["unannotated"],
                "split_method": "none",
            },
        )
        assert version.status_code == 201, version.text
        version_id = version.json()["id"]
    third = import_one(
        client, project["id"], filename="third.png", relative_path="third.png", size=(90, 60)
    )["successful"][0]["image_id"]
    model = _seed_detector_proposals(
        client, project, {first: 0.30, second: 0.45, third: 0.10 if freeze_pool else 0.9}
    )
    _seed_detector_proposals(client, project, {first: 0.99, second: 0.01}, "d" * 64)
    response = client.post(
        f"{project_url}/active-learning-rounds",
        json={
            "name": "Round two",
            "strategy": "uncertainty",
            "dataset_version_id": version_id,
            "requested_size": 1,
            "model_ids": [model],
        },
    )
    assert response.status_code == 201, response.text
    round_record = response.json()
    assert [item["image_id"] for item in round_record["selection_manifest_json"]["items"]] == [
        first
    ]
    queue_url = f"/api/v1/review-queues/{round_record['review_queue_id']}"
    items = client.get(f"{queue_url}/items").json()["items"]
    assert [item["image_id"] for item in items] == [first]
    assert items[0]["model_ids_json"] == [model]
    assert items[0]["signal_values_json"]["low_mean_confidence"] == pytest.approx(0.70)
    feedback = client.get(f"/api/v1/active-learning-rounds/{round_record['id']}/feedback").json()
    assert feedback["prediction_review_counts"] == {"detection_pending": 1}
    replay = client.post(f"{queue_url}/regenerate")
    assert replay.status_code == 200, replay.text
    replay_items = client.get(f"/api/v1/review-queues/{replay.json()['id']}/items").json()["items"]
    assert [item["input_checksum"] for item in replay_items] == [items[0]["input_checksum"]]


def test_empty_model_scope_creates_no_orphan_queue(client: TestClient) -> None:
    project = create_project(client, "No proposals yet")
    _import_images(client, project["id"])
    model = _seed_detector_proposals(client, project, {})
    project_url = f"/api/v1/projects/{project['id']}"
    response = client.post(
        f"{project_url}/active-learning-rounds", json={"name": "Empty", "model_ids": [model]}
    )
    assert response.status_code == 400, response.text
    assert client.get(f"{project_url}/review-queues").json() == []


def test_scoped_acquisition_excludes_frozen_holdouts_and_rejects_other_project(
    client: TestClient,
) -> None:
    project = create_project(client, "Independent test groups")
    other = create_project(client, "Other expedition")
    project_url = f"/api/v1/projects/{project['id']}"
    training, validation = _import_images(client, project["id"])
    test_image = import_one(
        client, project["id"], filename="test.png", relative_path="test.png", size=(89, 60)
    )["successful"][0]["image_id"]
    for image, group in [(training, "training"), (validation, "validation"), (test_image, "test")]:
        assert client.patch(f"/api/v1/images/{image}", json={"group_key": group}).status_code == 200
    version = client.post(
        f"{project_url}/dataset-versions",
        json={
            "name": "Frozen split",
            "eligible_annotation_statuses": ["unannotated"],
            "split_method": "manual",
            "manual_assignments": [
                {"image_id": training, "split": "train"},
                {"image_id": validation, "split": "validation"},
                {"image_id": test_image, "split": "test"},
            ],
        },
    )
    assert version.status_code == 201, version.text
    model = _seed_detector_proposals(
        client, project, {training: 0.99, validation: 0.1, test_image: 0.01}
    )
    payload = {
        "name": "Train only",
        "dataset_version_id": version.json()["id"],
        "model_ids": [model],
    }
    response = client.post(f"{project_url}/active-learning-rounds", json=payload)
    assert response.status_code == 201, response.text
    items = response.json()["selection_manifest_json"]["items"]
    assert [item["image_id"] for item in items] == [training]
    foreign_url = f"/api/v1/projects/{other['id']}"
    assert client.post(f"{foreign_url}/active-learning-rounds", json=payload).status_code == 400
    assert (
        client.post(
            f"{foreign_url}/active-learning-rounds", json={"name": "Foreign", "model_ids": [model]}
        ).status_code
        == 400
    )
    assert client.get(f"{foreign_url}/review-queues").json() == []


def test_closed_round_keeps_feedback_at_closure_when_queue_is_revisited(client: TestClient) -> None:
    project = create_project(client, "Historical feedback")
    _import_images(client, project["id"])
    created = client.post(
        f"/api/v1/projects/{project['id']}/active-learning-rounds",
        json={"name": "No labels", "requested_size": 1},
    ).json()
    item_id = created["selection_manifest_json"]["items"][0]["queue_item_id"]
    item_url = f"/api/v1/review-queue-items/{item_id}"
    assert client.post(f"{item_url}/skip", json={"reason": "Ambiguous"}).status_code == 200
    round_url = f"/api/v1/active-learning-rounds/{created['id']}"
    closed = client.post(f"{round_url}/complete")
    assert closed.status_code == 200, closed.text
    assert client.post(f"{item_url}/return").status_code == 200
    feedback = client.get(f"{round_url}/feedback").json()
    assert feedback["status"] == "complete"
    assert feedback["completion_fraction"] == 1
    assert feedback["skipped_count"] == 1
    assert feedback["feedback_dataset_version_id"] is None


def test_project_test_groups_stay_out_of_live_and_separate_pool_rounds(client: TestClient) -> None:
    project = create_project(client, "Longitudinal test holdout")
    prefix = f"/api/v1/projects/{project['id']}"
    original, safe = _import_images(client, project["id"])

    def group(image_id: str, value: str) -> None:
        assert client.patch(f"/api/v1/images/{image_id}", json={"group_key": value}).is_success

    group(original, "held colony")
    group(safe, "other colony")
    reference = client.post(
        f"{prefix}/dataset-versions",
        json={
            "name": "Study split",
            "eligible_annotation_statuses": ["unannotated"],
            "split_method": "manual",
            "manual_assignments": [{"image_id": original, "split": "test"}],
        },
    )
    assert reference.status_code == 201, reference.text
    duplicate = import_one(
        client, project["id"], filename="renamed.png", relative_path="renamed.png"
    )
    assert duplicate["duplicates"][0]["duplicate_image_id"] == original
    group(original, "updated held colony")
    mate = import_one(
        client, project["id"], filename="later.png", relative_path="later.png", size=(91, 63)
    )["successful"][0]["image_id"]
    group(mate, "held colony")
    second_mate = import_one(
        client,
        project["id"],
        filename="renamed-colony.png",
        relative_path="renamed-colony.png",
        size=(97, 63),
    )["successful"][0]["image_id"]
    group(second_mate, "updated held colony")
    pool = client.post(
        f"{prefix}/dataset-versions",
        json={
            "name": "Separately frozen pool",
            "eligible_annotation_statuses": ["unannotated"],
            "split_method": "none",
        },
    )
    assert pool.status_code == 201, pool.text
    model = _seed_detector_proposals(
        client, project, {safe: 0.99, original: 0.01, mate: 0.01, second_mate: 0.01}
    )
    rounds = []
    for version_id in (None, pool.json()["id"]):
        result = client.post(
            f"{prefix}/active-learning-rounds",
            json={
                "name": "Holdout stays reserved",
                "dataset_version_id": version_id,
                "model_ids": [model],
                "requested_size": 10,
            },
        )
        assert result.status_code == 201, result.text
        rounds.append(result.json())
        assert [item["image_id"] for item in result.json()["selection_manifest_json"]["items"]] == [
            safe
        ]

    other = create_project(client, "Independent collection")
    matching_content, _ = _import_images(client, other["id"])
    group(matching_content, "held colony")
    other_model = _seed_detector_proposals(client, other, {matching_content: 0.01})
    selection = client.post(
        f"/api/v1/projects/{other['id']}/active-learning-rounds",
        json={"name": "Other project", "model_ids": [other_model]},
    )
    assert selection.status_code == 201, selection.text
    assert selection.json()["selection_manifest_json"]["items"][0]["image_id"] == matching_content

    for image_id in (safe, original, mate, second_mate):
        assert client.patch(
            f"/api/v1/images/{image_id}", json={"annotation_status": "reviewed"}
        ).is_success
    item = rounds[1]["selection_manifest_json"]["items"][0]
    assert client.post(f"/api/v1/review-queue-items/{item['queue_item_id']}/complete").is_success
    closed = client.post(f"/api/v1/active-learning-rounds/{rounds[1]['id']}/complete")
    assert closed.status_code == 200, closed.text
    feedback_id = closed.json()["feedback_summary_json"]["feedback_dataset_version_id"]
    assert [
        item["image_id"]
        for item in client.get(f"/api/v1/dataset-versions/{feedback_id}/items").json()
    ] == [safe]


def test_automatic_feedback_does_not_designate_reviewed_acquisitions_as_new_holdouts(
    client: TestClient,
) -> None:
    project = create_project(client, "Training feedback")
    prefix = f"/api/v1/projects/{project['id']}"
    for i in range(10):
        image = import_one(
            client, project["id"], filename=f"{i}.png", relative_path=f"{i}.png", size=(80 + i, 60)
        )
        image_id = image["successful"][0]["image_id"]
        assert client.patch(
            f"/api/v1/images/{image_id}", json={"annotation_status": "reviewed"}
        ).is_success
    created = client.post(
        f"{prefix}/active-learning-rounds",
        json={"name": "Reviewed training batch", "requested_size": 10},
    ).json()
    for item in created["selection_manifest_json"]["items"]:
        assert client.post(
            f"/api/v1/review-queue-items/{item['queue_item_id']}/complete"
        ).is_success
    result = client.post(f"/api/v1/active-learning-rounds/{created['id']}/complete")
    assert result.status_code == 200, result.text
    feedback = result.json()["feedback_summary_json"]["feedback_dataset_version_id"]
    items = client.get(f"/api/v1/dataset-versions/{feedback}/items").json()
    assert len(items) == 10
    assert {item["split"] for item in items} == {"train"}


def test_new_test_assignment_blocks_feedback_on_an_already_open_round(client: TestClient) -> None:
    project = create_project(client, "Late holdout assignment")
    prefix = f"/api/v1/projects/{project['id']}"
    _import_images(client, project["id"])
    round_record = client.post(
        f"{prefix}/active-learning-rounds", json={"name": "Earlier round", "requested_size": 1}
    ).json()
    item = round_record["selection_manifest_json"]["items"][0]
    _mark_image_reviewed(client, project, item["image_id"])
    assert client.post(f"/api/v1/review-queue-items/{item['queue_item_id']}/complete").is_success
    holdout = client.post(
        f"{prefix}/dataset-versions",
        json={
            "name": "New test set",
            "eligible_annotation_statuses": ["reviewed"],
            "split_method": "manual",
            "manual_assignments": [{"image_id": item["image_id"], "split": "test"}],
        },
    )
    assert holdout.status_code == 201, holdout.text
    complete = client.post(f"/api/v1/active-learning-rounds/{round_record['id']}/complete")
    assert complete.status_code == 409, complete.text
    assert "reserved for testing" in complete.json()["detail"]
    assert [version["id"] for version in client.get(f"{prefix}/dataset-versions").json()] == [
        holdout.json()["id"]
    ]
