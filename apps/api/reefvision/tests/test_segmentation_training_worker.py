from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import reefvision.jobs.segmentation_training as worker_module
from reefvision.db.models import Job, TrainingRun
from reefvision.jobs.segmentation_training import process_segmentation_training_job
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_dataset_versions import create_version, import_image
from reefvision.tests.test_mask_dataset_exports import _save_polygon


def _seed_run(client: TestClient) -> str:
    project = create_project(client, "Segmentation worker")
    report = import_image(
        client,
        project["id"],
        filename="segment.png",
        relative_path="training/segment.png",
        color=(35, 95, 145),
    )
    image_id = report["successful"][0]["image_id"]
    _save_polygon(
        client,
        image_id=image_id,
        class_id=project["label_classes"][0]["id"],
        mask_id="c38e70bb-b0f1-442f-8bf6-8953451bddc1",
        points=[(8, 6), (42, 6), (42, 32), (8, 32)],
        base_revision=0,
    )
    version = create_version(client, project["id"], name="Worker polygons")
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        run = TrainingRun(
            project_id=project["id"],
            dataset_version_id=version["id"],
            dataset_manifest_sha256=version["manifest_sha256"],
            split_manifest_sha256="b" * 64,
            task="segment",
            provider_id="ultralytics",
            architecture="yolo11n-seg.yaml",
            initial_checkpoint_source="scratch",
            resolved_model_asset_id="builtin_architecture:yolo11n-seg.yaml",
            device="cpu",
            precision="fp32",
            run_name="segment-worker",
            tiling_config_json={"mode": "none"},
            training_config_json={"epochs": 2, "batch": 1, "imgsz": 64},
            tuning_config_json={"mode": "disabled"},
            evaluation_config_json={"split": "validation"},
            resource_limits_json={},
            preflight_report_json={},
            draft_snapshot_json={},
            progress_total_epochs=2,
        )
        session.add(run)
        session.flush()
        job = Job(
            project_id=project["id"],
            job_type="training",
            status="queued",
            progress_total=2,
            request_json={"training_run_id": run.id},
            result_json={"stage": "queued"},
        )
        session.add(job)
        session.flush()
        run.job_id = job.id
        session.commit()
        return job.id


def test_segment_worker_exports_polygons_and_preserves_mask_metrics(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = _seed_run(client)
    captured: dict[str, Any] = {}
    monkeypatch.setattr(worker_module, "require_provider_ready", lambda *args: None)
    monkeypatch.setattr(worker_module, "configure_provider_runtime", lambda settings: None)
    monkeypatch.setattr(worker_module, "resolve_torch_device", lambda device: "cpu")
    monkeypatch.setattr(
        worker_module,
        "_resolve_model_source",
        lambda settings, session, run: "yolo11n-seg.yaml",
    )

    module = ModuleType("ultralytics")

    class FakeYOLO:
        def __init__(self, model: str) -> None:
            assert model == "yolo11n-seg.yaml"
            self.callbacks: dict[str, list[Any]] = {}
            self.trainer: Any | None = None

        def add_callback(self, event: str, callback: Any) -> None:
            self.callbacks.setdefault(event, []).append(callback)

        def train(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            save_dir = Path(kwargs["project"]) / kwargs["name"]
            weights = save_dir / "weights"
            weights.mkdir(parents=True, exist_ok=True)
            csv_path = save_dir / "results.csv"
            self.trainer = SimpleNamespace(
                save_dir=save_dir,
                csv=csv_path,
                epoch=0,
                epochs=2,
                stop=False,
            )
            for callback in self.callbacks.get("on_train_start", []):
                callback(self.trainer)
            csv_path.write_text(
                "epoch,metrics/mAP50(B),metrics/mAP50(M)\n1,0.5,0.6\n2,0.6,0.7\n",
                encoding="utf-8",
            )
            self.trainer.epoch = 1
            for callback in self.callbacks.get("on_fit_epoch_end", []):
                callback(self.trainer)
            (weights / "best.pt").write_bytes(b"best")
            for callback in self.callbacks.get("on_train_end", []):
                callback(self.trainer)

    module.YOLO = FakeYOLO
    monkeypatch.setitem(sys.modules, "ultralytics", module)
    app = cast(FastAPI, client.app)
    result = process_segmentation_training_job(
        app.state.settings,
        app.state.session_factory,
        job_id,
    )
    with app.state.session_factory() as debug_session:
        debug_job = debug_session.get(Job, job_id)
        assert result, (
            f"Segmentation training worker failed: "
            f"{debug_job.error_message if debug_job else 'job missing'}"
        )
    assert captured["name"] == "segment"
    assert Path(captured["data"]).name == "data.yaml"

    with app.state.session_factory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        run = session.get(TrainingRun, job.request_json["training_run_id"])
        assert run is not None
        assert run.status == "completed"
        assert run.artifact_manifest_json["dataset_format"] == "yolo_segmentation"
        assert run.artifact_manifest_json["dataset_export_result"]["polygon_count"] == 1
        assert run.artifact_manifest_json["mask_metrics"] == {
            "metrics/mAP50(M)": pytest.approx(0.7)
        }
        assert "metrics/mAP50(B)" in run.metrics_json
        assert "metrics/mAP50(M)" in run.metrics_json
