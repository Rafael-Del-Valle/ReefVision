from __future__ import annotations

from hashlib import sha256
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import ModelRegistration, Project
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_classification_phase5 import _seed_classification_project
from reefvision.tests.test_dataset_versions import create_version


def _register_transfer_classifier(
    client: TestClient,
    *,
    project_id: str,
    class_map: dict[str, object],
    payload: bytes = b"phase5-transfer-classifier",
) -> str:
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        project = session.get(Project, project_id)
        assert project is not None
        managed_path = f"{project.storage_root}/models/phase5-transfer.pt"
        checkpoint = resolve_managed_project_path(app.state.settings, managed_path)
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_bytes(payload)
        model = ModelRegistration(
            project_id=project_id,
            purpose="classifier",
            display_name="Phase 5 transfer classifier",
            source_filename="phase5-transfer.pt",
            managed_path=managed_path,
            sha256=sha256(payload).hexdigest(),
            file_size_bytes=len(payload),
            framework="ultralytics",
            task="classify",
            provider_name="ultralytics",
            provider_version="test",
            class_map_json=class_map,
            metadata_json={},
        )
        session.add(model)
        session.commit()
        return model.id


def _queue_transfer_training(
    client: TestClient,
    *,
    project_id: str,
    version_id: str,
    model_id: str,
    mode: str,
):
    return client.post(
        f"/api/v1/projects/{project_id}/classification-training-runs",
        json={
            "dataset_version_id": version_id,
            "mode": mode,
            "minimum_crop_size_px": 10,
            "run_name": "Transfer safety",
            "architecture": "ignored-cls.yaml",
            "initial_checkpoint_model_id": model_id,
            "epochs": 1,
            "batch": 2,
            "imgsz": 64,
            "device": "cpu",
            "precision": "fp32",
        },
    )


def test_transfer_training_accepts_verified_complete_multiclass_mapping(
    client: TestClient,
) -> None:
    project, _image_id, class_ids = _seed_classification_project(client)
    project_id = str(project["id"])
    version = create_version(client, project_id, name="Transfer valid")
    model_id = _register_transfer_classifier(
        client,
        project_id=project_id,
        class_map={
            "classification_mode": "multiclass",
            "labels": ["closed", "open", "small"],
            "mapping": {
                "closed": class_ids["closed"],
                "open": class_ids["open"],
                "small": class_ids["small"],
            },
        },
    )

    response = _queue_transfer_training(
        client,
        project_id=project_id,
        version_id=str(version["id"]),
        model_id=model_id,
        mode="multiclass",
    )

    assert response.status_code == 201, response.text
    assert response.json()["initial_checkpoint_source"] == "registered_model"
    assert response.json()["initial_checkpoint_model_id"] == model_id


def test_transfer_training_rejects_mode_mismatch(client: TestClient) -> None:
    project, _image_id, class_ids = _seed_classification_project(client)
    project_id = str(project["id"])
    version = create_version(client, project_id, name="Transfer mode mismatch")
    model_id = _register_transfer_classifier(
        client,
        project_id=project_id,
        class_map={
            "classification_mode": "multiclass",
            "labels": ["closed", "open", "small"],
            "mapping": {
                "closed": class_ids["closed"],
                "open": class_ids["open"],
                "small": class_ids["small"],
            },
        },
    )

    response = _queue_transfer_training(
        client,
        project_id=project_id,
        version_id=str(version["id"]),
        model_id=model_id,
        mode="binary_state",
    )

    assert response.status_code == 400, response.text
    assert "mode does not match" in response.json()["detail"]


def test_transfer_training_rejects_duplicate_multiclass_targets(
    client: TestClient,
) -> None:
    project, _image_id, class_ids = _seed_classification_project(client)
    project_id = str(project["id"])
    version = create_version(client, project_id, name="Transfer duplicate mapping")
    model_id = _register_transfer_classifier(
        client,
        project_id=project_id,
        class_map={
            "classification_mode": "multiclass",
            "labels": ["closed", "open", "small"],
            "mapping": {
                "closed": class_ids["closed"],
                "open": class_ids["closed"],
                "small": class_ids["small"],
            },
        },
    )

    response = _queue_transfer_training(
        client,
        project_id=project_id,
        version_id=str(version["id"]),
        model_id=model_id,
        mode="multiclass",
    )

    assert response.status_code == 400, response.text
    assert "multiple outputs" in response.json()["detail"]


def test_transfer_training_rejects_modified_checkpoint(client: TestClient) -> None:
    project, _image_id, class_ids = _seed_classification_project(client)
    project_id = str(project["id"])
    version = create_version(client, project_id, name="Transfer checksum mismatch")
    model_id = _register_transfer_classifier(
        client,
        project_id=project_id,
        class_map={
            "classification_mode": "multiclass",
            "labels": ["closed", "open", "small"],
            "mapping": {
                "closed": class_ids["closed"],
                "open": class_ids["open"],
                "small": class_ids["small"],
            },
        },
    )
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        model = session.get(ModelRegistration, model_id)
        assert model is not None
        checkpoint = resolve_managed_project_path(app.state.settings, model.managed_path)
        checkpoint.write_bytes(b"modified-after-registration")

    response = _queue_transfer_training(
        client,
        project_id=project_id,
        version_id=str(version["id"]),
        model_id=model_id,
        mode="multiclass",
    )

    assert response.status_code == 400, response.text
    assert "no longer matches" in response.json()["detail"]


def test_transfer_training_accepts_explicit_binary_state_mapping(
    client: TestClient,
) -> None:
    project, _image_id, _class_ids = _seed_classification_project(client)
    project_id = str(project["id"])
    version = create_version(client, project_id, name="Transfer binary")
    model_id = _register_transfer_classifier(
        client,
        project_id=project_id,
        class_map={
            "classification_mode": "binary_state",
            "labels": ["state_0", "state_1"],
            "state_mapping": {"state_0": "closed", "state_1": "open"},
        },
    )

    response = _queue_transfer_training(
        client,
        project_id=project_id,
        version_id=str(version["id"]),
        model_id=model_id,
        mode="binary_state",
    )

    assert response.status_code == 201, response.text


def test_transfer_training_rejects_ambiguous_binary_mapping(
    client: TestClient,
) -> None:
    project, _image_id, _class_ids = _seed_classification_project(client)
    project_id = str(project["id"])
    version = create_version(client, project_id, name="Transfer ambiguous binary")
    model_id = _register_transfer_classifier(
        client,
        project_id=project_id,
        class_map={
            "classification_mode": "binary_state",
            "labels": ["state_0", "state_1"],
            "state_mapping": {"state_0": "open", "state_1": "open"},
        },
    )

    response = _queue_transfer_training(
        client,
        project_id=project_id,
        version_id=str(version["id"]),
        model_id=model_id,
        mode="binary_state",
    )

    assert response.status_code == 400, response.text
    assert "exactly one output" in response.json()["detail"]
