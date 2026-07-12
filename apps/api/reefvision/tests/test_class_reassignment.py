from datetime import UTC, datetime
from typing import Any, cast

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.db.models import (
    Annotation,
    AnnotationEvent,
    ClassOperation,
    DatasetVersion,
    ImageAsset,
    Job,
    LabelClass,
    ModelRegistration,
    PredictionProposal,
    QualityControlIssue,
    QualityControlRun,
    ReviewQueue,
    ReviewQueueItem,
)


def create_project(client: TestClient, **overrides: object) -> dict[str, Any]:
    payload: dict[str, object] = {"name": "Reassignment Study", "template": "blank"}
    payload.update(overrides)
    response = client.post("/api/v1/projects", json=payload)
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def create_label_class(
    client: TestClient,
    project_id: str,
    *,
    class_index: int,
    name: str,
    display_color: str,
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/projects/{project_id}/classes",
        json={
            "class_index": class_index,
            "name": name,
            "display_color": display_color,
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def seed_reassignment_records(
    client: TestClient,
    project: dict[str, Any],
    source_class: dict[str, Any],
    target_class: dict[str, Any],
    *,
    include_deleted_annotation: bool = True,
    include_historical_prediction: bool = True,
) -> None:
    with Session(client.app.state.engine) as session:
        image = ImageAsset(
            id="image-1",
            project_id=project["id"],
            original_filename="reef.png",
            managed_path=f"{project['storage_root']}/images/originals/image-1.png",
            thumbnail_path=None,
            sha256="a" * 64,
            width_px=1600,
            height_px=1200,
            file_size_bytes=1024,
            media_type="image/png",
            import_source="fixture/reef.png",
            annotation_status="in_progress",
            annotation_revision=2,
            metadata_json={},
        )
        active_annotation = Annotation(
            id="annotation-active",
            image_id=image.id,
            label_class_id=source_class["id"],
            x_min=10,
            y_min=20,
            x_max=100,
            y_max=140,
        )
        session.add(image)
        session.add(active_annotation)
        if include_deleted_annotation:
            session.add(
                Annotation(
                    id="annotation-deleted",
                    image_id=image.id,
                    label_class_id=source_class["id"],
                    x_min=30,
                    y_min=40,
                    x_max=150,
                    y_max=190,
                    deleted_at=datetime.now(UTC),
                )
            )
        session.add(
            AnnotationEvent(
                id="annotation-event-1",
                annotation_id=active_annotation.id,
                image_id=image.id,
                event_type="created",
                before_json=None,
                after_json={"label_class_id": source_class["id"]},
                actor="local_user",
            )
        )
        inference_job = Job(
            id="job-inference-1",
            project_id=project["id"],
            job_type="inference",
            status="queued",
            progress_total=1,
            request_json={},
        )
        qc_job = Job(
            id="job-qc-1",
            project_id=project["id"],
            job_type="qc",
            status="queued",
            progress_total=1,
            request_json={},
        )
        model = ModelRegistration(
            id="model-1",
            project_id=project["id"],
            purpose="detector",
            display_name="Fixture detector",
            source_filename="fixture.pt",
            managed_path=f"{project['storage_root']}/models/model-1.pt",
            sha256="b" * 64,
            file_size_bytes=2048,
            framework="ultralytics",
            task="detect",
            provider_name="ultralytics",
            provider_version="8.3.228",
            class_map_json={
                "labels": [source_class["name"], target_class["name"]],
                "mapping": {
                    source_class["name"]: source_class["id"],
                    target_class["name"]: target_class["id"],
                },
            },
            metadata_json={},
        )
        session.add_all([inference_job, qc_job, model])
        session.add(
            PredictionProposal(
                id="proposal-pending",
                project_id=project["id"],
                image_id=image.id,
                model_id=model.id,
                inference_job_id=inference_job.id,
                model_checksum="c" * 64,
                label_class_id=source_class["id"],
                predicted_label=source_class["name"],
                predicted_index=0,
                confidence=0.88,
                x_min=20,
                y_min=30,
                x_max=120,
                y_max=150,
                review_status="pending",
            )
        )
        if include_historical_prediction:
            session.add(
                PredictionProposal(
                    id="proposal-accepted",
                    project_id=project["id"],
                    image_id=image.id,
                    model_id=model.id,
                    inference_job_id=inference_job.id,
                    model_checksum="d" * 64,
                    label_class_id=source_class["id"],
                    predicted_label=source_class["name"],
                    predicted_index=0,
                    confidence=0.93,
                    x_min=40,
                    y_min=60,
                    x_max=180,
                    y_max=220,
                    review_status="accepted",
                    accepted_annotation_id=active_annotation.id,
                )
            )

        qc_run = QualityControlRun(
            id="qc-run-1",
            project_id=project["id"],
            dataset_version_id=None,
            job_id=qc_job.id,
            scope_type="project",
            status="succeeded",
            rule_categories_json=["annotation_semantics"],
            selected_rule_ids_json=["missing_or_invalid_class"],
            thresholds_json={},
            configuration_json={
                "selected_class_ids": [source_class["id"]],
                "selected_image_ids": [],
            },
            input_checksums_json={},
            issue_count=2,
            summary_json={},
            created_by="local_user",
        )
        open_issue = QualityControlIssue(
            id="qc-issue-open",
            quality_control_run_id=qc_run.id,
            project_id=project["id"],
            dataset_version_id=None,
            image_id=image.id,
            rule_id="missing_or_invalid_class",
            rule_version="1",
            severity="warning",
            status="open",
            fingerprint="f" * 64,
            title="Open issue",
            explanation="Needs review",
            class_ids_json=[source_class["id"]],
        )
        dismissed_issue = QualityControlIssue(
            id="qc-issue-dismissed",
            quality_control_run_id=qc_run.id,
            project_id=project["id"],
            dataset_version_id=None,
            image_id=image.id,
            rule_id="missing_or_invalid_class",
            rule_version="1",
            severity="info",
            status="dismissed",
            fingerprint="e" * 64,
            title="Dismissed issue",
            explanation="Historical note",
            class_ids_json=[source_class["id"]],
            dismissed_at=datetime.now(UTC),
            dismissed_by="local_user",
            dismissed_reason="expected",
        )
        session.add_all([qc_run, open_issue, dismissed_issue])

        review_queue = ReviewQueue(
            id="queue-1",
            project_id=project["id"],
            dataset_version_id=None,
            source_quality_control_run_id=qc_run.id,
            status="completed",
            scope_type="project",
            formula_id="qc_priority",
            formula_version="1",
            configuration_json={},
            input_checksums_json={},
            summary_json={},
            item_count=2,
            created_by="local_user",
            completed_at=datetime.now(UTC),
        )
        pending_item = ReviewQueueItem(
            id="queue-item-pending",
            review_queue_id=review_queue.id,
            project_id=project["id"],
            dataset_version_id=None,
            image_id=image.id,
            review_state="pending",
            score=0.9,
            rank_position=1,
            label_class_ids_json=[source_class["id"]],
            model_ids_json=[model.id],
            related_issue_ids_json=[open_issue.id],
            signal_values_json={},
            normalized_signals_json={},
            weights_json={},
            score_breakdown_json=[],
            input_checksum="g" * 64,
        )
        completed_item = ReviewQueueItem(
            id="queue-item-completed",
            review_queue_id=review_queue.id,
            project_id=project["id"],
            dataset_version_id=None,
            image_id=image.id,
            review_state="completed",
            score=0.7,
            rank_position=2,
            label_class_ids_json=[source_class["id"]],
            model_ids_json=[model.id],
            related_issue_ids_json=[dismissed_issue.id],
            signal_values_json={},
            normalized_signals_json={},
            weights_json={},
            score_breakdown_json=[],
            input_checksum="h" * 64,
            completed_at=datetime.now(UTC),
        )
        session.add_all([review_queue, pending_item, completed_item])

        session.add(
            DatasetVersion(
                id="dataset-version-1",
                project_id=project["id"],
                version_number=1,
                name="Baseline export",
                notes=None,
                parent_version_id=None,
                status="complete",
                requested_split_method="group_random",
                resolved_split_method="group_random",
                eligible_annotation_statuses_json=["reviewed"],
                requested_ratios_json={"train": 0.7, "validation": 0.2, "test": 0.1},
                achieved_ratios_json={"train": 0.67, "validation": 0.33, "test": 0.0},
                split_seed=11,
                reuse_parent_assignments=False,
                missing_group_key_count=0,
                warnings_json=[],
                class_map_json=[
                    {"id": source_class["id"], "name": source_class["name"], "index": 0},
                    {"id": target_class["id"], "name": target_class["name"], "index": 1},
                ],
                manifest_json={},
                manifest_sha256="i" * 64,
                image_count=1,
                annotation_count=1,
                created_by="local_user",
                reefvision_version="1.6.0",
                schema_version="0010",
                created_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
        )
        session.commit()


def test_reassign_preview_and_execution_updates_only_mutable_records(client: TestClient) -> None:
    project = create_project(client)
    source_class = create_label_class(
        client,
        project["id"],
        class_index=0,
        name="Muricea Closed",
        display_color="#E76F51",
    )
    target_class = create_label_class(
        client,
        project["id"],
        class_index=1,
        name="Muricea Open",
        display_color="#2A9D8F",
    )
    seed_reassignment_records(client, project, source_class, target_class)

    preview = client.post(
        f"/api/v1/projects/{project['id']}/classes/{source_class['id']}/reassign/preview",
        json={"target_class_id": target_class["id"], "notes": "Preview reassign"},
    )
    assert preview.status_code == 201, preview.text
    preview_payload = preview.json()
    assert preview_payload["status"] == "previewed"
    assert preview_payload["operation_type"] == "reassign"
    assert preview_payload["preview_checksum"]
    mutable_groups = {item["key"]: item for item in preview_payload["plan"]["mutable_records"]}
    assert mutable_groups["annotations_active"]["record_ids"] == ["annotation-active"]
    assert mutable_groups["prediction_proposals_pending"]["record_ids"] == ["proposal-pending"]
    assert mutable_groups["quality_control_issues_open"]["record_ids"] == ["qc-issue-open"]
    assert mutable_groups["review_queue_items_open"]["record_ids"] == ["queue-item-pending"]
    protected_groups = {item["key"]: item for item in preview_payload["plan"]["protected_records"]}
    assert protected_groups["annotations_deleted"]["record_ids"] == ["annotation-deleted"]
    assert protected_groups["prediction_proposals_historical"]["record_ids"] == [
        "proposal-accepted"
    ]
    assert protected_groups["dataset_versions"]["record_ids"] == ["dataset-version-1"]
    assert protected_groups["model_registrations"]["record_ids"] == ["model-1"]

    execute = client.post(
        f"/api/v1/projects/{project['id']}/classes/{source_class['id']}/reassign",
        json={
            "operation_id": preview_payload["id"],
            "preview_checksum": preview_payload["preview_checksum"],
            "notes": "Run reassign",
        },
    )
    assert execute.status_code == 200, execute.text
    execute_payload = execute.json()
    assert execute_payload["status"] == "completed"
    assert execute_payload["final_state"] == "reassigned"

    with Session(client.app.state.engine) as session:
        active_annotation = session.get(Annotation, "annotation-active")
        deleted_annotation = session.get(Annotation, "annotation-deleted")
        pending_proposal = session.get(PredictionProposal, "proposal-pending")
        accepted_proposal = session.get(PredictionProposal, "proposal-accepted")
        open_issue = session.get(QualityControlIssue, "qc-issue-open")
        dismissed_issue = session.get(QualityControlIssue, "qc-issue-dismissed")
        pending_item = session.get(ReviewQueueItem, "queue-item-pending")
        completed_item = session.get(ReviewQueueItem, "queue-item-completed")
        dataset_version = session.get(DatasetVersion, "dataset-version-1")
        model = session.get(ModelRegistration, "model-1")
        latest_operation = session.get(ClassOperation, preview_payload["id"])
        events = list(
            session.scalars(
                select(AnnotationEvent).where(AnnotationEvent.annotation_id == "annotation-active")
            )
        )

        assert active_annotation is not None
        assert deleted_annotation is not None
        assert pending_proposal is not None
        assert accepted_proposal is not None
        assert open_issue is not None
        assert dismissed_issue is not None
        assert pending_item is not None
        assert completed_item is not None
        assert dataset_version is not None
        assert model is not None
        assert latest_operation is not None

        assert active_annotation.label_class_id == target_class["id"]
        assert deleted_annotation.label_class_id == source_class["id"]
        assert pending_proposal.label_class_id == target_class["id"]
        assert accepted_proposal.label_class_id == source_class["id"]
        assert open_issue.class_ids_json == [target_class["id"]]
        assert dismissed_issue.class_ids_json == [source_class["id"]]
        assert pending_item.label_class_ids_json == [target_class["id"]]
        assert completed_item.label_class_ids_json == [source_class["id"]]
        assert dataset_version.class_map_json[0]["id"] == source_class["id"]
        assert model.class_map_json["mapping"][source_class["name"]] == source_class["id"]
        assert any(event.event_type == "class_reassigned" for event in events)
        assert latest_operation.status == "completed"

    fetched_operation = client.get(f"/api/v1/class-operations/{preview_payload['id']}")
    assert fetched_operation.status_code == 200, fetched_operation.text
    assert fetched_operation.json()["status"] == "completed"


def test_reassign_preview_checksum_blocks_scope_drift(client: TestClient) -> None:
    project = create_project(client, name="Drift Study")
    source_class = create_label_class(
        client,
        project["id"],
        class_index=0,
        name="Source",
        display_color="#E76F51",
    )
    target_class = create_label_class(
        client,
        project["id"],
        class_index=1,
        name="Target",
        display_color="#2A9D8F",
    )
    seed_reassignment_records(
        client,
        project,
        source_class,
        target_class,
        include_deleted_annotation=False,
        include_historical_prediction=False,
    )

    preview = client.post(
        f"/api/v1/projects/{project['id']}/classes/{source_class['id']}/reassign/preview",
        json={"target_class_id": target_class["id"]},
    )
    assert preview.status_code == 201, preview.text
    preview_payload = preview.json()

    with Session(client.app.state.engine) as session:
        session.add(
            Annotation(
                id="annotation-new",
                image_id="image-1",
                label_class_id=source_class["id"],
                x_min=200,
                y_min=220,
                x_max=320,
                y_max=360,
            )
        )
        session.commit()

    execute = client.post(
        f"/api/v1/projects/{project['id']}/classes/{source_class['id']}/reassign",
        json={
            "operation_id": preview_payload["id"],
            "preview_checksum": preview_payload["preview_checksum"],
        },
    )
    assert execute.status_code == 409
    assert "stale" in execute.json()["detail"].lower()


def test_reassign_delete_reports_blocking_historical_references(client: TestClient) -> None:
    project = create_project(client, name="Delete Blocked")
    source_class = create_label_class(
        client,
        project["id"],
        class_index=0,
        name="Source",
        display_color="#E76F51",
    )
    target_class = create_label_class(
        client,
        project["id"],
        class_index=1,
        name="Target",
        display_color="#2A9D8F",
    )
    seed_reassignment_records(client, project, source_class, target_class)

    preview = client.post(
        f"/api/v1/projects/{project['id']}/classes/{source_class['id']}/reassign-delete/preview",
        json={"target_class_id": target_class["id"]},
    )
    assert preview.status_code == 201, preview.text
    preview_payload = preview.json()
    assert preview_payload["operation_type"] == "reassign_delete"
    assert preview_payload["plan"]["blockers"]
    blocking_keys = {item["key"] for item in preview_payload["plan"]["blocking_records"]}
    assert "annotations_deleted" in blocking_keys
    assert "prediction_proposals_historical" in blocking_keys

    execute = client.post(
        f"/api/v1/projects/{project['id']}/classes/{source_class['id']}/reassign-delete",
        json={
            "operation_id": preview_payload["id"],
            "preview_checksum": preview_payload["preview_checksum"],
        },
    )
    assert execute.status_code == 409
    assert "blocked" in execute.json()["detail"].lower()


def test_reassign_delete_deletes_source_after_safe_reassignment(client: TestClient) -> None:
    project = create_project(client, name="Delete Success")
    source_class = create_label_class(
        client,
        project["id"],
        class_index=0,
        name="Source",
        display_color="#E76F51",
    )
    target_class = create_label_class(
        client,
        project["id"],
        class_index=1,
        name="Target",
        display_color="#2A9D8F",
    )
    seed_reassignment_records(
        client,
        project,
        source_class,
        target_class,
        include_deleted_annotation=False,
        include_historical_prediction=False,
    )

    preview = client.post(
        f"/api/v1/projects/{project['id']}/classes/{source_class['id']}/reassign-delete/preview",
        json={"target_class_id": target_class["id"], "notes": "Safe delete"},
    )
    assert preview.status_code == 201, preview.text
    preview_payload = preview.json()
    assert preview_payload["plan"]["blockers"] == []

    execute = client.post(
        f"/api/v1/projects/{project['id']}/classes/{source_class['id']}/reassign-delete",
        json={
            "operation_id": preview_payload["id"],
            "preview_checksum": preview_payload["preview_checksum"],
        },
    )
    assert execute.status_code == 200, execute.text
    execute_payload = execute.json()
    assert execute_payload["status"] == "completed"
    assert execute_payload["final_state"] == "reassigned_and_deleted"
    assert execute_payload["source_class"]["name"] == source_class["name"]

    with Session(client.app.state.engine) as session:
        assert session.get(LabelClass, source_class["id"]) is None
        active_annotation = session.get(Annotation, "annotation-active")
        pending_proposal = session.get(PredictionProposal, "proposal-pending")
        open_issue = session.get(QualityControlIssue, "qc-issue-open")
        pending_item = session.get(ReviewQueueItem, "queue-item-pending")
        dataset_version = session.get(DatasetVersion, "dataset-version-1")
        model = session.get(ModelRegistration, "model-1")
        operation = session.get(ClassOperation, preview_payload["id"])

        assert active_annotation is not None
        assert pending_proposal is not None
        assert open_issue is not None
        assert pending_item is not None
        assert dataset_version is not None
        assert model is not None
        assert operation is not None
        assert active_annotation.label_class_id == target_class["id"]
        assert pending_proposal.label_class_id == target_class["id"]
        assert open_issue.class_ids_json == [target_class["id"]]
        assert pending_item.label_class_ids_json == [target_class["id"]]
        assert dataset_version.class_map_json[0]["id"] == source_class["id"]
        assert model.class_map_json["mapping"][source_class["name"]] == source_class["id"]
        assert operation.status == "completed"
