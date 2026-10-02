from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from reefvision.config import Settings
from reefvision.db.models import Job
from reefvision.jobs.export import process_export_job
from reefvision.jobs.worker import recover_interrupted_jobs
from reefvision.tests.test_annotations import create_project


def image_bytes(color: tuple[int, int, int], size: tuple[int, int] = (80, 60)) -> bytes:
    stream = BytesIO()
    Image.new("RGB", size, color).save(stream, format="PNG")
    return stream.getvalue()


def import_image(
    client: TestClient,
    project_id: str,
    *,
    filename: str,
    relative_path: str,
    color: tuple[int, int, int],
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/projects/{project_id}/imports/images",
        files=[("files", (filename, image_bytes(color), "image/png"))],
        data={"relative_paths": relative_path},
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def update_image(
    client: TestClient,
    image_id: str,
    *,
    group_key: str | None,
    annotation_status: str,
) -> dict[str, Any]:
    response = client.patch(
        f"/api/v1/images/{image_id}",
        json={"group_key": group_key, "annotation_status": annotation_status},
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


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


def create_version(
    client: TestClient,
    project_id: str,
    *,
    name: str,
    parent_version_id: str | None = None,
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/projects/{project_id}/dataset-versions",
        json={
            "name": name,
            "parent_version_id": parent_version_id,
            "eligible_annotation_statuses": ["reviewed"],
            "split_method": "group_random",
            "requested_ratios": {"train": 0.7, "validation": 0.2, "test": 0.1},
            "split_seed": 11,
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def test_dataset_version_preview_is_deterministic_and_group_aware(client: TestClient) -> None:
    project = create_project(client, "Preview study")
    image_ids: list[str] = []
    for index, filename in enumerate(("a.png", "b.png", "c.png", "d.png")):
        report = import_image(
            client,
            project["id"],
            filename=filename,
            relative_path=f"preview/{filename}",
            color=(20 + index, 60, 120),
        )
        image_ids.append(report["successful"][0]["image_id"])

    update_image(client, image_ids[0], group_key="tile-set-1", annotation_status="reviewed")
    update_image(client, image_ids[1], group_key="tile-set-1", annotation_status="reviewed")
    update_image(client, image_ids[2], group_key="tile-set-2", annotation_status="reviewed")
    update_image(client, image_ids[3], group_key=None, annotation_status="reviewed")

    payload = {
        "eligible_annotation_statuses": ["reviewed"],
        "split_method": "random",
        "requested_ratios": {"train": 0.5, "validation": 0.25, "test": 0.25},
        "split_seed": 7,
    }
    preview_one = client.post(
        f"/api/v1/projects/{project['id']}/dataset-version-previews",
        json=payload,
    )
    preview_two = client.post(
        f"/api/v1/projects/{project['id']}/dataset-version-previews",
        json=payload,
    )
    assert preview_one.status_code == 200, preview_one.text
    assert preview_two.status_code == 200, preview_two.text

    first = preview_one.json()
    second = preview_two.json()
    assert first["resolved_split_method"] == "group_random"
    assert first["images"] == second["images"]
    group_one = {
        item["image_id"]: item["proposed_split"]
        for item in first["images"]
        if item["group_key"] == "tile-set-1"
    }
    assert len(set(group_one.values())) == 1
    assert any("Group-aware splitting" in warning for warning in first["warnings"])


def test_dataset_versions_are_immutable_and_comparable(client: TestClient) -> None:
    project = create_project(client, "Immutable study")
    report = import_image(
        client,
        project["id"],
        filename="snapshot.png",
        relative_path="immutable/snapshot.png",
        color=(30, 90, 140),
    )
    image_id = report["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]

    created = save_annotations(
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
    assert created["image"]["annotation_revision"] == 1
    version_one = create_version(client, project["id"], name="Version 1")

    updated = save_annotations(
        client,
        image_id,
        base_revision=1,
        annotation_status="reviewed",
        annotations=[
            {
                "id": "ann-1",
                "label_class_id": class_id,
                "x_min": 12,
                "y_min": 7,
                "x_max": 34,
                "y_max": 27,
            },
            {
                "id": "ann-2",
                "label_class_id": class_id,
                "x_min": 40,
                "y_min": 10,
                "x_max": 55,
                "y_max": 28,
            },
        ],
    )
    assert updated["image"]["annotation_revision"] == 2
    version_two = create_version(
        client,
        project["id"],
        name="Version 2",
        parent_version_id=version_one["id"],
    )

    items_one = client.get(f"/api/v1/dataset-versions/{version_one['id']}/items")
    items_two = client.get(f"/api/v1/dataset-versions/{version_two['id']}/items")
    assert items_one.status_code == 200
    assert items_two.status_code == 200

    item_one = items_one.json()[0]
    item_two = items_two.json()[0]
    assert item_one["annotation_count"] == 1
    assert item_one["annotation_snapshot_json"][0]["x_min"] == 10
    assert item_two["annotation_count"] == 2
    assert item_two["annotation_snapshot_json"][0]["x_min"] == 12

    comparison = client.get(
        f"/api/v1/dataset-versions/{version_one['id']}/compare",
        params={"other_version_id": version_two["id"]},
    )
    assert comparison.status_code == 200, comparison.text
    payload = comparison.json()
    assert payload["added_images"] == []
    assert payload["removed_images"] == []
    assert payload["annotation_delta"] == 1
    assert payload["changed_images"][0]["image_id"] == image_id


def test_dataset_export_uses_frozen_snapshot_after_current_edits(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project = create_project(client, "Export study")
    report = import_image(
        client,
        project["id"],
        filename="export.png",
        relative_path="export/export.png",
        color=(45, 100, 155),
    )
    image_id = report["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]

    save_annotations(
        client,
        image_id,
        base_revision=0,
        annotation_status="reviewed",
        annotations=[
            {
                "id": "export-ann-1",
                "label_class_id": class_id,
                "x_min": 10,
                "y_min": 5,
                "x_max": 30,
                "y_max": 25,
            }
        ],
    )
    version = create_version(client, project["id"], name="Exportable snapshot")

    save_annotations(
        client,
        image_id,
        base_revision=1,
        annotation_status="reviewed",
        annotations=[
            {
                "id": "export-ann-1",
                "label_class_id": class_id,
                "x_min": 12,
                "y_min": 6,
                "x_max": 32,
                "y_max": 26,
            },
            {
                "id": "export-ann-2",
                "label_class_id": class_id,
                "x_min": 40,
                "y_min": 10,
                "x_max": 55,
                "y_max": 30,
            },
        ],
    )

    export_response = client.post(
        f"/api/v1/dataset-versions/{version['id']}/exports",
        json={"format": "yolo_detection"},
    )
    assert export_response.status_code == 200, export_response.text
    export_payload = export_response.json()

    app = cast(FastAPI, client.app)
    processed = process_export_job(
        app.state.settings,
        app.state.session_factory,
        export_payload["job"]["id"],
    )
    if not processed:
        job_payload = client.get(f"/api/v1/jobs/{export_payload['job']['id']}").json()
        export_state = client.get(f"/api/v1/exports/{export_payload['export']['id']}").json()
        raise AssertionError(
            f"Export job failed unexpectedly: job={job_payload} export={export_state}"
        )

    export_record = client.get(f"/api/v1/exports/{export_payload['export']['id']}").json()
    assert export_record["status"] == "succeeded"
    export_root = test_settings.resolved_data_dir / Path(export_record["output_path"])
    manifest_path = test_settings.resolved_data_dir / Path(export_record["manifest_path"])
    label_files = sorted(export_root.glob("labels/*/*.txt"))
    assert len(label_files) == 1
    label_lines = label_files[0].read_text(encoding="utf-8").splitlines()
    assert label_lines == ["0 0.25000000 0.25000000 0.25000000 0.33333333"]
    data_yaml = (export_root / "data.yaml").read_text(encoding="utf-8")
    assert "path:" not in data_yaml
    assert "train: images/train" in data_yaml

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["items"][0]["annotation_count"] == 1
    assert manifest["dataset_version_id"] == version["id"]


def test_interrupted_dataset_export_restarts_from_clean_partial_artifacts(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project = create_project(client, "Restart-safe export")
    report = import_image(
        client,
        project["id"],
        filename="restart-export.png",
        relative_path="export/restart-export.png",
        color=(65, 110, 165),
    )
    image_id = report["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]

    save_annotations(
        client,
        image_id,
        base_revision=0,
        annotation_status="reviewed",
        annotations=[
            {
                "id": "restart-export-ann-1",
                "label_class_id": class_id,
                "x_min": 10,
                "y_min": 5,
                "x_max": 30,
                "y_max": 25,
            }
        ],
    )
    version = create_version(client, project["id"], name="Restart-safe snapshot")
    created = client.post(
        f"/api/v1/dataset-versions/{version['id']}/exports",
        json={"format": "yolo_detection"},
    )
    assert created.status_code == 200, created.text
    payload = created.json()

    output_root = test_settings.resolved_data_dir / Path(payload["export"]["output_path"])
    archive_path = test_settings.resolved_data_dir / Path(payload["export"]["archive_path"])
    output_root.mkdir(parents=True)
    stale_file = output_root / "stale-partial-file.txt"
    stale_file.write_text("interrupted export", encoding="utf-8")
    archive_path.write_bytes(b"partial zip")

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        job = session.get(Job, payload["job"]["id"])
        assert job is not None
        job.status = "running"
        session.commit()

    assert (
        recover_interrupted_jobs(
            app.state.session_factory,
            app.state.settings,
        )
        == 1
    )
    recovered = client.get(f"/api/v1/jobs/{payload['job']['id']}").json()
    assert recovered["status"] == "queued"
    assert recovered["result_json"]["recovery"] == "requeued_on_startup"

    processed = process_export_job(
        app.state.settings,
        app.state.session_factory,
        payload["job"]["id"],
    )
    if not processed:
        job_payload = client.get(f"/api/v1/jobs/{payload['job']['id']}").json()
        export_state = client.get(f"/api/v1/exports/{payload['export']['id']}").json()
        raise AssertionError(
            f"Recovered export job failed unexpectedly: job={job_payload} export={export_state}"
        )

    completed = client.get(f"/api/v1/exports/{payload['export']['id']}").json()
    assert completed["status"] == "succeeded"
    assert not stale_file.exists()
    assert archive_path.read_bytes().startswith(b"PK")
    manifest = json.loads(
        (test_settings.resolved_data_dir / Path(completed["manifest_path"])).read_text(
            encoding="utf-8"
        )
    )
    assert manifest["dataset_version_id"] == version["id"]
    assert manifest["items"][0]["annotation_count"] == 1
