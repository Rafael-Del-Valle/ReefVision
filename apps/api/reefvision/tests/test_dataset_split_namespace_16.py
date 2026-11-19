"""An explicit colony group key must never collide with an image singleton key.

This is a source-level split fix exercised by the existing frozen dataset
QC service and by a persisted executable, typed Workflow Builder graph.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from reefvision.db.models import ImageAsset
from reefvision.schemas.dataset_versions import DatasetVersionPreviewRequest
from reefvision.services.dataset_versions import CandidateImage, DatasetVersionService

from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_dataset_versions import save_annotations, update_image
from reefvision.tests.test_workflow_review_queue_frozen_dataset_16 import (
    _frozen_graph,
    _run_frozen_graph,
)


def test_literal_image_prefix_group_is_independent_in_preview_and_saved_qc(
    client: TestClient,
) -> None:
    project = create_project(client, "Independent octocoral colonies")
    project_id = project["id"]
    first = import_one(
        client,
        project_id,
        filename="singleton.png",
        relative_path="colonies/singleton.png",
        size=(80, 60),
    )
    second = import_one(
        client,
        project_id,
        filename="grouped.png",
        relative_path="colonies/grouped.png",
        size=(81, 60),
    )
    singleton_id = first["successful"][0]["image_id"]
    grouped_id = second["successful"][0]["image_id"]
    assert singleton_id != grouped_id
    # Previously this group key was indistinguishable from the singleton's
    # internally generated "image:<id>" unit key.
    misleading_group_key = f"image:{singleton_id}"
    for image_id, group_key in (
        (singleton_id, None),
        (grouped_id, misleading_group_key),
    ):
        save_annotations(
            client,
            image_id,
            base_revision=0,
            annotation_status="reviewed",
            annotations=[
                {
                    "id": str(uuid4()),
                    "label_class_id": project["label_classes"][0]["id"],
                    "x_min": 5,
                    "y_min": 5,
                    "x_max": 25,
                    "y_max": 25,
                }
            ],
        )
        update_image(
            client,
            image_id,
            group_key=group_key,
            annotation_status="reviewed",
        )

    split_request = {
        "eligible_annotation_statuses": ["reviewed"],
        "split_method": "manual",
        "manual_assignments": [
            {"image_id": singleton_id, "split": "train"},
            {"image_id": grouped_id, "split": "test"},
        ],
    }
    preview_url = f"/api/v1/projects/{project_id}/dataset-version-previews"
    preview = client.post(preview_url, json=split_request)
    assert preview.status_code == 200, preview.text
    assert preview.json()["missing_group_key_count"] == 1
    proposed = {image["image_id"]: image["proposed_split"] for image in preview.json()["images"]}
    assert proposed == {singleton_id: "train", grouped_id: "test"}

    created = client.post(
        f"/api/v1/projects/{project_id}/dataset-versions",
        json={**split_request, "name": "Distinct colonies, distinct manual splits"},
    )
    assert created.status_code == 201, created.text
    version_id = created.json()["id"]
    assert created.json()["missing_group_key_count"] == 1
    assert created.json()["achieved_ratios_json"] == {
        "train": 0.5,
        "validation": 0.0,
        "test": 0.5,
    }
    frozen_items = client.get(f"/api/v1/dataset-versions/{version_id}/items")
    assert frozen_items.status_code == 200, frozen_items.text
    assert {item["image_id"]: item["split"] for item in frozen_items.json()} == proposed

    standalone = client.post(f"/api/v1/dataset-versions/{version_id}/review-queues", json={})
    assert standalone.status_code == 201, standalone.text
    graph = _frozen_graph(version_id)
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] and plan.json()["executable"]
    saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text

    first_run, first_output = _run_frozen_graph(client, project_id, saved.json()["id"])
    next_run, next_output = _run_frozen_graph(client, project_id, saved.json()["id"])
    assert first_run != next_run
    assert first_output["dataset_version_id"] == version_id
    assert first_output["dataset_manifest_sha256"] == created.json()["manifest_sha256"]
    assert next_output["dataset_manifest_sha256"] == first_output["dataset_manifest_sha256"]
    for queue_id in (
        standalone.json()["id"],
        first_output["queue_id"],
        next_output["queue_id"],
    ):
        items = client.get(f"/api/v1/review-queues/{queue_id}/items")
        assert items.status_code == 200, items.text
        assert items.json()["total"] == 2
        assert all(item["review_state"] == "pending" for item in items.json()["items"])
    assert first_output["priority_score_unit"] == "dimensionless"
    assert first_output["review_status"] == "requires_researcher_review"

def test_collision_safe_seeded_group_random_is_independent_of_candidate_order() -> None:
    """An arbitrary import order must not change a seeded study split."""
    singleton_id = "00000000-0000-0000-0000-000000000001"
    grouped_id = "00000000-0000-0000-0000-000000000002"
    singleton = CandidateImage(
        image=ImageAsset(id=singleton_id, group_key=None),
        annotations=[],
        per_class_counts={},
    )
    grouped = CandidateImage(
        image=ImageAsset(id=grouped_id, group_key=f"image:{singleton_id}"),
        annotations=[],
        per_class_counts={},
    )
    # _plan_splits is a pure in-memory operation for a request with no parent.
    service = DatasetVersionService.__new__(DatasetVersionService)
    request = DatasetVersionPreviewRequest(
        split_method="group_random",
        split_seed=7,
    )
    forward = service._plan_splits([singleton, grouped], request)
    backward = service._plan_splits([grouped, singleton], request)
    assert forward.assignments == backward.assignments
    assert set(forward.assignments.values()) == {"train", "validation"}
    assert forward.missing_group_key_count == backward.missing_group_key_count == 1
