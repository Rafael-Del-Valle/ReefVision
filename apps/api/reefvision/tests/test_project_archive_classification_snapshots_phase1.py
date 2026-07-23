from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from reefvision.db.models import (
    ClassificationAssignment,
    ClassificationDatasetSample,
    ClassificationDatasetSnapshot,
    ClassificationLabelSet,
)
from reefvision.jobs.project_archives import (
    process_project_archive_export_job,
    process_project_archive_import_job,
)
from reefvision.tests.test_annotations import create_project, import_one


def test_project_archive_preserves_classification_dataset_snapshots(
    client: TestClient,
) -> None:
    source = create_project(client, "Portable classification snapshot")
    source_id = str(source["id"])
    imported_image = import_one(client, source_id)
    image_id = str(imported_image["successful"][0]["image_id"])
    source_detail = client.get(f"/api/v1/projects/{source_id}")
    assert source_detail.status_code == 200, source_detail.text
    class_id = str(source_detail.json()["label_classes"][0]["id"])

    with client.app.state.session_factory() as session:
        label_set = ClassificationLabelSet(
            project_id=source_id,
            key="portable-image-state",
            name="Portable image state",
            target_kind="image",
            cardinality="single",
            allowed_class_ids_json=[class_id],
        )
        session.add(label_set)
        session.flush()
        session.add(
            ClassificationAssignment(
                project_id=source_id,
                label_set_id=label_set.id,
                target_kind="image",
                target_key=f"image:{image_id}",
                image_id=image_id,
                label_class_id=class_id,
                source_type="manual",
                status="accepted",
            )
        )
        session.commit()
        label_set_id = label_set.id

    snapshot_response = client.post(
        f"/api/v1/projects/{source_id}/classification-dataset-snapshots",
        json={
            "name": "Portable image dataset v1",
            "label_set_id": label_set_id,
            "split_seed": 99,
        },
    )
    assert snapshot_response.status_code == 201, snapshot_response.text
    source_snapshot = snapshot_response.json()["snapshot"]
    source_sample = snapshot_response.json()["samples"][0]

    queued = client.post(
        f"/api/v1/projects/{source_id}/archive-export",
        json={"include_archived_records": True, "notes": "classification snapshot"},
    )
    assert queued.status_code == 202, queued.text
    export_job_id = str(queued.json()["job"]["id"])
    assert process_project_archive_export_job(
        client.app.state.settings,
        client.app.state.session_factory,
        export_job_id,
    )
    exported_job = client.get(f"/api/v1/jobs/{export_job_id}")
    assert exported_job.status_code == 200, exported_job.text
    archive_path = exported_job.json()["result_json"]["archive_path"]

    verification = client.get(
        "/api/v1/project-archives/verify",
        params={"archive_path": archive_path},
    )
    assert verification.status_code == 200, verification.text
    assert verification.json()["valid"] is True

    import_queued = client.post(
        "/api/v1/project-archives/import",
        json={
            "archive_path": archive_path,
            "name": "Imported classification snapshot",
            "slug": "imported-classification-snapshot",
            "restore_as_active": True,
        },
    )
    assert import_queued.status_code == 202, import_queued.text
    import_job_id = str(import_queued.json()["job"]["id"])
    assert process_project_archive_import_job(
        client.app.state.settings,
        client.app.state.session_factory,
        import_job_id,
    )
    imported_job = client.get(f"/api/v1/jobs/{import_job_id}")
    assert imported_job.status_code == 200, imported_job.text
    imported_project_id = str(imported_job.json()["result_json"]["project_id"])
    assert imported_project_id != source_id

    with client.app.state.session_factory() as session:
        imported_label_set = session.scalar(
            select(ClassificationLabelSet).where(
                ClassificationLabelSet.project_id == imported_project_id,
                ClassificationLabelSet.key == "portable-image-state",
            )
        )
        assert imported_label_set is not None
        imported_snapshot = session.scalar(
            select(ClassificationDatasetSnapshot).where(
                ClassificationDatasetSnapshot.project_id == imported_project_id,
                ClassificationDatasetSnapshot.name == "Portable image dataset v1",
            )
        )
        assert imported_snapshot is not None
        imported_sample = session.scalar(
            select(ClassificationDatasetSample).where(
                ClassificationDatasetSample.snapshot_id == imported_snapshot.id
            )
        )
        assert imported_sample is not None
        assert imported_snapshot.label_set_id == imported_label_set.id
        assert imported_snapshot.manifest_sha256 == source_snapshot["manifest_sha256"]
        assert imported_snapshot.sample_count == 1
        assert imported_sample.sample_sha256 == source_sample["sample_sha256"]
        assert imported_sample.source_image_sha256 == source_sample["source_image_sha256"]
        assert imported_sample.label_class_ids_json
        assert imported_sample.assignment_ids_json
