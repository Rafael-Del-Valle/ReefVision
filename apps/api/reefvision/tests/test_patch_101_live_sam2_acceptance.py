"""Online SAM 2.1 Tiny integration acceptance.

This test downloads real upstream model weights only in the explicitly enabled
live acceptance workflow. Ordinary pytest, source CI and offline clean-install
tests never trigger an external model download.
"""

from __future__ import annotations

import base64
import io
import json
import os
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from reefvision.config import Settings
from reefvision.services.sam2_install import (
    model_directory,
    process_sam2_install,
    sam2_status,
    variant_repo,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("REEFVISION_LIVE_SAM2_ACCEPTANCE") != "1",
        reason="Real SAM checkpoint downloads require the dedicated live acceptance job",
    ),
]


def _synthetic_image() -> bytes:
    image = Image.new("RGB", (256, 256), (36, 49, 62))
    draw = ImageDraw.Draw(image)
    draw.ellipse((42, 42, 216, 216), fill=(210, 155, 92))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_real_sam2_tiny_download_inference_and_review_provenance(
    client: TestClient, test_settings: Settings
) -> None:
    project_response = client.post(
        "/api/v1/projects",
        json={"name": "Live SAM 2.1 release acceptance", "template": "blank"},
    )
    assert project_response.status_code == 201, project_response.text
    project_id = project_response.json()["id"]

    image_response = client.post(
        f"/api/v1/projects/{project_id}/imports/images",
        files=[("files", ("live-synthetic.png", _synthetic_image(), "image/png"))],
        data={"relative_paths": "acceptance/live-synthetic.png"},
    )
    assert image_response.status_code == 200, image_response.text
    successful = image_response.json()["successful"]
    assert len(successful) == 1
    image_id = successful[0]["image_id"]

    # Exercise the production install endpoint, queue and real download worker,
    # without substituting a synthetic model or mocking Hugging Face.
    install_response = client.post(f"/api/v1/projects/{project_id}/sam2-models/tiny/install")
    assert install_response.status_code == 200, install_response.text
    job_id = install_response.json()["id"]
    assert process_sam2_install(test_settings, client.app.state.session_factory, job_id)
    job_response = client.get(f"/api/v1/jobs/{job_id}")
    assert job_response.status_code == 200, job_response.text
    job = job_response.json()
    assert job["status"] == "succeeded", job.get("error_message")

    status_response = client.get(f"/api/v1/projects/{project_id}/sam2-models")
    assert status_response.status_code == 200, status_response.text
    status = next(item for item in status_response.json() if item["variant"] == "tiny")
    assert status["ready"] is True, status.get("reason")
    assert status["repo_id"] == variant_repo("tiny")
    assert sam2_status(test_settings, "tiny")["ready"] is True
    assert len(status["revision"]) == 40
    assert len(status["weight_sha256"]) == 64

    weights = model_directory(test_settings, "tiny") / "model.safetensors"
    assert weights.is_file()
    assert sha256(weights.read_bytes()).hexdigest() == status["weight_sha256"]

    # Call the same API endpoint used by editor Shift+1. Inference must create
    # an actual raster-mask proposal, not claim human validation.
    inference_response = client.post(
        f"/api/v1/projects/{project_id}/advanced-providers/sam2/execute",
        json={
            "task": "assist_segmentation",
            "device": "cpu",
            "allow_model_download": False,
            "prompt_fields": {
                "image_id": image_id,
                "sam2_variant": "tiny",
                "box": [35, 35, 225, 225],
            },
        },
    )
    assert inference_response.status_code == 200, inference_response.text
    result = inference_response.json()
    assert result["model_id"] == variant_repo("tiny")
    assert result["model_revision"] == status["revision"]
    assert result["result"]["review_status"] == "pending"
    assert result["result"]["proposal_count"] == 1
    assert result["result"]["area_pixels"] > 0
    mask_bytes = base64.b64decode(result["result"]["mask_png_base64"], validate=True)
    with Image.open(io.BytesIO(mask_bytes)) as source:
        assert source.size == (256, 256)
        assert source.getbbox() is not None

    proposals_response = client.get(f"/api/v1/images/{image_id}/prediction-proposals")
    assert proposals_response.status_code == 200, proposals_response.text
    matching = [
        p for p in proposals_response.json()["items"] if p["id"] == result["result"]["proposal_id"]
    ]
    assert len(matching) == 1
    proposal = matching[0]
    assert proposal["review_status"] == "pending"
    assert proposal["geometry_kind"] == "raster_mask"
    assert proposal["model_checksum"] == status["weight_sha256"]
    assert proposal["provenance_json"]["requires_researcher_review"] is True
    assert proposal["accepted_mask_annotation_id"] is None

    report_dir = os.environ.get("REEFVISION_ACCEPTANCE_REPORT_DIR")
    if report_dir:
        evidence = Path(report_dir)
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / "sam2-live-result.json").write_text(
            json.dumps(
                {
                    "test": "sam2_tiny_real_checkpoint_download_prompt_and_pending_review",
                    "result": "PASS",
                    "repo_id": status["repo_id"],
                    "revision": status["revision"],
                    "weight_sha256": status["weight_sha256"],
                    "image_size": [256, 256],
                    "mask_area_pixels": result["result"]["area_pixels"],
                    "review_status": proposal["review_status"],
                    "model_install_job_status": job["status"],
                    "note": "CPU source-runtime integration; not packaged Windows GUI acceptance",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
