"""An explicit colony group key must never collide with an image singleton key.

This is a source-level split fix exercised by the existing frozen dataset
QC service and by a persisted executable, typed Workflow Builder graph.
"""

from __future__ import annotations

from typing import cast
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import DatasetVersionItem, ImageAsset
from reefvision.schemas.dataset_versions import DatasetVersionPreviewRequest
from reefvision.services.dataset_versions import CandidateImage, DatasetVersionService
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_dataset_versions import save_annotations, update_image
from reefvision.tests.test_workflow_review_queue_frozen_dataset_16 import (
    _frozen_graph,
    _run_frozen_graph,
    _study,
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


def test_manual_assignments_cannot_silently_ignore_ineligible_images_or_mutate_saved_qc(
    client: TestClient,
) -> None:
    """Rejected explicit split choices never alter an existing reviewed study."""
    project = create_project(client, "Explicit colony selection")
    project_id = project["id"]
    other_project = create_project(client, "Different independent study")
    # The import helper produces identical bytes for identical dimensions.
    # Use distinct source images so content-deduplication cannot drop one.
    reviewed_id = import_one(
        client,
        project_id,
        filename="reviewed.png",
        relative_path="cohort/reviewed.png",
        size=(80, 60),
    )["successful"][0]["image_id"]
    excluded_id = import_one(
        client,
        project_id,
        filename="excluded.png",
        relative_path="cohort/excluded.png",
        size=(81, 60),
    )["successful"][0]["image_id"]
    foreign_id = import_one(
        client,
        other_project["id"],
        filename="foreign.png",
        relative_path="foreign/foreign.png",
        size=(82, 60),
    )["successful"][0]["image_id"]
    save_annotations(
        client,
        reviewed_id,
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
    update_image(client, reviewed_id, group_key=None, annotation_status="reviewed")
    update_image(client, excluded_id, group_key=None, annotation_status="excluded")
    update_image(client, foreign_id, group_key=None, annotation_status="reviewed")

    valid_request = {
        "eligible_annotation_statuses": ["reviewed"],
        "split_method": "manual",
        "manual_assignments": [{"image_id": reviewed_id, "split": "train"}],
    }
    preview_url = f"/api/v1/projects/{project_id}/dataset-version-previews"
    version_url = f"/api/v1/projects/{project_id}/dataset-versions"
    valid_preview = client.post(preview_url, json=valid_request)
    assert valid_preview.status_code == 200, valid_preview.text
    assert len(valid_preview.json()["images"]) == 1
    created = client.post(version_url, json={**valid_request, "name": "Approved subset"})
    assert created.status_code == 201, created.text
    version_id = created.json()["id"]

    graph = _frozen_graph(version_id)
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] and plan.json()["executable"]
    saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    first_run, first_output = _run_frozen_graph(client, project_id, saved.json()["id"])

    for invalid_id in (str(uuid4()), excluded_id, foreign_id):
        request = {
            **valid_request,
            "manual_assignments": [
                {"image_id": reviewed_id, "split": "train"},
                {"image_id": invalid_id, "split": "test"},
            ],
        }
        for endpoint, payload in (
            (preview_url, request),
            (version_url, {**request, "name": "Reject invalid cohort"}),
        ):
            rejected = client.post(endpoint, json=payload)
            assert rejected.status_code == 400, rejected.text
            assert "eligible images" in rejected.json()["detail"]

    # Even identical split values must not quietly collapse duplicate
    # researcher instructions into a single immutable cohort decision.
    for repeated_split, expected_error in (
        ("train", "duplicate image"),
        ("test", "conflict"),
    ):
        duplicate_request = {
            **valid_request,
            "manual_assignments": [
                {"image_id": reviewed_id, "split": "train"},
                {"image_id": reviewed_id, "split": repeated_split},
            ],
        }
        for endpoint, payload in (
            (preview_url, duplicate_request),
            (version_url, {**duplicate_request, "name": "Reject duplicate intent"}),
        ):
            rejected = client.post(endpoint, json=payload)
            assert rejected.status_code == 400, rejected.text
            assert expected_error in rejected.json()["detail"]

    versions = client.get(version_url)
    assert versions.status_code == 200, versions.text
    assert [version["id"] for version in versions.json()] == [version_id]
    second_run, second_output = _run_frozen_graph(client, project_id, saved.json()["id"])
    assert second_run != first_run
    assert second_output["dataset_manifest_sha256"] == first_output["dataset_manifest_sha256"]
    assert second_output["dataset_version_id"] == first_output["dataset_version_id"] == version_id
    for output in (first_output, second_output):
        assert output["priority_score_unit"] == "dimensionless"
        assert output["review_status"] == "requires_researcher_review"
        queued = client.get(f"/api/v1/review-queues/{output['queue_id']}/items")
        assert queued.status_code == 200, queued.text
        assert queued.json()["total"] == 1
        assert queued.json()["items"][0]["review_state"] == "pending"


def test_blank_legacy_biological_group_cannot_pool_samples_or_rewrite_saved_qc(
    client: TestClient,
) -> None:
    """Fail closed on legacy blank colony IDs, preserving frozen reviewed evidence."""
    project_id, image_id, version_id, _ = _study(client)
    graph = _frozen_graph(version_id)
    planned = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert planned.status_code == 200, planned.text
    assert planned.json()["valid"] and planned.json()["executable"]
    saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text

    standalone = client.post(f"/api/v1/dataset-versions/{version_id}/review-queues", json={})
    assert standalone.status_code == 201, standalone.text
    first_run, first_output = _run_frozen_graph(client, project_id, saved.json()["id"])

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        image = session.get(ImageAsset, image_id)
        assert image is not None
        original_group_key = image.group_key
        image.group_key = "   "
        session.commit()

    request = {
        "eligible_annotation_statuses": ["reviewed"],
        "split_method": "random",
        "split_seed": 19,
    }
    preview_url = f"/api/v1/projects/{project_id}/dataset-version-previews"
    versions_url = f"/api/v1/projects/{project_id}/dataset-versions"
    for endpoint, payload in (
        (preview_url, request),
        (versions_url, {**request, "name": "Reject blank biological group"}),
    ):
        refused = client.post(endpoint, json=payload)
        assert refused.status_code == 400, refused.text
        assert "Empty biological group keys" in refused.json()["detail"]
    listed = client.get(versions_url)
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()] == [version_id]

    # The invalid *live* metadata cannot contaminate an immutable study.
    # Both standalone and replayed saved QC retain explicit human review.
    next_run, next_output = _run_frozen_graph(client, project_id, saved.json()["id"])
    assert first_run != next_run
    assert next_output["dataset_version_id"] == first_output["dataset_version_id"] == version_id
    assert next_output["dataset_manifest_sha256"] == first_output["dataset_manifest_sha256"]
    for output in (first_output, next_output):
        assert output["priority_score_unit"] == "dimensionless"
        assert output["review_status"] == "requires_researcher_review"
    for queue_id in (standalone.json()["id"], first_output["queue_id"], next_output["queue_id"]):
        queued = client.get(f"/api/v1/review-queues/{queue_id}/items")
        assert queued.status_code == 200, queued.text
        assert queued.json()["total"] == 1
        assert queued.json()["items"][0]["review_state"] == "pending"

    # Restore the disposable direct-DB mutation; regular API writes already
    # normalize empty and whitespace-only group keys to None.
    with app.state.session_factory() as session:
        image = session.get(ImageAsset, image_id)
        assert image is not None
        image.group_key = original_group_key
        session.commit()
    recovered = client.post(preview_url, json=request)
    assert recovered.status_code == 200, recovered.text


def test_parent_reuse_refuses_modified_frozen_holdout_and_preserves_saved_qc(
    client: TestClient,
) -> None:
    """No child may inherit a forged parent train/test assignment."""
    project_id, image_id, parent_id, _ = _study(client)
    request = {
        "parent_version_id": parent_id,
        "reuse_parent_assignments": True,
        "eligible_annotation_statuses": ["reviewed"],
        "split_method": "group_random",
        "split_seed": 11,
    }
    preview_url = f"/api/v1/projects/{project_id}/dataset-version-previews"
    versions_url = f"/api/v1/projects/{project_id}/dataset-versions"
    parent_items = client.get(f"/api/v1/dataset-versions/{parent_id}/items")
    assert parent_items.status_code == 200, parent_items.text
    original_split = parent_items.json()[0]["split"]
    initial = client.post(preview_url, json=request)
    assert initial.status_code == 200, initial.text
    assert initial.json()["images"][0]["proposed_split"] == original_split

    standalone = client.post(f"/api/v1/dataset-versions/{parent_id}/review-queues", json={})
    assert standalone.status_code == 201, standalone.text
    graph = _frozen_graph(parent_id)
    planned = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert planned.status_code == 200, planned.text
    assert planned.json()["valid"] and planned.json()["executable"]
    saved = client.post(f"/api/v1/projects/{project_id}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    first_run, first_output = _run_frozen_graph(client, project_id, saved.json()["id"])

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        parent_item = session.scalar(
            select(DatasetVersionItem).where(
                DatasetVersionItem.dataset_version_id == parent_id,
                DatasetVersionItem.image_id == image_id,
            )
        )
        assert parent_item is not None
        parent_item.split = "test" if original_split != "test" else "train"
        session.commit()

    # A forged complete parent cannot silently supply a child holdout.
    for endpoint, payload in (
        (preview_url, request),
        (versions_url, {**request, "name": "Forged inherited holdout"}),
    ):
        rejected = client.post(endpoint, json=payload)
        assert rejected.status_code == 400, rejected.text
        assert "original manifest" in rejected.json()["detail"]
    versions = client.get(versions_url)
    assert versions.status_code == 200, versions.text
    assert [item["id"] for item in versions.json()] == [parent_id]

    # Restore only the disposable test mutation. Saved QC and child lineage
    # must use exactly the original evidence and still require a human review.
    with app.state.session_factory() as session:
        parent_item = session.scalar(
            select(DatasetVersionItem).where(
                DatasetVersionItem.dataset_version_id == parent_id,
                DatasetVersionItem.image_id == image_id,
            )
        )
        assert parent_item is not None
        parent_item.split = original_split
        session.commit()
    recovered = client.post(preview_url, json=request)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["images"][0]["proposed_split"] == original_split
    child = client.post(versions_url, json={**request, "name": "Verified inherited holdout"})
    assert child.status_code == 201, child.text
    child_items = client.get(f"/api/v1/dataset-versions/{child.json()['id']}/items")
    assert child_items.status_code == 200, child_items.text
    assert child_items.json()[0]["split"] == original_split
    second_run, second_output = _run_frozen_graph(client, project_id, saved.json()["id"])
    assert first_run != second_run
    assert first_output["dataset_version_id"] == second_output["dataset_version_id"] == parent_id
    assert first_output["dataset_manifest_sha256"] == second_output["dataset_manifest_sha256"]
    assert (
        first_output["priority_score_unit"]
        == second_output["priority_score_unit"]
        == "dimensionless"
    )
    assert (
        first_output["review_status"]
        == second_output["review_status"]
        == "requires_researcher_review"
    )
    for queue_id in (standalone.json()["id"], first_output["queue_id"], second_output["queue_id"]):
        queued = client.get(f"/api/v1/review-queues/{queue_id}/items")
        assert queued.status_code == 200, queued.text
        assert queued.json()["total"] == 1
        assert queued.json()["items"][0]["review_state"] == "pending"
