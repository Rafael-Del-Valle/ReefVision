from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import TrainingRun
from reefvision.ml.providers import DetectionModelMetadata
from reefvision.services.segmentation_models import SegmentationModelService
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project


class FakeSegmentationRegistrationProvider:
    provider_name = "ultralytics"
    provider_version = "8.3.228"

    def inspect_model(self, model_path: Path) -> DetectionModelMetadata:
        assert model_path.is_file()
        return DetectionModelMetadata(
            framework="ultralytics",
            task="segment",
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            class_labels=["soft coral"],
            input_size={"imgsz": 640},
            metadata={
                "trusted_checkpoint": True,
                "proposal_geometry": "polygon_mask",
            },
        )


def test_completed_segmentation_run_registers_as_segmenter(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Segment registration")
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        checkpoint_relative = f"{project['storage_root']}/training/test-segment/weights/best.pt"
        checkpoint = resolve_managed_project_path(
            app.state.settings,
            checkpoint_relative,
        )
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_bytes(b"segmentation-best")
        run = TrainingRun(
            project_id=project["id"],
            dataset_manifest_sha256="a" * 64,
            split_manifest_sha256="b" * 64,
            task="segment",
            catalog_model_id=("ultralytics/yolo11/segment-architecture/n"),
            provider_id="ultralytics",
            architecture="yolo11n-seg.yaml",
            initial_checkpoint_source="scratch",
            resolved_model_asset_id=("builtin_architecture:yolo11n-seg.yaml"),
            parameter_registry_version="8.3.228",
            selected_preset="YOLO11 N Segmentation",
            installation_state="Ready",
            device="cpu",
            precision="fp32",
            run_name="segment-registration",
            tiling_config_json={"mode": "none"},
            training_config_json={"epochs": 1},
            tuning_config_json={"mode": "disabled"},
            evaluation_config_json={},
            resource_limits_json={},
            preflight_report_json={},
            draft_snapshot_json={},
            metrics_json={"metrics/mAP50(M)": 0.7},
            status="completed",
            stage="completed",
            result_checkpoint_path=checkpoint_relative,
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        run_id = run.id

    monkeypatch.setattr(
        SegmentationModelService,
        "_provider_for_registration",
        lambda self, purpose, provider_name: FakeSegmentationRegistrationProvider(),
    )
    response = client.post(
        f"/api/v1/projects/{project['id']}/models/register-from-run",
        json={
            "training_run_id": run_id,
            "display_name": "Segment worker best",
        },
    )
    assert response.status_code == 200, response.text
    model = response.json()
    assert model["purpose"] == "segmenter"
    assert model["task"] == "segment"
    assert model["provider_name"] == "ultralytics"
    assert model["metadata_json"]["registered_from"] == "training_run"
    assert model["metadata_json"]["source_training_run_id"] == run_id
    assert model["metadata_json"]["proposal_geometry"] == "polygon_mask"
    assert model["metadata_json"]["source_metrics"] == {"metrics/mAP50(M)": 0.7}
