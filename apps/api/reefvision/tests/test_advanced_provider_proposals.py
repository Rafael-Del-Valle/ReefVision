from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import cast

from fastapi import FastAPI
from PIL import Image

from reefvision.db.models import Job, ModelRegistration, PredictionProposal
from reefvision.ml.optional_transformers_runtime import OPTIONAL_MODEL_SPECS
from reefvision.services.advanced_provider_proposals import (
    persist_grounding_dino_proposals,
    persist_sam2_proposal,
)
from reefvision.tests.test_annotations import create_project, import_one


def _runtime_path(tmp_path: Path, provider_id: str) -> Path:
    path = tmp_path / provider_id
    path.mkdir(parents=True, exist_ok=True)
    (path / OPTIONAL_MODEL_SPECS[provider_id].weight_filename).write_bytes(b"test")
    return path


def _mask_png_base64(width: int, height: int) -> str:
    image = Image.new("L", (width, height), 0)
    for x in range(10, min(width, 30)):
        for y in range(8, min(height, 25)):
            image.putpixel((x, y), 255)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def test_grounding_dino_enters_prediction_review_system(
    client,
    tmp_path: Path,
) -> None:
    project = create_project(client, "Grounding DINO proposals")
    imported = import_one(client, str(project["id"]), size=(100, 80))
    image_id = str(imported["successful"][0]["image_id"])
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        proposal_ids = persist_grounding_dino_proposals(
            session,
            app.state.settings,
            project_id=str(project["id"]),
            image_id=image_id,
            runtime_path=_runtime_path(tmp_path, "grounding_dino"),
            device="cpu",
            task="open_vocabulary_detect",
            detections=[
                {
                    "label": "novel coral feature",
                    "confidence": 0.91,
                    "box": {
                        "x_min": 4,
                        "y_min": 5,
                        "x_max": 40,
                        "y_max": 45,
                    },
                }
            ],
            prompt_labels=["novel coral feature"],
            confidence_threshold=0.35,
            text_threshold=0.25,
        )
        assert len(proposal_ids) == 1
        proposal = session.get(PredictionProposal, proposal_ids[0])
        assert proposal is not None
        assert proposal.geometry_kind == "bounding_box"
        assert proposal.review_status == "pending"
        assert proposal.provenance_json["provider_id"] == "grounding_dino"
        assert proposal.provenance_json["requires_researcher_review"] is True

        model = session.get(ModelRegistration, proposal.model_id)
        assert model is not None
        assert model.metadata_json["managed_catalog_proxy"] is True

        job = session.get(Job, proposal.inference_job_id)
        assert job is not None
        assert job.status == "succeeded"
        assert job.result_json["proposal_ids"] == proposal_ids

    listed = client.get(f"/api/v1/images/{image_id}/prediction-proposals")
    assert listed.status_code == 200, listed.text
    payload = listed.json()
    assert payload["counts"]["pending"] == 1
    assert payload["items"][0]["id"] == proposal_ids[0]


def test_sam2_becomes_raster_mask_proposal_and_accepts(
    client,
    tmp_path: Path,
) -> None:
    project = create_project(client, "SAM 2 proposals")
    imported = import_one(client, str(project["id"]), size=(100, 80))
    image_id = str(imported["successful"][0]["image_id"])
    label_class_id = str(project["label_classes"][0]["id"])
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        proposal_id = persist_sam2_proposal(
            session,
            app.state.settings,
            project_id=str(project["id"]),
            image_id=image_id,
            runtime_path=_runtime_path(tmp_path, "sam2"),
            device="cpu",
            mask_png_base64=_mask_png_base64(100, 80),
            score=0.94,
            box={
                "x_min": 10,
                "y_min": 8,
                "x_max": 30,
                "y_max": 25,
            },
            prompt_fields={
                "box": [10, 8, 30, 25],
                "label_class_id": label_class_id,
            },
        )
        proposal = session.get(PredictionProposal, proposal_id)
        assert proposal is not None
        assert proposal.geometry_kind == "raster_mask"
        assert proposal.mask_path is not None
        assert proposal.mask_content_sha256 is not None
        assert proposal.review_status == "pending"
        assert proposal.label_class_id == label_class_id
        assert proposal.provenance_json["provider_id"] == "sam2"

    mask_response = client.get(f"/api/v1/prediction-proposals/{proposal_id}/mask")
    assert mask_response.status_code == 200, mask_response.text
    assert mask_response.content.startswith(b"\x89PNG\r\n\x1a\n")

    accepted = client.post(
        f"/api/v1/prediction-proposals/{proposal_id}/accept",
        json={"label_class_id": label_class_id},
    )
    assert accepted.status_code == 200, accepted.text
    payload = accepted.json()
    assert payload["proposal"]["review_status"] == "accepted"
    assert payload["mask_annotation"] is not None
    assert payload["mask_annotation"]["geometry_kind"] == "raster_mask"
