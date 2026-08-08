from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import numpy
import pytest
from fastapi.testclient import TestClient

from reefvision.jobs import advanced_depth as advanced_depth_job
from reefvision.ml.advanced_provider_contracts import DepthPrediction
from reefvision.ml.model_bundles import inspect_transformers_bundle
from reefvision.services import advanced_providers as advanced_providers_service
from reefvision.tests.test_annotations import create_project, import_one


def _transformers_bundle(model_type: str, architecture: str) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "config.json",
            json.dumps({"model_type": model_type, "architectures": [architecture]}),
        )
        archive.writestr("preprocessor_config.json", json.dumps({"do_resize": True}))
        archive.writestr("model.safetensors", b"synthetic-test-weights")
    return output.getvalue()


def _register_bundle(
    client: TestClient,
    project_id: str,
    *,
    filename: str,
    purpose: str,
    provider_name: str,
    content: bytes,
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/projects/{project_id}/models/register",
        data={
            "purpose": purpose,
            "provider_name": provider_name,
            "display_name": filename.removesuffix(".zip"),
        },
        files={"file": (filename, io.BytesIO(content), "application/zip")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_safe_transformers_bundles_register_for_sam2_and_depth(
    client: TestClient,
) -> None:
    project = create_project(client, "Advanced provider bundles")
    sam2 = _register_bundle(
        client,
        project["id"],
        filename="sam2-local.zip",
        purpose="assist",
        provider_name="sam2",
        content=_transformers_bundle("sam2", "Sam2Model"),
    )
    depth = _register_bundle(
        client,
        project["id"],
        filename="depth-anything-v2-local.zip",
        purpose="depth",
        provider_name="depth_anything_v2",
        content=_transformers_bundle("depth_anything", "DepthAnythingForDepthEstimation"),
    )

    assert sam2["provider_name"] == "sam2"
    assert sam2["purpose"] == "assist"
    assert sam2["task"] == "assist_segmentation"
    assert sam2["metadata_json"]["bundle_format"] == "transformers_zip_v1"
    assert depth["provider_name"] == "depth_anything_v2"
    assert depth["purpose"] == "depth"
    assert depth["task"] == "relative_depth"
    assert depth["metadata_json"]["metric_depth"] is False


def test_transformers_bundle_rejects_path_traversal(tmp_path: Path) -> None:
    bundle = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("config.json", json.dumps({"model_type": "sam2"}))
        archive.writestr("preprocessor_config.json", "{}")
        archive.writestr("model.safetensors", b"weights")
        archive.writestr("../escape.txt", b"nope")

    with pytest.raises(Exception, match="unsafe path"):
        inspect_transformers_bundle(bundle)


class _FakeDepthProvider:
    provider_name = "depth_anything_v2"
    provider_version = "test-provider"

    def load_model(self, model_path: Path, device: str) -> None:
        assert model_path.is_file()
        assert device == "cpu"

    def predict_depth(
        self,
        image_path: Path,
        output_path: Path,
        *,
        device: str,
    ) -> DepthPrediction:
        assert image_path.is_file()
        assert device == "cpu"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        depth_path = output_path.with_suffix(".npy")
        preview_path = output_path.with_suffix(".png")
        numpy.save(depth_path, numpy.array([[1.0, 2.0]], dtype="float32"), allow_pickle=False)
        preview_path.write_bytes(b"png-test")
        return DepthPrediction(
            width=2,
            height=1,
            relative_depth_path=depth_path,
            preview_path=preview_path,
            minimum_value=1.0,
            maximum_value=2.0,
        )

    def unload_model(self) -> None:
        return None


def test_depth_job_writes_provenance_and_managed_outputs(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_project(client, "Depth worker")
    imported = import_one(
        client,
        project["id"],
        filename="depth-source.png",
        relative_path="depth/depth-source.png",
    )
    assert imported["successful"]
    image_id = str(imported["image_id"])
    model = _register_bundle(
        client,
        project["id"],
        filename="depth-anything-v2-worker.zip",
        purpose="depth",
        provider_name="depth_anything_v2",
        content=_transformers_bundle("depth_anything", "DepthAnythingForDepthEstimation"),
    )

    monkeypatch.setattr(
        advanced_providers_service,
        "_managed_runtime_status",
        lambda _provider_id: ("ready", None),
    )
    queued = client.post(
        f"/api/v1/projects/{project['id']}/advanced-providers/depth-anything-v2/jobs",
        json={"model_id": model["id"], "image_ids": [image_id], "device": "cpu"},
    )
    assert queued.status_code == 200, queued.text
    job_id = str(queued.json()["id"])

    monkeypatch.setattr(
        advanced_depth_job,
        "TransformersDepthAnythingV2Provider",
        _FakeDepthProvider,
    )
    processed = advanced_depth_job.process_advanced_depth_job(
        client.app.state.settings,
        client.app.state.session_factory,
        job_id,
    )
    assert processed is True

    job = client.get(f"/api/v1/jobs/{job_id}")
    assert job.status_code == 200, job.text
    payload = job.json()
    assert payload["status"] == "succeeded"
    assert payload["progress_current"] == 1
    assert payload["result_json"]["stage"] == "complete"
    output = payload["result_json"]["outputs"][0]
    assert output["image_id"] == image_id
    assert output["model_id"] == model["id"]
    assert output["model_sha256"] == model["sha256"]
    assert output["provider_id"] == "depth_anything_v2"
    assert output["depth_kind"] == "relative"
    assert output["metric_units"] is None
    assert output["minimum_value"] == 1.0
    assert output["maximum_value"] == 2.0

    depth_path = client.app.state.settings.resolved_data_dir / output["relative_depth_path"]
    preview_path = client.app.state.settings.resolved_data_dir / output["preview_path"]
    assert depth_path.is_file()
    assert preview_path.is_file()
    assert numpy.load(depth_path, allow_pickle=False).tolist() == [[1.0, 2.0]]
