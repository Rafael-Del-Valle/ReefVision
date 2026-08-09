from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any, cast

import numpy
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from reefvision.db.models import Job, ModelRegistration
from reefvision.ml.advanced_provider_contracts import DepthPrediction
from reefvision.services.workflow_depth import create_depth_map_artifacts
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project, import_one


def _depth_bundle_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "config.json",
            json.dumps(
                {
                    "model_type": "depth_anything",
                    "architectures": ["DepthAnythingForDepthEstimation"],
                }
            ),
        )
        archive.writestr(
            "preprocessor_config.json",
            json.dumps({"image_processor_type": "DepthAnythingImageProcessor"}),
        )
        archive.writestr("model.safetensors", b"synthetic-depth-weight-placeholder")
    return buffer.getvalue()


def _register_depth_model(client: TestClient, project_id: str) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/projects/{project_id}/models/register",
        data={
            "purpose": "depth",
            "provider_name": "depth_anything_v2",
            "display_name": "Synthetic Depth Anything V2",
        },
        files={
            "file": (
                "depth-anything-v2-synthetic.zip",
                _depth_bundle_bytes(),
                "application/zip",
            )
        },
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


class FakeDepthProvider:
    provider_name = "depth_anything_v2"
    provider_version = "fake-depth-1"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.loaded = False
        self.unloaded = False

    def load_model(self, model_path: Path, device: str) -> None:
        assert model_path.is_file()
        assert device == "cpu"
        self.loaded = True

    def predict_depth(
        self,
        image_path: Path,
        output_path: Path,
        *,
        device: str,
    ) -> DepthPrediction:
        assert self.loaded is True
        assert image_path.is_file()
        assert device == "cpu"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        depth_path = output_path.with_suffix(".npy")
        preview_path = output_path.with_suffix(".png")
        depth = numpy.linspace(0.2, 1.8, num=80 * 100, dtype="float32").reshape(80, 100)
        numpy.save(depth_path, depth, allow_pickle=False)
        if self.fail:
            raise RuntimeError("synthetic depth failure")
        preview = ((depth - depth.min()) / (depth.max() - depth.min()) * 65535).astype(
            "uint16"
        )
        Image.fromarray(preview).save(preview_path, format="PNG")
        return DepthPrediction(
            width=100,
            height=80,
            relative_depth_path=depth_path,
            preview_path=preview_path,
            minimum_value=float(depth.min()),
            maximum_value=float(depth.max()),
        )

    def unload_model(self) -> None:
        self.unloaded = True


def test_depth_bundle_registers_as_non_metric_relative_depth_model(
    client: TestClient,
) -> None:
    project = create_project(client, "Depth registration")
    model = _register_depth_model(client, str(project["id"]))

    assert model["purpose"] == "depth"
    assert model["task"] == "relative_depth"
    assert model["provider_name"] == "depth_anything_v2"
    assert model["framework"] == "transformers"
    assert model["metadata_json"]["depth_kind"] == "relative"
    assert model["metadata_json"]["metric_depth"] is False
    assert model["metadata_json"]["bundle_format"] == "transformers_zip_v1"


def test_relative_depth_workflow_service_persists_checksummed_artifacts(
    client: TestClient,
) -> None:
    project = create_project(client, "Depth workflow")
    imported = import_one(client, str(project["id"]), size=(100, 80))
    image_id = str(imported["successful"][0]["image_id"])
    model = _register_depth_model(client, str(project["id"]))
    app = cast(FastAPI, client.app)
    provider = FakeDepthProvider()

    with app.state.session_factory() as session:
        result = create_depth_map_artifacts(
            session,
            app.state.settings,
            project_id=str(project["id"]),
            image_ids=[image_id],
            model_id=str(model["id"]),
            device="cpu",
            provider_factory=lambda _: provider,
        )

        assert result["schema_version"] == "relative-depth-maps-0001"
        assert result["depth_kind"] == "relative"
        assert result["metric_units"] is None
        assert result["count"] == 1
        output = cast(list[dict[str, Any]], result["outputs"])[0]
        assert output["image_id"] == image_id
        assert output["model_sha256"] == model["sha256"]
        assert output["provider_id"] == "depth_anything_v2"
        assert output["depth_kind"] == "relative"
        assert output["metric_units"] is None
        assert output["width"] == 100
        assert output["height"] == 80
        assert len(str(output["source_image_sha256"])) == 64
        assert len(str(output["relative_depth_sha256"])) == 64
        assert len(str(output["preview_sha256"])) == 64

        depth_path = resolve_managed_project_path(
            app.state.settings,
            str(output["relative_depth_path"]),
        )
        preview_path = resolve_managed_project_path(
            app.state.settings,
            str(output["preview_path"]),
        )
        assert depth_path.is_file()
        assert preview_path.is_file()
        loaded = numpy.load(depth_path, allow_pickle=False)
        assert loaded.shape == (80, 100)
        assert loaded.dtype == numpy.float32

        job = session.get(Job, str(result["depth_job_id"]))
        assert job is not None
        assert job.job_type == "advanced_depth"
        assert job.status == "succeeded"
        assert job.progress_current == 1
        assert job.result_json["stage"] == "complete"

    assert provider.loaded is True
    assert provider.unloaded is True


def test_relative_depth_failure_removes_partial_outputs_and_marks_job_failed(
    client: TestClient,
) -> None:
    project = create_project(client, "Depth failure cleanup")
    imported = import_one(client, str(project["id"]), size=(100, 80))
    image_id = str(imported["successful"][0]["image_id"])
    model = _register_depth_model(client, str(project["id"]))
    app = cast(FastAPI, client.app)
    provider = FakeDepthProvider(fail=True)

    with app.state.session_factory() as session:
        with pytest.raises(RuntimeError, match="synthetic depth failure"):
            create_depth_map_artifacts(
                session,
                app.state.settings,
                project_id=str(project["id"]),
                image_ids=[image_id],
                model_id=str(model["id"]),
                device="cpu",
                provider_factory=lambda _: provider,
            )

        job = session.scalar(
            select(Job)
            .where(
                Job.project_id == str(project["id"]),
                Job.job_type == "advanced_depth",
            )
            .order_by(Job.created_at.desc())
            .limit(1)
        )
        assert job is not None
        assert job.status == "failed"
        assert "synthetic depth failure" in str(job.error_message)
        output_directory = resolve_managed_project_path(
            app.state.settings,
            f"{project['storage_root']}/derived/depth/{job.id}",
        )
        assert not output_directory.exists()

    assert provider.unloaded is True


def _depth_graph(model_id: str) -> dict[str, Any]:
    return {
        "graph_id": "relative-depth-workflow",
        "name": "Relative depth workflow",
        "schema_version": "workflow-graph-0001",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "images", "node_type": "project_images"},
            {
                "node_id": "depth_model",
                "node_type": "registered_model_source",
                "parameters": {"model_id": model_id},
            },
            {
                "node_id": "depth",
                "node_type": "relative_depth_estimation",
                "parameters": {"device": "cpu"},
            },
        ],
        "edges": [
            {
                "edge_id": "project-images",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "images",
                "target_port_id": "project",
            },
            {
                "edge_id": "project-model",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "depth_model",
                "target_port_id": "project",
            },
            {
                "edge_id": "images-depth",
                "source_node_id": "images",
                "source_port_id": "images",
                "target_node_id": "depth",
                "target_port_id": "images",
            },
            {
                "edge_id": "model-depth",
                "source_node_id": "depth_model",
                "source_port_id": "model",
                "target_node_id": "depth",
                "target_port_id": "model",
            },
        ],
    }


def test_relative_depth_node_plans_and_rejects_wrong_model_purpose(
    client: TestClient,
) -> None:
    project = create_project(client, "Depth graph")
    depth_model = _register_depth_model(client, str(project["id"]))

    plan = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs/plan",
        json=_depth_graph(str(depth_model["id"])),
    )
    assert plan.status_code == 200, plan.text
    assert plan.json()["valid"] is True
    assert plan.json()["executable"] is True
    depth_step = next(step for step in plan.json()["steps"] if step["node_id"] == "depth")
    assert depth_step["output_types"] == {"depth_maps": ["relative_depth_maps"]}

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        assist = ModelRegistration(
            project_id=project["id"],
            purpose="assist",
            display_name="Wrong depth model",
            source_filename="sam-v1.pth",
            managed_path=f"projects/{project['id']}/models/wrong-depth.pth",
            sha256="f" * 64,
            file_size_bytes=10,
            framework="segment_anything",
            task="assist_segmentation",
            provider_name="segment_anything",
            provider_version="test",
            class_map_json={},
            input_size_json=None,
            metadata_json={},
        )
        session.add(assist)
        session.commit()
        assist_id = assist.id

    invalid = client.post(
        f"/api/v1/projects/{project['id']}/workflow-graphs/validate",
        json=_depth_graph(assist_id),
    )
    assert invalid.status_code == 200, invalid.text
    assert invalid.json()["valid"] is False
    assert any(
        issue["code"] == "model_purpose_mismatch" for issue in invalid.json()["issues"]
    )
