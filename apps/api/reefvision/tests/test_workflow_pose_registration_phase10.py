from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from reefvision.config import Settings
from reefvision.db.models import (
    ModelRegistration,
    PoseModelSchemaBinding,
    PoseTrainingDataset,
    TrainingRun,
    WorkflowArtifact,
)
from reefvision.domain.errors import ValidationError
from reefvision.ml.providers import DetectionModelMetadata
from reefvision.schemas.models import ModelRegistrationResponse
from reefvision.services.semantic_models import SemanticModelService
from reefvision.services.workflow_pose_training import (
    create_pose_workflow_training_result,
)
from reefvision.services.workflow_results_packages import (
    execute_training_results_package_adapter,
)
from reefvision.services.workflow_training import (
    register_workflow_trained_model,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.storage.models import hash_model_file
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_workflow_pose_training_phase10 import (
    _fake_pose_processor,
    _frozen_dataset,
    _seed_model,
)


class _FakeTrainedPoseProvider:
    def inspect_model(
        self,
        model_path: Path,
    ) -> DetectionModelMetadata:
        assert model_path.is_file()

        return DetectionModelMetadata(
            framework="ultralytics",
            task="pose",
            provider_name="ultralytics",
            provider_version="test",
            class_labels=["organism"],
            input_size={
                "imgsz": 640,
            },
            metadata={
                "pose_keypoint_shape": [
                    2,
                    3,
                ],
                "proposal_geometry": ("keypoints+bbox"),
            },
        )


class _FakePoseRegistrationService(SemanticModelService):
    def _provider_for_registration(
        self,
        purpose: str,
        provider_name: str,
    ) -> Any:
        assert purpose == "detector"
        assert provider_name == "ultralytics"

        return _FakeTrainedPoseProvider()

    def _register_model_path(
        self,
        project_id: str,
        *,
        purpose: str,
        provider_name: str | None,
        source_path: Path,
        source_filename: str | None,
        display_name: str | None,
        notes: str | None,
        metadata_overrides: dict[
            str,
            object,
        ]
        | None = None,
    ) -> ModelRegistrationResponse:
        project = self._project(project_id)

        checksum, size = hash_model_file(source_path)

        existing = self.models.find_by_checksum(
            project_id,
            checksum,
        )

        if existing is not None:
            return ModelRegistrationResponse.model_validate(existing)

        model_id = str(uuid4())

        managed_path = f"{project.storage_root}/models/{model_id}.pt"

        destination = resolve_managed_project_path(
            self.settings,
            managed_path,
        )

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        destination.write_bytes(source_path.read_bytes())

        model = ModelRegistration(
            id=model_id,
            project_id=project_id,
            purpose=purpose,
            display_name=(display_name or "Trained pose"),
            source_filename=(source_filename or "trained-pose.pt"),
            managed_path=managed_path,
            sha256=checksum,
            file_size_bytes=size,
            framework="ultralytics",
            task="pose",
            provider_name=(provider_name or "ultralytics"),
            provider_version="test",
            class_map_json={},
            input_size_json={
                "imgsz": 640,
            },
            metadata_json={
                "pose_keypoint_shape": [
                    2,
                    3,
                ],
                **(metadata_overrides or {}),
            },
            notes=notes,
        )

        self.models.add(model)

        self.session.commit()
        self.session.refresh(model)

        return ModelRegistrationResponse.model_validate(model)


def _fake_pose_model_factory(
    session: Session,
    settings: Settings,
) -> SemanticModelService:
    return _FakePoseRegistrationService(
        session,
        settings,
    )


def _training_result(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, Any],
]:
    project, dataset = _frozen_dataset(
        client,
        monkeypatch,
    )

    app = cast(
        FastAPI,
        client.app,
    )

    seed_model_id = _seed_model(
        app,
        project,
        dataset,
    )

    with app.state.session_factory() as session:
        training = create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload={
                "project_id": (project["id"]),
                "dataset_id": (dataset["id"]),
                "manifest_sha256": (dataset["manifest_sha256"]),
            },
            initial_model_payload={
                "model_id": (seed_model_id),
            },
            parameters={
                "run_name": ("phase10b2b-pose"),
                "device": "cpu",
                "precision": "fp32",
                "random_seed": 41,
                "training_config": {
                    "epochs": 1,
                },
            },
            workflow_run_id=("phase10b2b-workflow"),
            workflow_node_run_id=("phase10b2b-train"),
            processor=(_fake_pose_processor),
        )

    return (
        project,
        dataset,
        training,
    )


def test_trained_pose_registration_reuses_exact_frozen_schema_revision(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        project,
        dataset,
        training,
    ) = _training_result(
        client,
        test_settings,
        monkeypatch,
    )

    app = cast(
        FastAPI,
        client.app,
    )

    with app.state.session_factory() as session:
        registered = register_workflow_trained_model(
            session,
            test_settings,
            project_id=str(project["id"]),
            training_payload=training,
            parameters={
                "display_name": ("Phase 10B trained pose"),
            },
            model_service_factory=(_fake_pose_model_factory),
        )

        assert registered["task"] == "pose"

        assert registered["source_pose_training_dataset_id"] == dataset["id"]

        assert registered["pose_schema_id"] == dataset["pose_schema_id"]

        assert registered["pose_schema_revision"] == dataset["pose_schema_revision"]

        assert registered["pose_schema_content_hash"] == dataset["pose_schema_content_hash"]

        binding = session.get(
            PoseModelSchemaBinding,
            str(registered["model_id"]),
        )

        assert binding is not None

        assert binding.schema_id == dataset["pose_schema_id"]

        assert binding.schema_revision == dataset["pose_schema_revision"]

        model = session.get(
            ModelRegistration,
            str(registered["model_id"]),
        )

        assert model is not None

        pose_schema = dict(model.metadata_json["pose_landmark_schema"])

        assert pose_schema["content_hash"] == dataset["pose_schema_content_hash"]

        # Registration must bind the existing immutable schema identity.
        frozen = session.get(
            PoseTrainingDataset,
            str(dataset["id"]),
        )

        assert frozen is not None
        assert binding.schema_id == frozen.pose_schema_id


def test_pose_registration_fails_closed_if_training_schema_provenance_changes(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        project,
        _dataset,
        training,
    ) = _training_result(
        client,
        test_settings,
        monkeypatch,
    )

    app = cast(
        FastAPI,
        client.app,
    )

    with app.state.session_factory() as session:
        run = session.get(
            TrainingRun,
            str(training["training_run_id"]),
        )

        assert run is not None

        manifest = dict(run.artifact_manifest_json or {})

        manifest["pose_schema_content_hash"] = "f" * 64

        run.artifact_manifest_json = manifest

        session.commit()

        with pytest.raises(
            ValidationError,
            match=("landmark-schema provenance"),
        ):
            register_workflow_trained_model(
                session,
                test_settings,
                project_id=str(project["id"]),
                training_payload=training,
                parameters={},
                model_service_factory=(_fake_pose_model_factory),
            )


def test_pose_training_registration_and_results_package_chain(
    client: TestClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        project,
        dataset,
        training,
    ) = _training_result(
        client,
        test_settings,
        monkeypatch,
    )

    app = cast(
        FastAPI,
        client.app,
    )

    with app.state.session_factory() as session:
        registered = register_workflow_trained_model(
            session,
            test_settings,
            project_id=str(project["id"]),
            training_payload=training,
            parameters={},
            model_service_factory=(_fake_pose_model_factory),
        )

        assert registered["task"] == "pose"

        source = cast(
            WorkflowArtifact,
            SimpleNamespace(
                id=("phase10b2b-training-artifact"),
                payload_json=training,
                payload_sha256=(canonical_json_sha256(training)),
            ),
        )

        outputs = execute_training_results_package_adapter(
            session,
            test_settings,
            str(project["id"]),
            {
                "include_excel": False,
                "include_machine_data": True,
                "include_native_artifacts": False,
                "include_logs": False,
                "checkpoint_mode": "none",
            },
            {
                "training": [source],
            },
        )

        assert len(outputs) == 1

        package = outputs[0]["payload"]

        assert package["verification_valid"] is True

        assert package["pose_training_dataset_id"] == dataset["id"]

        assert package["pose_schema_id"] == dataset["pose_schema_id"]

        assert package["pose_schema_content_hash"] == dataset["pose_schema_content_hash"]

        package_root = resolve_managed_project_path(
            test_settings,
            package["package_directory_path"],
        )

        provenance_path = package_root / "data" / "provenance.json"

        assert provenance_path.is_file()

        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))

        snapshot = dict(provenance["draft_snapshot"])

        assert snapshot["pose_training_dataset_id"] == dataset["id"]

        assert snapshot["pose_schema_content_hash"] == dataset["pose_schema_content_hash"]
