from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as SchemaValidationError

from reefvision.config import Settings
from reefvision.db.models import TrainingRun
from reefvision.domain.errors import ValidationError
from reefvision.jobs.training import _resolve_model_source
from reefvision.ml.ultralytics_registry import validate_ultralytics_training_configuration
from reefvision.schemas.training import TrainingDraftWriteRequest
from reefvision.services.workflow_pose_training import create_pose_workflow_training_result
from reefvision.tests.test_workflow_pose_training_phase10 import (
    _fake_pose_processor,
    _frozen_dataset,
)


@pytest.mark.parametrize("scale", list("nslmx"))
def test_pose_architectures_train_without_seed_and_preserve_initialization(
    client: TestClient, test_settings: Settings, monkeypatch: pytest.MonkeyPatch, scale: str
) -> None:
    project, dataset = _frozen_dataset(client, monkeypatch)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        result = create_pose_workflow_training_result(
            session,
            test_settings,
            project_id=str(project["id"]),
            dataset_payload={"dataset_id": dataset["id"]},
            parameters={
                "initialization_mode": "random",
                "architecture": f"yolo11{scale}-pose.yaml",
                "training_config": {"epochs": 1},
            },
            processor=_fake_pose_processor,
        )
    assert result["initialization_mode"] == "random"
    assert result["architecture"] == f"yolo11{scale}-pose.yaml"
    assert result["initial_checkpoint_model_id"] is None
    assert result["resolved_model_checksum"] is None
    assert result["pose_schema_content_hash"] == dataset["pose_schema_content_hash"]


@pytest.mark.parametrize("value", [True, "yolo11n.pt", "https://example.org/model.pt"])
def test_training_configuration_rejects_provider_pretrained_weights(
    test_settings: Settings, value: object
) -> None:
    with pytest.raises(ValidationError, match="pretrained"):
        validate_ultralytics_training_configuration(
            task="pose",
            mode="train",
            parameters={"pretrained": value},
            search_space=[],
            settings=test_settings,
        )


def test_explicit_registered_initialization_maps_to_legacy_storage() -> None:
    request = TrainingDraftWriteRequest(
        name="Continue local model",
        initialization_mode="registered_model",
        initial_checkpoint_model_id="existing-model",
    )
    assert request.initial_checkpoint_source == "registered_model"


def test_random_initialization_rejects_conflicting_checkpoint() -> None:
    with pytest.raises(SchemaValidationError, match="random"):
        TrainingDraftWriteRequest(
            name="Conflicting initialization",
            initialization_mode="random",
            initial_checkpoint_model_id="existing-model",
        )


def test_pose_workflow_seed_port_is_optional(client: TestClient) -> None:
    response = client.get("/api/v1/workflow-graphs/node-registry")
    assert response.status_code == 200
    node = next(item for item in response.json() if item["node_type"] == "pose_model_training")
    port = next(item for item in node["input_ports"] if item["port_id"] == "initial_model")
    assert port["required"] is False


@pytest.mark.parametrize("architecture", ["yolo11n.pt", "https://example.org/yolo11n.yaml"])
def test_random_training_never_treats_weights_or_urls_as_architectures(
    client: TestClient, test_settings: Settings, architecture: str
) -> None:
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session, pytest.raises(Exception, match="architecture"):
        _resolve_model_source(
            test_settings,
            session,
            TrainingRun(
                architecture=architecture,
                initial_checkpoint_source="scratch",
                resolved_model_asset_id=None,
            ),
        )


def test_training_runtime_blocks_downloads_and_uses_local_fonts(test_settings: Settings) -> None:
    from reefvision.ml.adapters.ultralytics_training import configure_local_training_runtime

    configure_local_training_runtime(test_settings)
    from ultralytics.data import utils as data_utils
    from ultralytics.utils import downloads

    with pytest.raises(ValidationError, match="download"):
        downloads.attempt_download_asset("yolo11n.pt")
    with pytest.raises(ValidationError, match="download"):
        downloads.safe_download("https://example.org/weights.pt")
    assert data_utils.check_font("Arial.Unicode.ttf").is_file()


def test_pose_trainer_does_not_validate_training_frames() -> None:
    from types import SimpleNamespace

    from reefvision.ml.adapters.ultralytics_training import pose_trainer_class

    trainer = object.__new__(pose_trainer_class())
    trainer.args = SimpleNamespace(val=False)
    trainer.best_fitness = None
    import torch

    trainer.loss = torch.tensor(2.0)
    trainer.validator = lambda *args: pytest.fail("Training truth was used as validation")
    assert trainer.validate() == ({}, -2.0)
    trainer.final_eval()


def test_frozen_pose_dataset_source_preserves_manifest(
    client: TestClient, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from reefvision.services.workflow_runtime_adapters import _ADAPTERS

    project, dataset = _frozen_dataset(client, monkeypatch)
    assert "pose_training_dataset" in _ADAPTERS
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        result = _ADAPTERS["pose_training_dataset"](
            session, test_settings, str(project["id"]), {"dataset_id": dataset["id"]}, {}
        )
    assert result[0]["port_id"] == "dataset"
    assert result[0]["payload"]["manifest_sha256"] == dataset["manifest_sha256"]
