from __future__ import annotations

from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.quality_control import process_quality_control_job
from reefvision.tests.test_annotations import create_project, import_one


def save_annotations(
    client: TestClient,
    image_id: str,
    *,
    base_revision: int,
    annotation_status: str,
    annotations: list[dict[str, Any]],
) -> dict[str, Any]:
    response = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": base_revision,
            "annotation_status": annotation_status,
            "annotations": annotations,
        },
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def run_quality_control(
    client: TestClient,
    project_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    create_response = client.post(
        f"/api/v1/projects/{project_id}/quality-control-runs",
        json=payload,
    )
    assert create_response.status_code == 201, create_response.text
    run = cast(dict[str, Any], create_response.json())
    app = cast(FastAPI, client.app)
    processed = process_quality_control_job(
        app.state.settings,
        app.state.session_factory,
        str(run["job_id"]),
    )
    assert processed is True
    refreshed = client.get(f"/api/v1/quality-control-runs/{run['id']}")
    assert refreshed.status_code == 200, refreshed.text
    return cast(dict[str, Any], refreshed.json())


def test_quality_control_detects_duplicate_boundary_and_small_box_issues(
    client: TestClient,
) -> None:
    project = create_project(client, "QC geometry study")
    report = import_one(client, project["id"])
    image_id = report["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]

    save_annotations(
        client,
        image_id,
        base_revision=0,
        annotation_status="reviewed",
        annotations=[
            {
                "id": "ann-1",
                "label_class_id": class_id,
                "x_min": 0,
                "y_min": 0,
                "x_max": 10,
                "y_max": 10,
            },
            {
                "id": "ann-2",
                "label_class_id": class_id,
                "x_min": 0,
                "y_min": 0,
                "x_max": 10,
                "y_max": 10,
            },
            {
                "id": "ann-3",
                "label_class_id": class_id,
                "x_min": 0,
                "y_min": 0,
                "x_max": 11,
                "y_max": 11,
            },
            {
                "id": "ann-4",
                "label_class_id": class_id,
                "x_min": 50,
                "y_min": 50,
                "x_max": 53,
                "y_max": 53,
            },
        ],
    )

    run = run_quality_control(
        client,
        project["id"],
        {
            "rule_categories": ["annotation_geometry"],
            "thresholds": {
                "small_box_min_width_px": 6,
                "small_box_min_height_px": 6,
                "near_duplicate_iou_threshold": 0.8,
                "same_class_overlap_iou_threshold": 0.7,
                "different_class_overlap_iou_threshold": 0.8,
                "boundary_touch_margin_px": 0,
                "annotation_count_mad_multiplier": 3.5,
                "class_imbalance_majority_ratio": 0.85,
                "suspicious_bulk_acceptance_min_count": 12,
                "suspicious_bulk_acceptance_window_minutes": 10,
                "overlap_spatial_cell_px": 32,
            },
        },
    )
    issues = client.get(f"/api/v1/quality-control-runs/{run['id']}/issues").json()
    rule_ids = {item["rule_id"] for item in issues["items"]}

    assert run["status"] == "succeeded"
    assert "exact_duplicate_box" in rule_ids
    assert "near_duplicate_box" in rule_ids
    assert "boundary_touching_box" in rule_ids
    assert "small_box" in rule_ids

    paged = client.get(
        f"/api/v1/quality-control-runs/{run['id']}/issues",
        params={"page": 1, "page_size": 1, "class_id": class_id},
    )
    assert paged.status_code == 200, paged.text
    paged_payload = paged.json()
    assert paged_payload["page"] == 1
    assert paged_payload["page_size"] == 1
    assert paged_payload["total"] >= 1
    assert len(paged_payload["items"]) == 1
    assert class_id in paged_payload["items"][0]["class_ids_json"]


def test_quality_control_rerun_marks_old_issue_resolved_after_fix(
    client: TestClient,
) -> None:
    project = create_project(client, "QC history study")
    report = import_one(client, project["id"])
    image_id = report["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]

    first_save = save_annotations(
        client,
        image_id,
        base_revision=0,
        annotation_status="reviewed",
        annotations=[
            {
                "id": "dup-1",
                "label_class_id": class_id,
                "x_min": 5,
                "y_min": 5,
                "x_max": 20,
                "y_max": 20,
            },
            {
                "id": "dup-2",
                "label_class_id": class_id,
                "x_min": 5,
                "y_min": 5,
                "x_max": 20,
                "y_max": 20,
            },
        ],
    )
    first_run = run_quality_control(
        client,
        project["id"],
        {"rule_categories": ["annotation_geometry"], "thresholds": {}},
    )
    first_issues = client.get(f"/api/v1/quality-control-runs/{first_run['id']}/issues").json()[
        "items"
    ]
    assert any(issue["rule_id"] == "exact_duplicate_box" for issue in first_issues)

    save_annotations(
        client,
        image_id,
        base_revision=first_save["image"]["annotation_revision"],
        annotation_status="reviewed",
        annotations=[
            {
                "id": "dup-1",
                "label_class_id": class_id,
                "x_min": 5,
                "y_min": 5,
                "x_max": 20,
                "y_max": 20,
            }
        ],
    )
    second_run = run_quality_control(
        client,
        project["id"],
        {"rule_categories": ["annotation_geometry"], "thresholds": {}},
    )
    comparison = client.get(
        f"/api/v1/quality-control-runs/{first_run['id']}/compare",
        params={"other_run_id": second_run["id"]},
    )
    assert comparison.status_code == 200, comparison.text
    payload = comparison.json()
    assert payload["resolved_count"] >= 1

    refreshed_first_issues = client.get(
        f"/api/v1/quality-control-runs/{first_run['id']}/issues"
    ).json()["items"]
    assert any(issue["status"] == "resolved_in_later_run" for issue in refreshed_first_issues)


def test_quality_control_reports_missing_group_key_and_reviewed_without_annotations(
    client: TestClient,
) -> None:
    project = create_project(client, "QC metadata study")
    report = import_one(client, project["id"])
    image_id = report["successful"][0]["image_id"]

    response = client.patch(
        f"/api/v1/images/{image_id}",
        json={"group_key": None, "annotation_status": "reviewed"},
    )
    assert response.status_code == 200, response.text

    run = run_quality_control(
        client,
        project["id"],
        {
            "rule_categories": ["annotation_semantics", "statistics"],
            "thresholds": {},
        },
    )
    issues = client.get(f"/api/v1/quality-control-runs/{run['id']}/issues").json()
    rule_ids = {item["rule_id"] for item in issues["items"]}

    assert "reviewed_without_annotations" in rule_ids
    assert "missing_group_key" in rule_ids


def test_review_queue_generation_preserves_breakdown_and_item_state_transitions(
    client: TestClient,
) -> None:
    project = create_project(client, "Queue study")
    report = import_one(client, project["id"])
    image_id = report["successful"][0]["image_id"]

    response = client.patch(
        f"/api/v1/images/{image_id}",
        json={"group_key": None, "annotation_status": "in_progress"},
    )
    assert response.status_code == 200, response.text
    baseline_image = response.json()
    run = run_quality_control(
        client,
        project["id"],
        {
            "rule_categories": ["statistics"],
            "thresholds": {},
        },
    )

    queue_response = client.post(
        f"/api/v1/projects/{project['id']}/review-queues",
        json={
            "source_quality_control_run_id": run["id"],
            "signal_weights": {
                "low_mean_confidence": 24,
                "low_min_confidence": 12,
                "pending_proposals": 14,
                "rejection_rate": 8,
                "count_disagreement": 12,
                "unresolved_qc_severity": 18,
                "rare_class_presence": 5,
                "edited_acceptance_rate": 6,
                "unreviewed_state": 10,
                "missing_group_metadata": 4,
                "incomplete_provenance": 5,
                "recent_import": 4,
                "stale_review_state": 6,
            },
        },
    )
    assert queue_response.status_code == 201, queue_response.text
    queue = queue_response.json()

    items_response = client.get(f"/api/v1/review-queues/{queue['id']}/items")
    assert items_response.status_code == 200, items_response.text
    items = items_response.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["image_id"] == image_id
    assert item["score"] > 0
    assert item["score_breakdown_json"]
    assert any(
        component["signal_id"] == "unresolved_qc_severity"
        for component in item["score_breakdown_json"]
    )

    start_response = client.post(f"/api/v1/review-queue-items/{item['id']}/start")
    assert start_response.status_code == 200, start_response.text
    assert start_response.json()["review_state"] == "in_progress"

    skip_response = client.post(
        f"/api/v1/review-queue-items/{item['id']}/skip",
        json={"reason": "Waiting for class-map clarification"},
    )
    assert skip_response.status_code == 200, skip_response.text
    assert skip_response.json()["review_state"] == "skipped"
    assert skip_response.json()["skip_reason"] == "Waiting for class-map clarification"

    return_response = client.post(f"/api/v1/review-queue-items/{item['id']}/return")
    assert return_response.status_code == 200, return_response.text
    assert return_response.json()["review_state"] == "pending"

    unconfirmed = client.post(f"/api/v1/review-queue-items/{item['id']}/complete")
    assert unconfirmed.status_code == 422, unconfirmed.text
    unchanged = client.get(f"/api/v1/review-queues/{queue['id']}/items").json()
    assert unchanged["items"][0]["review_state"] == "pending"

    complete_response = client.post(
        f"/api/v1/review-queue-items/{item['id']}/complete",
        json={"actor": "QC reviewer", "review_confirmed": True},
    )
    assert complete_response.status_code == 200, complete_response.text
    assert complete_response.json()["review_state"] == "completed"

    annotation_session = client.get(f"/api/v1/images/{image_id}/annotations").json()
    assert annotation_session["annotations"] == []
    assert (
        annotation_session["image"]["annotation_revision"] == baseline_image["annotation_revision"]
    )


def test_review_queue_is_deterministic_for_identical_inputs(client: TestClient) -> None:
    project = create_project(client, "Queue deterministic study")
    report = import_one(client, project["id"])
    image_id = report["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]

    save_annotations(
        client,
        image_id,
        base_revision=0,
        annotation_status="reviewed",
        annotations=[
            {
                "id": "ann-1",
                "label_class_id": class_id,
                "x_min": 10,
                "y_min": 5,
                "x_max": 30,
                "y_max": 25,
            }
        ],
    )
    run = run_quality_control(
        client,
        project["id"],
        {"rule_categories": ["statistics"], "thresholds": {}},
    )

    payload = {
        "source_quality_control_run_id": run["id"],
        "signal_weights": {
            "low_mean_confidence": 24,
            "low_min_confidence": 12,
            "pending_proposals": 14,
            "rejection_rate": 8,
            "count_disagreement": 12,
            "unresolved_qc_severity": 18,
            "rare_class_presence": 5,
            "edited_acceptance_rate": 6,
            "unreviewed_state": 10,
            "missing_group_metadata": 4,
            "incomplete_provenance": 5,
            "recent_import": 4,
            "stale_review_state": 6,
        },
    }
    first_queue = client.post(
        f"/api/v1/projects/{project['id']}/review-queues",
        json=payload,
    ).json()
    second_queue = client.post(
        f"/api/v1/projects/{project['id']}/review-queues",
        json=payload,
    ).json()

    first_items = client.get(f"/api/v1/review-queues/{first_queue['id']}/items").json()["items"]
    second_items = client.get(f"/api/v1/review-queues/{second_queue['id']}/items").json()["items"]
    assert first_items[0]["image_id"] == second_items[0]["image_id"]
    assert first_items[0]["score"] == second_items[0]["score"]
    assert first_items[0]["score_breakdown_json"] == second_items[0]["score_breakdown_json"]
