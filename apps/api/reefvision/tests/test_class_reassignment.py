from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fastapi import FastAPI
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
from reefvision.services import class_operations as class_operations_module
from reefvision.services.class_operations import ClassOperationsService


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
    with Session(cast(FastAPI, client.app).state.engine) as session:
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
                reefvision_version="1.0.1",
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

    with Session(cast(FastAPI, client.app).state.engine) as session:
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

    with Session(cast(FastAPI, client.app).state.engine) as session:
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

    with Session(cast(FastAPI, client.app).state.engine) as session:
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


@pytest.mark.parametrize("operation_type", ["reassign", "reassign-delete"])
@pytest.mark.parametrize("changed_role", ["source", "target"])
@pytest.mark.parametrize("changed_field", ["name", "scientific_name", "state_name"])
def test_class_operation_preview_expires_after_biological_identity_change(
    client: TestClient,
    operation_type: str,
    changed_role: str,
    changed_field: str,
) -> None:
    """A count-identical class semantic edit must invalidate researcher approval."""
    project = create_project(client, name="Biological Identity Approval")
    source_class = create_label_class(
        client,
        project["id"],
        class_index=0,
        name="Swiftia Closed",
        display_color="#E76F51",
    )
    target_class = create_label_class(
        client,
        project["id"],
        class_index=1,
        name="Swiftia Open",
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
    endpoint = f"/api/v1/projects/{project['id']}/classes/{source_class['id']}/{operation_type}"
    preview = client.post(f"{endpoint}/preview", json={"target_class_id": target_class["id"]})
    assert preview.status_code == 201, preview.text
    reviewed = preview.json()
    assert reviewed["plan"]["blockers"] == []

    changed_id = source_class["id"] if changed_role == "source" else target_class["id"]
    with Session(cast(FastAPI, client.app).state.engine) as session:
        label_class = session.get(LabelClass, changed_id)
        assert label_class is not None
        setattr(label_class, changed_field, f"revised {changed_field}")
        session.commit()

    execute = client.post(
        endpoint,
        json={"operation_id": reviewed["id"], "preview_checksum": reviewed["preview_checksum"]},
    )
    assert execute.status_code == 409, execute.text
    assert "stale" in execute.json()["detail"].lower()

    with Session(cast(FastAPI, client.app).state.engine) as session:
        annotation = session.get(Annotation, "annotation-active")
        prediction = session.get(PredictionProposal, "proposal-pending")
        qc_issue = session.get(QualityControlIssue, "qc-issue-open")
        review_item = session.get(ReviewQueueItem, "queue-item-pending")
        operation = session.get(ClassOperation, reviewed["id"])
        assert annotation is not None and annotation.label_class_id == source_class["id"]
        assert annotation.revision == 1
        assert prediction is not None and prediction.label_class_id == source_class["id"]
        assert qc_issue is not None and qc_issue.class_ids_json == [source_class["id"]]
        assert review_item is not None and review_item.label_class_ids_json == [source_class["id"]]
        assert operation is not None and operation.status == "failed"
        assert operation.final_state == "preview_stale"
        assert session.get(LabelClass, source_class["id"]) is not None
        assert session.get(LabelClass, target_class["id"]) is not None


@pytest.mark.parametrize("operation_endpoint", ["reassign", "reassign-delete"])
def test_class_operation_execute_requires_previewing_local_researcher(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, operation_endpoint: str
) -> None:
    """A copied preview ID/checksum cannot authorize a different local identity."""
    project = create_project(client, name="Researcher ownership")
    source_class = create_label_class(
        client, project["id"], class_index=0, name="Source", display_color="#E76F51"
    )
    target_class = create_label_class(
        client, project["id"], class_index=1, name="Target", display_color="#2A9D8F"
    )
    seed_reassignment_records(
        client,
        project,
        source_class,
        target_class,
        include_deleted_annotation=False,
        include_historical_prediction=False,
    )
    identity_module = "reefvision.services.class_operations.get_local_user_identity"
    monkeypatch.setattr(identity_module, lambda _settings: "local-user:researcher-a")
    route = f"/api/v1/projects/{project['id']}/classes/{source_class['id']}/{operation_endpoint}"
    preview_response = client.post(f"{route}/preview", json={"target_class_id": target_class["id"]})
    assert preview_response.status_code == 201, preview_response.text
    preview = preview_response.json()
    assert preview["requested_by_identity"] == "local-user:researcher-a"
    assert preview["plan"]["blockers"] == []
    approval = {
        "operation_id": preview["id"],
        "preview_checksum": preview["preview_checksum"],
    }

    monkeypatch.setattr(identity_module, lambda _settings: "local-user:researcher-b")
    refused = client.post(route, json=approval)
    assert refused.status_code == 409, refused.text
    assert "researcher" in refused.json()["detail"].lower()
    with Session(cast(FastAPI, client.app).state.engine) as session:
        operation = session.get(ClassOperation, preview["id"])
        annotation = session.get(Annotation, "annotation-active")
        proposal = session.get(PredictionProposal, "proposal-pending")
        issue = session.get(QualityControlIssue, "qc-issue-open")
        queue_item = session.get(ReviewQueueItem, "queue-item-pending")
        events = list(
            session.scalars(
                select(AnnotationEvent).where(AnnotationEvent.annotation_id == "annotation-active")
            )
        )
        assert operation is not None and operation.status == "previewed"
        assert operation.started_at is None and operation.completed_at is None
        assert annotation is not None and annotation.label_class_id == source_class["id"]
        assert proposal is not None and proposal.label_class_id == source_class["id"]
        assert issue is not None and issue.class_ids_json == [source_class["id"]]
        assert queue_item is not None and queue_item.label_class_ids_json == [source_class["id"]]
        assert session.get(LabelClass, source_class["id"]) is not None
        assert not any(event.event_type.startswith("class_reassigned") for event in events)

    # A rejected foreign identity must not consume the legitimate review approval.
    monkeypatch.setattr(identity_module, lambda _settings: "local-user:researcher-a")
    accepted = client.post(route, json=approval)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "completed"
    with Session(cast(FastAPI, client.app).state.engine) as session:
        annotation = session.get(Annotation, "annotation-active")
        assert annotation is not None and annotation.label_class_id == target_class["id"]
        events = list(
            session.scalars(
                select(AnnotationEvent).where(AnnotationEvent.annotation_id == "annotation-active")
            )
        )
        assert any(
            event.event_type.startswith("class_reassigned")
            and event.actor == "local-user:researcher-a"
            for event in events
        )


@pytest.mark.parametrize("operation_endpoint", ["reassign", "reassign-delete"])
@pytest.mark.parametrize(
    "mutation",
    ["qc_class_membership", "review_class_membership", "qc_state", "review_state"],
)
def test_class_operation_preview_rejects_same_id_review_reference_changes(
    client: TestClient, operation_endpoint: str, mutation: str
) -> None:
    """A reviewed class inventory must not silently accept repurposed QC records."""
    project = create_project(client, name="Reviewed reference membership")
    source_class = create_label_class(
        client, project["id"], class_index=0, name="Source", display_color="#E76F51"
    )
    target_class = create_label_class(
        client, project["id"], class_index=1, name="Target", display_color="#2A9D8F"
    )
    seed_reassignment_records(
        client,
        project,
        source_class,
        target_class,
        include_deleted_annotation=False,
        include_historical_prediction=False,
    )
    route = f"/api/v1/projects/{project['id']}/classes/{source_class['id']}/{operation_endpoint}"
    preview_response = client.post(f"{route}/preview", json={"target_class_id": target_class["id"]})
    assert preview_response.status_code == 201, preview_response.text
    preview = preview_response.json()
    assert preview["plan"]["blockers"] == []
    groups = {group["key"]: group["record_ids"] for group in preview["plan"]["mutable_records"]}
    assert groups["quality_control_issues_open"] == ["qc-issue-open"]
    assert groups["review_queue_items_open"] == ["queue-item-pending"]

    with Session(cast(FastAPI, client.app).state.engine) as session:
        issue = session.get(QualityControlIssue, "qc-issue-open")
        item = session.get(ReviewQueueItem, "queue-item-pending")
        assert issue is not None and item is not None
        if mutation == "qc_class_membership":
            issue.class_ids_json = [source_class["id"], target_class["id"]]
        elif mutation == "review_class_membership":
            item.label_class_ids_json = [source_class["id"], target_class["id"]]
        elif mutation == "qc_state":
            issue.status = "acknowledged"
        else:
            item.review_state = "in_progress"
        session.commit()

    refused = client.post(
        route,
        json={"operation_id": preview["id"], "preview_checksum": preview["preview_checksum"]},
    )
    assert refused.status_code == 409, refused.text
    assert "stale" in refused.json()["detail"].lower()

    with Session(cast(FastAPI, client.app).state.engine) as session:
        operation = session.get(ClassOperation, preview["id"])
        annotation = session.get(Annotation, "annotation-active")
        proposal = session.get(PredictionProposal, "proposal-pending")
        issue = session.get(QualityControlIssue, "qc-issue-open")
        item = session.get(ReviewQueueItem, "queue-item-pending")
        assert operation is not None and operation.final_state == "preview_stale"
        assert operation.status == "failed" and operation.started_at is None
        assert annotation is not None and annotation.label_class_id == source_class["id"]
        assert proposal is not None and proposal.label_class_id == source_class["id"]
        assert issue is not None and source_class["id"] in issue.class_ids_json
        assert item is not None and source_class["id"] in item.label_class_ids_json
        assert session.get(LabelClass, source_class["id"]) is not None


@pytest.mark.parametrize("operation_endpoint", ["reassign", "reassign-delete"])
@pytest.mark.parametrize(
    "mutation",
    [
        "annotation_revision",
        "annotation_geometry",
        "prediction_confidence",
        "prediction_model_checksum",
        "prediction_geometry",
        "prediction_polygon",
        "prediction_label",
    ],
)
def test_class_operation_preview_expires_after_observation_content_change(
    client: TestClient, operation_endpoint: str, mutation: str
) -> None:
    """An observation edit with identical record IDs cannot reuse earlier researcher approval."""
    project = create_project(client, name="Observation content approval")
    source = create_label_class(
        client, project["id"], class_index=0, name="Swiftia Closed", display_color="#E76F51"
    )
    target = create_label_class(
        client, project["id"], class_index=1, name="Swiftia Open", display_color="#2A9D8F"
    )
    seed_reassignment_records(
        client,
        project,
        source,
        target,
        include_deleted_annotation=False,
        include_historical_prediction=False,
    )
    route = f"/api/v1/projects/{project['id']}/classes/{source['id']}/{operation_endpoint}"
    response = client.post(f"{route}/preview", json={"target_class_id": target["id"]})
    assert response.status_code == 201, response.text
    preview = response.json()
    assert preview["plan"]["blockers"] == []

    with Session(cast(FastAPI, client.app).state.engine) as session:
        annotation = session.get(Annotation, "annotation-active")
        proposal = session.get(PredictionProposal, "proposal-pending")
        assert annotation is not None and proposal is not None
        if mutation == "annotation_revision":
            annotation.revision += 1
        elif mutation == "annotation_geometry":
            annotation.x_min += 2
        elif mutation == "prediction_confidence":
            proposal.confidence = 0.45
        elif mutation == "prediction_model_checksum":
            proposal.model_checksum = "9" * 64
        elif mutation == "prediction_geometry":
            proposal.x_max += 3
        elif mutation == "prediction_polygon":
            proposal.polygon_json = [[1.0, 2.0], [5.0, 2.0], [3.0, 6.0]]
        else:
            proposal.predicted_label = "revised prediction label"
        session.commit()

    execute = client.post(
        route,
        json={"operation_id": preview["id"], "preview_checksum": preview["preview_checksum"]},
    )
    assert execute.status_code == 409, execute.text
    assert "stale" in execute.json()["detail"].lower()

    with Session(cast(FastAPI, client.app).state.engine) as session:
        annotation = session.get(Annotation, "annotation-active")
        proposal = session.get(PredictionProposal, "proposal-pending")
        issue = session.get(QualityControlIssue, "qc-issue-open")
        item = session.get(ReviewQueueItem, "queue-item-pending")
        operation = session.get(ClassOperation, preview["id"])
        assert annotation is not None and annotation.label_class_id == source["id"]
        assert proposal is not None and proposal.label_class_id == source["id"]
        assert issue is not None and issue.class_ids_json == [source["id"]]
        assert item is not None and item.label_class_ids_json == [source["id"]]
        assert operation is not None and operation.status == "failed"
        assert operation.final_state == "preview_stale"
        assert operation.started_at is None
        assert session.get(LabelClass, source["id"]) is not None
        assert session.get(LabelClass, target["id"]) is not None


@pytest.mark.parametrize("operation_endpoint", ["reassign", "reassign-delete"])
@pytest.mark.parametrize(
    "mutation",
    [
        "dataset_class_map",
        "dataset_manifest_checksum",
        "model_class_map",
        "model_weights_checksum",
    ],
)
def test_class_operation_preview_expires_after_compatibility_provenance_change(
    client: TestClient, operation_endpoint: str, mutation: str
) -> None:
    """Unchanged protected IDs cannot conceal revised dataset/model provenance."""
    project = create_project(client, name="Compatibility lineage approval")
    source = create_label_class(
        client, project["id"], class_index=0, name="Swiftia Closed", display_color="#E76F51"
    )
    target = create_label_class(
        client, project["id"], class_index=1, name="Swiftia Open", display_color="#2A9D8F"
    )
    seed_reassignment_records(
        client,
        project,
        source,
        target,
        include_deleted_annotation=False,
        include_historical_prediction=False,
    )
    route = f"/api/v1/projects/{project['id']}/classes/{source['id']}/{operation_endpoint}"
    response = client.post(f"{route}/preview", json={"target_class_id": target["id"]})
    assert response.status_code == 201, response.text
    preview = response.json()
    assert preview["plan"]["blockers"] == []

    with Session(cast(FastAPI, client.app).state.engine) as session:
        version = session.get(DatasetVersion, "dataset-version-1")
        model = session.get(ModelRegistration, "model-1")
        assert version is not None and model is not None
        if mutation == "dataset_class_map":
            version.class_map_json = [
                {**entry, "name": "reinterpreted source"} if entry["id"] == source["id"] else entry
                for entry in version.class_map_json
            ]
        elif mutation == "dataset_manifest_checksum":
            version.manifest_sha256 = "0" * 64
        elif mutation == "model_class_map":
            model.class_map_json = {
                **model.class_map_json,
                "labels": ["reinterpreted source", target["name"]],
            }
        else:
            model.sha256 = "1" * 64
        session.commit()

    execute = client.post(
        route,
        json={"operation_id": preview["id"], "preview_checksum": preview["preview_checksum"]},
    )
    assert execute.status_code == 409, execute.text
    assert "stale" in execute.json()["detail"].lower()

    with Session(cast(FastAPI, client.app).state.engine) as session:
        annotation = session.get(Annotation, "annotation-active")
        prediction = session.get(PredictionProposal, "proposal-pending")
        issue = session.get(QualityControlIssue, "qc-issue-open")
        queue_item = session.get(ReviewQueueItem, "queue-item-pending")
        operation = session.get(ClassOperation, preview["id"])
        assert annotation is not None and annotation.label_class_id == source["id"]
        assert prediction is not None and prediction.label_class_id == source["id"]
        assert issue is not None and issue.class_ids_json == [source["id"]]
        assert queue_item is not None and queue_item.label_class_ids_json == [source["id"]]
        assert operation is not None and operation.status == "failed"
        assert operation.final_state == "preview_stale" and operation.started_at is None
        assert session.get(LabelClass, source["id"]) is not None
        assert session.get(LabelClass, target["id"]) is not None

def test_class_execution_never_publishes_partial_running_state(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Other readers see approved preview until the biological mutation commits."""
    project = create_project(client, name="Atomic class change")
    source = create_label_class(
        client, project["id"], class_index=0, name="Swiftia closed", display_color="#E76F51"
    )
    target = create_label_class(
        client, project["id"], class_index=1, name="Swiftia open", display_color="#2A9D8F"
    )
    seed_reassignment_records(
        client,
        project,
        source,
        target,
        include_deleted_annotation=False,
        include_historical_prediction=False,
    )
    preview = client.post(
        f"/api/v1/projects/{project['id']}/classes/{source['id']}/reassign/preview",
        json={"target_class_id": target["id"]},
    )
    assert preview.status_code == 201, preview.text
    approval = preview.json()
    observed: list[tuple[str, str]] = []
    original_snapshot = class_operations_module.annotation_snapshot

    def observe_other_connection(annotation: Annotation) -> dict[str, Any]:
        # Called during the live biological mutation, before its final commit.
        # Read through a second SQLite connection, not the writing session.
        with Session(cast(FastAPI, client.app).state.engine) as other:
            operation = other.get(ClassOperation, approval["id"])
            existing = other.get(Annotation, "annotation-active")
            assert operation is not None
            assert existing is not None
            observed.append((operation.status, existing.label_class_id))
        return original_snapshot(annotation)

    monkeypatch.setattr(class_operations_module, "annotation_snapshot", observe_other_connection)
    response = client.post(
        f"/api/v1/projects/{project['id']}/classes/{source['id']}/reassign",
        json={"operation_id": approval["id"], "preview_checksum": approval["preview_checksum"]},
    )
    assert response.status_code == 200, response.text
    assert len(observed) >= 2
    assert all(state == ("previewed", source["id"]) for state in observed)
    with Session(cast(FastAPI, client.app).state.engine) as session:
        operation = session.get(ClassOperation, approval["id"])
        annotation = session.get(Annotation, "annotation-active")
        assert operation is not None and operation.status == "completed"
        assert annotation is not None and annotation.label_class_id == target["id"]
        assert session.scalar(
            select(AnnotationEvent.id).where(AnnotationEvent.event_type == "class_reassigned")
        )


def test_class_execution_cannot_reuse_preview_claimed_by_other_writer(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A concurrent completion between the initial read and claim cannot rerun science edits."""
    project = create_project(client, name="Competing class execution")
    source = create_label_class(
        client, project["id"], class_index=0, name="Thesea closed", display_color="#E76F51"
    )
    target = create_label_class(
        client, project["id"], class_index=1, name="Thesea open", display_color="#2A9D8F"
    )
    seed_reassignment_records(
        client,
        project,
        source,
        target,
        include_deleted_annotation=False,
        include_historical_prediction=False,
    )
    preview = client.post(
        f"/api/v1/projects/{project['id']}/classes/{source['id']}/reassign/preview",
        json={"target_class_id": target["id"]},
    )
    assert preview.status_code == 201, preview.text
    approval = preview.json()
    original_class = ClassOperationsService._class
    intercepted = False

    def other_writer_wins(
        service: ClassOperationsService, project_id: str, class_id: str
    ) -> LabelClass:
        nonlocal intercepted
        label_class = original_class(service, project_id, class_id)
        if class_id == target["id"] and not intercepted:
            intercepted = True
            with Session(cast(FastAPI, client.app).state.engine) as other:
                claimed = other.get(ClassOperation, approval["id"])
                assert claimed is not None
                claimed.status = "completed"
                claimed.final_state = "reassigned"
                claimed.completed_at = datetime.now(UTC)
                other.commit()
        return label_class

    monkeypatch.setattr(ClassOperationsService, "_class", other_writer_wins)
    response = client.post(
        f"/api/v1/projects/{project['id']}/classes/{source['id']}/reassign",
        json={"operation_id": approval["id"], "preview_checksum": approval["preview_checksum"]},
    )
    assert intercepted is True
    assert response.status_code == 409, response.text
    assert "already claimed" in response.json()["detail"]
    with Session(cast(FastAPI, client.app).state.engine) as session:
        operation = session.get(ClassOperation, approval["id"])
        annotation = session.get(Annotation, "annotation-active")
        assert operation is not None and operation.status == "completed"
        assert annotation is not None and annotation.label_class_id == source["id"]
        assert not list(
            session.scalars(
                select(AnnotationEvent.id).where(
                    AnnotationEvent.event_type == "class_reassigned"
                )
            )
        )
