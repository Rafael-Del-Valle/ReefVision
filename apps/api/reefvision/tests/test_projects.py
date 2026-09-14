from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.base import Base
from reefvision.db.models import (
    Annotation,
    AnnotationEvent,
    DatasetVersion,
    ImageAsset,
    Job,
    ModelRegistration,
    PredictionProposal,
    QualityControlIssue,
    QualityControlRun,
    ReviewQueue,
    ReviewQueueItem,
)
from reefvision.domain.templates import OCTOCORAL_TEMPLATE
from reefvision.main import create_app
from reefvision.storage.projects import resolve_managed_project_path


def create_project(client: TestClient, **overrides: object) -> dict[str, Any]:
    payload: dict[str, object] = {"name": "CPT Coral Study", "template": "octocoral"}
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


def test_octocoral_project_creation_and_restart_persistence(
    client: TestClient, test_settings: Settings
) -> None:
    project = create_project(client)

    assert project["slug"] == "cpt-coral-study"
    classes = project["label_classes"]
    assert [item["class_index"] for item in classes] == list(range(6))
    assert [item["name"] for item in classes] == [item["name"] for item in OCTOCORAL_TEMPLATE]

    storage_path = test_settings.resolved_data_dir / str(project["storage_root"])
    assert storage_path.is_dir()

    fetched = client.get(f"/api/v1/projects/{project['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["label_classes"] == classes


def test_project_reopens_after_application_restart(tmp_path: Path) -> None:
    settings = Settings(
        env="test",
        data_dir=tmp_path / "persistent-data",
        database_url=f"sqlite:///{(tmp_path / 'persistent.db').as_posix()}",
        web_origin="http://testserver",
    )
    first_app = create_app(settings)
    Base.metadata.create_all(first_app.state.engine)
    with TestClient(first_app) as first_client:
        project = create_project(first_client)

    second_app = create_app(settings)
    with TestClient(second_app) as second_client:
        response = second_client.get(f"/api/v1/projects/{project['id']}")
        assert response.status_code == 200
        assert response.json()["name"] == "CPT Coral Study"
        assert len(response.json()["label_classes"]) == 6
        Base.metadata.drop_all(second_app.state.engine)


def test_generated_slugs_are_deterministically_disambiguated(client: TestClient) -> None:
    first = create_project(client, name="Reef Study", template="blank")
    second = create_project(client, name="Reef Study", template="blank")

    assert first["slug"] == "reef-study"
    assert second["slug"] == "reef-study-2"


def test_explicit_duplicate_slug_is_rejected(client: TestClient) -> None:
    create_project(client, name="One", slug="shared", template="blank")
    response = client.post(
        "/api/v1/projects", json={"name": "Two", "slug": "shared", "template": "blank"}
    )

    assert response.status_code == 409


def test_project_archive_hides_from_default_dashboard(client: TestClient) -> None:
    project = create_project(client, template="blank")

    archived = client.post(f"/api/v1/projects/{project['id']}/archive")
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None
    assert client.get("/api/v1/projects").json() == []
    assert len(client.get("/api/v1/projects?include_archived=true").json()) == 1


def test_project_summaries_include_class_counts(client: TestClient) -> None:
    create_project(client, template="octocoral")

    response = client.get("/api/v1/project-summaries")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["label_class_count"] == 6
    assert payload[0]["active_label_class_count"] == 6


def test_class_uniqueness_is_project_local(client: TestClient) -> None:
    first = create_project(client, name="First", template="blank")
    second = create_project(client, name="Second", template="blank")
    class_payload = {
        "class_index": 0,
        "name": "Polyp",
        "display_color": "#12AB34",
    }

    first_response = client.post(f"/api/v1/projects/{first['id']}/classes", json=class_payload)
    assert first_response.status_code == 201
    second_response = client.post(f"/api/v1/projects/{second['id']}/classes", json=class_payload)
    assert second_response.status_code == 201
    duplicate_name = client.post(
        f"/api/v1/projects/{first['id']}/classes",
        json={"class_index": 1, "name": "Polyp", "display_color": "#FFFFFF"},
    )
    duplicate_index = client.post(
        f"/api/v1/projects/{first['id']}/classes",
        json={"class_index": 0, "name": "Other", "display_color": "#FFFFFF"},
    )

    assert duplicate_name.status_code == 409
    assert duplicate_index.status_code == 409


def test_class_update_reorder_and_deactivate(client: TestClient) -> None:
    project = create_project(client, template="octocoral")
    label_class = project["label_classes"][0]

    updated = client.patch(
        f"/api/v1/classes/{label_class['id']}",
        json={"name": "Muricea Retracted", "display_order": 10, "display_color": "#abcdef"},
    )
    assert updated.status_code == 200
    assert updated.json()["class_index"] == 0
    assert updated.json()["display_color"] == "#ABCDEF"

    deactivated = client.post(f"/api/v1/classes/{label_class['id']}/deactivate")
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False
    assert deactivated.json()["archived_at"] is not None


def test_class_description_archive_restore_usage_and_delete(client: TestClient) -> None:
    project = create_project(client, template="blank")
    label_class = create_label_class(
        client,
        project["id"],
        class_index=0,
        name="Muricea Closed",
        display_color="#E76F51",
    )

    updated = client.patch(
        f"/api/v1/classes/{label_class['id']}",
        json={
            "description": "Primary closed-polyp annotation class",
            "display_order": 4,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "Primary closed-polyp annotation class"

    usage = client.get(f"/api/v1/classes/{label_class['id']}/usage")
    assert usage.status_code == 200
    assert usage.json()["can_delete"] is True
    assert usage.json()["total_references"] == 0

    archived = client.post(f"/api/v1/classes/{label_class['id']}/archive")
    assert archived.status_code == 200
    assert archived.json()["is_active"] is False
    assert archived.json()["archived_at"] is not None

    restored = client.post(f"/api/v1/classes/{label_class['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["is_active"] is True
    assert restored.json()["archived_at"] is None

    deleted = client.delete(f"/api/v1/classes/{label_class['id']}")
    assert deleted.status_code == 204

    fetched = client.get(f"/api/v1/projects/{project['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["label_classes"] == []


def test_used_class_delete_is_blocked_and_usage_is_reported(client: TestClient) -> None:
    project = create_project(client, template="blank")
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
        deleted_annotation = Annotation(
            id="annotation-deleted",
            image_id=image.id,
            label_class_id=source_class["id"],
            x_min=30,
            y_min=40,
            x_max=150,
            y_max=190,
            deleted_at=datetime.now(UTC),
        )
        annotation_event = AnnotationEvent(
            annotation_id=active_annotation.id,
            image_id=image.id,
            event_type="created",
            before_json=None,
            after_json={"label_class_id": source_class["id"]},
            actor="local_user",
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
                "labels": ["Muricea Closed", "Muricea Open"],
                "mapping": {
                    "Muricea Closed": source_class["id"],
                    "Muricea Open": target_class["id"],
                },
            },
            metadata_json={},
        )
        proposal = PredictionProposal(
            id="proposal-1",
            project_id=project["id"],
            image_id=image.id,
            model_id=model.id,
            inference_job_id=inference_job.id,
            model_checksum="c" * 64,
            label_class_id=source_class["id"],
            predicted_label="Muricea Closed",
            predicted_index=0,
            confidence=0.88,
            x_min=20,
            y_min=30,
            x_max=120,
            y_max=150,
        )
        dataset_version = DatasetVersion(
            id="dataset-version-1",
            project_id=project["id"],
            version_number=1,
            name="v1",
            status="complete",
            requested_split_method="random",
            resolved_split_method="random",
            eligible_annotation_statuses_json=["reviewed"],
            requested_ratios_json={"train": 0.7, "validation": 0.2, "test": 0.1},
            achieved_ratios_json={"train": 1, "validation": 0, "test": 0},
            split_seed=7,
            reuse_parent_assignments=False,
            missing_group_key_count=0,
            warnings_json=[],
            class_map_json=[
                {
                    "id": source_class["id"],
                    "class_index": 0,
                    "display_order": 0,
                    "name": "Muricea Closed",
                    "scientific_name": None,
                    "state_name": None,
                    "display_color": "#E76F51",
                    "is_active": True,
                }
            ],
            manifest_json={},
            manifest_sha256="d" * 64,
            image_count=1,
            annotation_count=2,
            created_by="local_user",
            reefvision_version="1.0.1",
            schema_version="0006",
            completed_at=datetime.now(UTC),
        )
        qc_run = QualityControlRun(
            id="qc-run-1",
            project_id=project["id"],
            dataset_version_id=dataset_version.id,
            job_id=qc_job.id,
            scope_type="project",
            status="succeeded",
            rule_categories_json=["annotation_geometry"],
            selected_rule_ids_json=["exact_duplicate_box"],
            thresholds_json={},
            configuration_json={},
            input_checksums_json={},
            summary_json={},
            issue_count=1,
        )
        qc_issue = QualityControlIssue(
            id="qc-issue-1",
            quality_control_run_id=qc_run.id,
            project_id=project["id"],
            dataset_version_id=dataset_version.id,
            image_id=image.id,
            rule_id="exact_duplicate_box",
            rule_version="1.0",
            severity="warning",
            status="open",
            fingerprint="fp-1",
            title="Duplicate annotation",
            explanation="Two boxes are nearly identical.",
            annotation_ids_json=[active_annotation.id],
            prediction_ids_json=[proposal.id],
            class_ids_json=[source_class["id"]],
            measured_values_json={},
            thresholds_json={},
            resolution_metadata_json={},
        )
        review_queue = ReviewQueue(
            id="queue-1",
            project_id=project["id"],
            dataset_version_id=dataset_version.id,
            source_quality_control_run_id=qc_run.id,
            scope_type="project",
            status="complete",
            formula_id="default",
            formula_version="1.0",
            configuration_json={},
            input_checksums_json={},
            summary_json={},
            item_count=1,
        )
        review_queue_item = ReviewQueueItem(
            id="queue-item-1",
            review_queue_id=review_queue.id,
            project_id=project["id"],
            dataset_version_id=dataset_version.id,
            image_id=image.id,
            split="train",
            review_state="pending",
            score=0.8,
            rank_position=1,
            highest_qc_severity="warning",
            label_class_ids_json=[source_class["id"]],
            model_ids_json=[model.id],
            related_issue_ids_json=[qc_issue.id],
            signal_values_json={},
            normalized_signals_json={},
            weights_json={},
            score_breakdown_json=[],
            input_checksum="e" * 64,
        )
        session.add_all(
            [
                image,
                active_annotation,
                deleted_annotation,
                annotation_event,
                inference_job,
                qc_job,
                model,
                proposal,
                dataset_version,
                qc_run,
                qc_issue,
                review_queue,
                review_queue_item,
            ]
        )
        session.commit()

    usage = client.get(f"/api/v1/classes/{source_class['id']}/usage")
    assert usage.status_code == 200
    payload = usage.json()
    counts = {item["key"]: item["count"] for item in payload["counts"]}
    assert counts["annotations_active"] == 1
    assert counts["annotations_deleted"] == 1
    assert counts["annotation_history"] == 1
    assert counts["prediction_proposals"] == 1
    assert counts["quality_control_issues"] == 1
    assert counts["review_queue_items"] == 1
    assert counts["dataset_versions"] == 1
    assert counts["model_registrations"] == 1
    assert payload["can_delete"] is False
    assert payload["immutable_reference_count"] == 4
    assert len(payload["delete_blockers"]) >= 4
    assert len(payload["compatibility_warnings"]) >= 2

    deleted = client.delete(f"/api/v1/classes/{source_class['id']}")
    assert deleted.status_code == 409

    merged = client.post(
        f"/api/v1/classes/{source_class['id']}/merge",
        json={"target_class_id": target_class["id"]},
    )
    assert merged.status_code == 200, merged.text
    merge_payload = merged.json()
    merge_counts = {item["key"]: item["count"] for item in merge_payload["affected_counts"]}
    immutable_counts = {
        item["key"]: item["count"] for item in merge_payload["immutable_reference_counts"]
    }
    assert merge_counts["annotations_active"] == 1
    assert merge_counts["prediction_proposals"] == 1
    assert merge_counts["quality_control_issues"] == 1
    assert merge_counts["review_queue_items"] == 1
    assert immutable_counts["annotations_deleted"] == 1
    assert immutable_counts["annotation_history"] == 1
    assert immutable_counts["dataset_versions"] == 1
    assert immutable_counts["model_registrations"] == 1
    assert merge_payload["source_class"]["is_active"] is False
    assert merge_payload["source_class"]["archived_at"] is not None

    with Session(client.app.state.engine) as session:
        active_annotation = session.get(Annotation, "annotation-active")
        deleted_annotation = session.get(Annotation, "annotation-deleted")
        proposal = session.get(PredictionProposal, "proposal-1")
        qc_issue = session.get(QualityControlIssue, "qc-issue-1")
        queue_item = session.get(ReviewQueueItem, "queue-item-1")
        source_model = session.get(ModelRegistration, "model-1")
        events = list(
            session.scalars(
                select(AnnotationEvent).where(AnnotationEvent.annotation_id == "annotation-active")
            )
        )

        assert active_annotation is not None
        assert deleted_annotation is not None
        assert proposal is not None
        assert qc_issue is not None
        assert queue_item is not None
        assert source_model is not None
        assert active_annotation.label_class_id == target_class["id"]
        assert deleted_annotation.label_class_id == source_class["id"]
        assert proposal.label_class_id == target_class["id"]
        assert qc_issue.class_ids_json == [target_class["id"]]
        assert queue_item.label_class_ids_json == [target_class["id"]]
        assert any(event.event_type == "class_merged" for event in events)
        assert source_model.class_map_json["mapping"]["Muricea Closed"] == source_class["id"]


def test_storage_path_cannot_escape_data_root(test_settings: Settings) -> None:
    try:
        resolve_managed_project_path(test_settings, "../outside")
    except Exception as exc:
        assert "escapes" in str(exc)
    else:
        raise AssertionError("Expected path traversal to be rejected")


def test_project_update_and_not_found(client: TestClient) -> None:
    project = create_project(client, template="blank")
    response = client.patch(
        f"/api/v1/projects/{project['id']}",
        json={"name": "Updated Study", "description": "Research-ready project"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Updated Study"
    assert client.get("/api/v1/projects/missing").status_code == 404
