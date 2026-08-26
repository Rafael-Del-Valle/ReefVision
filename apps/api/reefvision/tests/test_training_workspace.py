from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from reefvision.jobs.training import _read_results_csv, _read_results_table, process_training_job
from reefvision.ml.dependencies import ProviderPreflightReport
from reefvision.ml.providers import DetectionModelMetadata
from reefvision.schemas.training import TrainingProviderArchitectureResponse
from reefvision.services.model_catalog import (
    ModelCatalogService,
    ResolvedTrainingCatalogSelection,
)
from reefvision.services.models import ModelService
from reefvision.services.training import TrainingService
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_dataset_versions import (
    create_version,
    import_image,
    save_annotations,
    update_image,
)


def test_results_csv_preserves_native_columns_and_orders_epochs(tmp_path: Path) -> None:
    results = tmp_path / "results.csv"
    results.write_text(
        " epoch , metrics/mAP50(B) ,native/status,extra metric\n"
        "2,0.41,complete,\n"
        "1,0.52,warmup,7.5\n",
        encoding="utf-8",
    )

    native = _read_results_table(results)
    assert [row["epoch"] for row in native] == [1.0, 2.0]
    assert native[0]["native/status"] == "warmup"
    assert native[1]["extra metric"] is None
    normalized = _read_results_csv(results)
    assert normalized["metrics/mAP50(B)"] == [0.52, 0.41]
    assert "native/status" not in normalized


class FakeTrainingRegistrationProvider:
    provider_name = "ultralytics"
    provider_version = "8.3.228"

    def inspect_model(self, model_path: Path) -> DetectionModelMetadata:
        assert model_path.exists()
        return DetectionModelMetadata(
            framework="ultralytics",
            task="detect",
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            class_labels=["soft coral"],
            input_size={"imgsz": 64},
            metadata={"trusted_checkpoint": True},
        )


def _patch_training_foundation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ModelCatalogService,
        "resolve_training_selection",
        lambda self, project_id, catalog_id: ResolvedTrainingCatalogSelection(
            catalog_model_id=catalog_id,
            task="detect",
            provider_id="ultralytics",
            architecture="yolo11x.yaml",
            initial_checkpoint_source="managed_catalog",
            initial_checkpoint_model_id=None,
            resolved_model_asset_id=f"catalog_model:{catalog_id}",
            resolved_model_checksum="a" * 64,
            parameter_registry_version="8.3.228",
            installation_state="Ready",
            selected_preset="YOLO11 X",
        ),
    )
    monkeypatch.setattr(
        TrainingService,
        "_ultralytics_detect_architectures",
        lambda self: [
            TrainingProviderArchitectureResponse(
                architecture_id="yolo11.yaml",
                display_name="yolo11",
                task="detect",
                source="11/yolo11.yaml",
            ),
            TrainingProviderArchitectureResponse(
                architecture_id="yolo11x.yaml",
                display_name="yolo11x",
                task="detect",
                source="11/yolo11x.yaml",
            ),
        ],
    )
    monkeypatch.setattr(
        "reefvision.services.training.provider_preflight",
        lambda provider_id, settings=None, check_level="full": ProviderPreflightReport(
            provider_name="ultralytics",
            display_name="Ultralytics detector",
            purpose="detector",
            provider_version="8.3.228",
            tested_python="3.12.x",
            current_python="3.12.7",
            tested_platform="Windows AMD64",
            current_platform="Windows AMD64",
            tested_cuda="12.1",
            current_cuda="12.1",
            automatic_downloads_disabled=True,
            explicit_checkpoint_required=True,
            requirements_file="requirements/providers-windows-cu121-py312.txt",
            package_statuses=(),
            issues=(),
        ),
    )
    monkeypatch.setattr(
        "reefvision.services.training.validate_ultralytics_training_configuration",
        lambda **kwargs: SimpleNamespace(warnings=[]),
    )


def _seed_training_dataset(client: TestClient) -> tuple[dict[str, object], dict[str, object]]:
    project = create_project(client, "Training study")
    report = import_image(
        client,
        project["id"],
        filename="train.png",
        relative_path="training/train.png",
        color=(30, 90, 140),
    )
    image_id = report["successful"][0]["image_id"]
    updated_image = update_image(client, image_id, group_key="reef-1", annotation_status="reviewed")
    save_annotations(
        client,
        image_id,
        base_revision=int(updated_image["annotation_revision"]),
        annotation_status="reviewed",
        annotations=[
            {
                "id": "train-ann-1",
                "label_class_id": project["label_classes"][0]["id"],
                "x_min": 10,
                "y_min": 8,
                "x_max": 38,
                "y_max": 32,
            }
        ],
    )
    version = create_version(client, project["id"], name="Training version")
    return project, version


def test_training_drafts_runs_and_cancellation_foundation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_training_foundation(monkeypatch)
    project, version = _seed_training_dataset(client)

    draft_response = client.post(
        f"/api/v1/projects/{project['id']}/training-drafts",
        json={
            "name": "Detect baseline",
            "run_name": "detect-baseline",
            "dataset_version_id": version["id"],
            "task": "detect",
            "provider_id": "ultralytics",
            "architecture": "yolo11.yaml",
            "initial_checkpoint_source": "scratch",
            "device": "auto",
            "precision": "fp32",
            "random_seed": 11,
            "tiling_config": {"mode": "none"},
            "training_config": {"epochs": 2, "batch": 2, "imgsz": 64},
            "tuning_config": {"mode": "disabled"},
            "evaluation_config": {"split": "validation"},
            "resource_limits": {"max_disk_usage_gb": 5},
        },
    )
    assert draft_response.status_code == 200, draft_response.text
    draft = draft_response.json()
    assert draft["dataset_manifest_sha256"] == version["manifest_sha256"]
    assert draft["validation_state"]["status"] == "ready_with_warnings"
    assert draft["validation_state"]["warnings"] == [
        "Detailed dataset split validation will refresh before launch."
    ]

    list_response = client.get(f"/api/v1/projects/{project['id']}/training-drafts")
    assert list_response.status_code == 200, list_response.text
    assert len(list_response.json()) == 1

    summary_response = client.get(f"/api/v1/projects/{project['id']}/training-draft-summaries")
    assert summary_response.status_code == 200, summary_response.text
    summaries = summary_response.json()
    assert len(summaries) == 1
    assert summaries[0]["id"] == draft["id"]
    assert summaries[0]["validation_status"] == "ready_with_warnings"
    assert summaries[0]["warning_count"] == 1
    assert summaries[0]["blocker_count"] == 0

    run_response = client.post(
        f"/api/v1/projects/{project['id']}/training-runs",
        json={"draft_id": draft["id"]},
    )
    assert run_response.status_code == 200, run_response.text
    run = run_response.json()
    assert run["status"] == "queued"
    assert run["stage"] == "queued"

    cancel_response = client.post(f"/api/v1/training-runs/{run['id']}/cancel")
    assert cancel_response.status_code == 200, cancel_response.text
    cancelled = cancel_response.json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["stage"] == "cancelled"


def test_training_draft_can_resolve_catalog_model_selection(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_training_foundation(monkeypatch)
    project, version = _seed_training_dataset(client)

    draft_response = client.post(
        f"/api/v1/projects/{project['id']}/training-drafts",
        json={
            "name": "Catalog baseline",
            "run_name": "catalog-baseline",
            "dataset_version_id": version["id"],
            "catalog_model_id": "ultralytics/yolo11/detect/x",
            "device": "auto",
            "precision": "fp32",
            "random_seed": 11,
            "tiling_config": {"mode": "none"},
            "training_config": {"epochs": 2, "batch": 2, "imgsz": 64},
            "tuning_config": {"mode": "disabled"},
            "evaluation_config": {"split": "validation"},
            "resource_limits": {"max_disk_usage_gb": 5},
        },
    )

    assert draft_response.status_code == 200, draft_response.text
    draft = draft_response.json()
    assert draft["catalog_model_id"] == "ultralytics/yolo11/detect/x"
    assert draft["task"] == "detect"
    assert draft["provider_id"] == "ultralytics"
    assert draft["architecture"] == "yolo11x.yaml"
    assert draft["initial_checkpoint_source"] == "managed_catalog"
    assert draft["resolved_model_asset_id"] == "catalog_model:ultralytics/yolo11/detect/x"
    assert draft["resolved_model_checksum"] == "a" * 64
    assert draft["selected_preset"] == "YOLO11 X"
    assert draft["installation_state"] == "Ready"
    assert draft["validation_state"]["status"] == "ready_with_warnings"
    assert draft["validation_state"]["warnings"] == [
        "Detailed dataset split validation will refresh before launch."
    ]


def test_training_workspace_bootstrap_returns_seed_data(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_training_foundation(monkeypatch)
    project, version = _seed_training_dataset(client)

    draft_response = client.post(
        f"/api/v1/projects/{project['id']}/training-drafts",
        json={
            "name": "Bootstrap baseline",
            "run_name": "bootstrap-baseline",
            "dataset_version_id": version["id"],
            "catalog_model_id": "ultralytics/yolo11/detect/x",
            "device": "auto",
            "precision": "fp32",
            "random_seed": 11,
            "tiling_config": {"mode": "none"},
            "training_config": {"epochs": 2, "batch": 2, "imgsz": 64},
            "tuning_config": {"mode": "disabled"},
            "evaluation_config": {"split": "validation"},
            "resource_limits": {"max_disk_usage_gb": 5},
        },
    )
    assert draft_response.status_code == 200, draft_response.text
    draft = draft_response.json()

    response = client.get(f"/api/v1/projects/{project['id']}/training/bootstrap")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["draft_summaries"][0]["id"] == draft["id"]
    assert payload["draft_summaries"][0]["validation_status"] == "ready_with_warnings"
    assert payload["selected_draft"]["id"] == draft["id"]
    assert payload["selected_draft"]["validation_state"]["status"] == "ready_with_warnings"
    assert payload["providers"][0]["provider_id"] == "ultralytics"
    assert any(
        item["catalog_id"] == "ultralytics/yolo11/detect/x" for item in payload["catalog"]["models"]
    )


def test_training_job_processing_creates_completed_run_and_experiment(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_training_foundation(monkeypatch)
    monkeypatch.setattr(
        "reefvision.jobs.training.require_provider_ready", lambda *args, **kwargs: None
    )
    monkeypatch.setattr("reefvision.jobs.training.resolve_torch_device", lambda requested: "cpu")
    monkeypatch.setattr(
        "reefvision.jobs.training.configure_provider_runtime", lambda settings: None
    )
    monkeypatch.setattr(
        "reefvision.jobs.training._resolve_model_source",
        lambda settings, session, run: "yolo11x.pt",
    )

    fake_ultralytics = ModuleType("ultralytics")

    class FakeYOLO:
        def __init__(self, model: str) -> None:
            self.model = model
            self.callbacks: dict[str, list] = {}
            self.trainer = None

        def add_callback(self, event: str, callback) -> None:
            self.callbacks.setdefault(event, []).append(callback)

        def train(self, **kwargs) -> None:
            save_dir = Path(kwargs["project"]) / kwargs["name"]
            save_dir.mkdir(parents=True, exist_ok=True)
            results_csv = save_dir / "results.csv"
            weights_dir = save_dir / "weights"
            weights_dir.mkdir(parents=True, exist_ok=True)
            self.trainer = SimpleNamespace(
                save_dir=save_dir,
                csv=results_csv,
                epoch=0,
                epochs=int(kwargs["epochs"]),
                stop=False,
            )
            for callback in self.callbacks.get("on_train_start", []):
                callback(self.trainer)
            results_csv.write_text(
                "epoch,metrics/mAP50(B),metrics/precision(B)\n",
                encoding="utf-8",
            )
            for epoch in range(int(kwargs["epochs"])):
                self.trainer.epoch = epoch
                with results_csv.open("a", encoding="utf-8") as handle:
                    handle.write(f"{epoch + 1},0.{epoch + 6},0.{epoch + 7}\n")
                for callback in self.callbacks.get("on_fit_epoch_end", []):
                    callback(self.trainer)
                if self.trainer.stop:
                    break
            (weights_dir / "best.pt").write_bytes(b"best")
            (weights_dir / "last.pt").write_bytes(b"last")
            for callback in self.callbacks.get("on_train_end", []):
                callback(self.trainer)

    fake_ultralytics.YOLO = FakeYOLO
    monkeypatch.setitem(sys.modules, "ultralytics", fake_ultralytics)

    project, version = _seed_training_dataset(client)
    draft_response = client.post(
        f"/api/v1/projects/{project['id']}/training-drafts",
        json={
            "name": "Worker baseline",
            "run_name": "worker-baseline",
            "dataset_version_id": version["id"],
            "catalog_model_id": "ultralytics/yolo11/detect/x",
            "device": "auto",
            "precision": "fp32",
            "random_seed": 11,
            "tiling_config": {"mode": "none"},
            "training_config": {"epochs": 2, "batch": 2, "imgsz": 64},
            "tuning_config": {"mode": "disabled"},
            "evaluation_config": {"split": "validation"},
            "resource_limits": {"max_disk_usage_gb": 5},
        },
    )
    assert draft_response.status_code == 200, draft_response.text
    draft = draft_response.json()

    run_response = client.post(
        f"/api/v1/projects/{project['id']}/training-runs",
        json={"draft_id": draft["id"]},
    )
    assert run_response.status_code == 200, run_response.text
    run = run_response.json()

    processed = process_training_job(
        client.app.state.settings,
        client.app.state.session_factory,
        run["job_id"],
    )
    if not processed:
        failed_job = client.get(f"/api/v1/jobs/{run['job_id']}").json()
        pytest.fail(f"Training worker failed: {failed_job.get('error_message')}")

    completed_response = client.get(f"/api/v1/training-runs/{run['id']}")
    assert completed_response.status_code == 200, completed_response.text
    completed = completed_response.json()
    assert completed["status"] == "completed"
    assert completed["stage"] == "completed"
    assert completed["result_checkpoint_path"] is not None
    assert "metrics/mAP50(B)" in completed["metrics"]
    assert completed["artifact_manifest"]["native_results_rows"] == [
        {
            "epoch": 1.0,
            "metrics/mAP50(B)": 0.6,
            "metrics/precision(B)": 0.7,
        },
        {
            "epoch": 2.0,
            "metrics/mAP50(B)": 0.7,
            "metrics/precision(B)": 0.8,
        },
    ]
    artifact_names = {item["name"] for item in completed["artifact_manifest"]["artifacts"]}
    assert {"results.csv", "best.pt", "last.pt"} <= artifact_names
    artifact_response = client.get(f"/api/v1/training-runs/{run['id']}/artifacts/0")
    assert artifact_response.status_code == 200

    experiments_response = client.get(f"/api/v1/projects/{project['id']}/experiments")
    assert experiments_response.status_code == 200, experiments_response.text
    experiments = experiments_response.json()
    assert len(experiments) == 1
    assert experiments[0]["training_run_id"] == run["id"]

    monkeypatch.setattr(
        ModelService,
        "_provider_for_registration",
        lambda self, purpose, provider_name: FakeTrainingRegistrationProvider(),
    )
    model_response = client.post(
        f"/api/v1/projects/{project['id']}/models/register-from-run",
        json={"training_run_id": run["id"], "display_name": "Worker baseline best"},
    )
    assert model_response.status_code == 200, model_response.text
    model = model_response.json()
    assert model["purpose"] == "detector"
    assert model["provider_name"] == "ultralytics"
    assert model["metadata_json"]["registered_from"] == "training_run"
    assert model["metadata_json"]["source_training_run_id"] == run["id"]
    assert model["metadata_json"]["source_experiment_id"] == experiments[0]["id"]
    assert model["metadata_json"]["source_catalog_model_id"] == "ultralytics/yolo11/detect/x"
    assert (
        model["metadata_json"]["source_resolved_model_asset_id"]
        == "catalog_model:ultralytics/yolo11/detect/x"
    )
    assert model["metadata_json"]["source_architecture"] == "yolo11x.yaml"
    assert model["metadata_json"]["source_architecture_family"] == "YOLO11"
