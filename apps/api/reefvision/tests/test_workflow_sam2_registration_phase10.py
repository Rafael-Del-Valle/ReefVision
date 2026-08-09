from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reefvision.domain.errors import ValidationError
from reefvision.ml.model_bundles import inspect_transformers_bundle
from reefvision.services.workflow_prompt_assist import workflow_assist_provider_for_name
from reefvision.tests.test_annotations import create_project


def _sam2_bundle_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "config.json",
            json.dumps(
                {
                    "model_type": "sam2",
                    "architectures": ["Sam2Model"],
                }
            ),
        )
        archive.writestr("preprocessor_config.json", json.dumps({"image_processor_type": "Sam2ImageProcessor"}))
        archive.writestr("model.safetensors", b"synthetic-test-weight-placeholder")
    return buffer.getvalue()


def test_sam2_zip_registers_without_enabling_unsafe_pickle_models(
    client: TestClient,
) -> None:
    project = create_project(client, "SAM2 workflow registration")
    response = client.post(
        f"/api/v1/projects/{project['id']}/models/register",
        data={
            "purpose": "assist",
            "provider_name": "sam2",
            "display_name": "Synthetic SAM2 bundle",
        },
        files={
            "file": (
                "sam2-synthetic.zip",
                _sam2_bundle_bytes(),
                "application/zip",
            )
        },
    )
    assert response.status_code == 200, response.text
    model = response.json()
    assert model["purpose"] == "assist"
    assert model["task"] == "assist_segmentation"
    assert model["provider_name"] == "sam2"
    assert model["framework"] == "transformers"
    assert model["source_filename"] == "sam2-synthetic.zip"
    assert model["metadata_json"]["bundle_format"] == "transformers_zip_v1"
    assert model["metadata_json"]["image_prompting"] is True
    assert model["metadata_json"]["video_propagation"] is False

    provider = workflow_assist_provider_for_name("sam2")
    assert provider.provider_name == "sam2"


def test_transformers_bundle_rejects_path_traversal(tmp_path: Path) -> None:
    bundle = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("../escape/config.json", "{}")
        archive.writestr("preprocessor_config.json", "{}")
        archive.writestr("model.safetensors", b"x")

    with pytest.raises(ValidationError, match="unsafe path"):
        inspect_transformers_bundle(bundle)


def test_non_sam2_transformers_bundle_is_rejected_by_registration(
    client: TestClient,
) -> None:
    project = create_project(client, "Reject wrong assist bundle")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("config.json", json.dumps({"model_type": "vit"}))
        archive.writestr("preprocessor_config.json", "{}")
        archive.writestr("model.safetensors", b"x")

    response = client.post(
        f"/api/v1/projects/{project['id']}/models/register",
        data={"purpose": "assist", "provider_name": "sam2"},
        files={"file": ("not-sam2.zip", buffer.getvalue(), "application/zip")},
    )
    assert response.status_code == 422, response.text
    assert "does not declare a SAM2 architecture" in response.text
