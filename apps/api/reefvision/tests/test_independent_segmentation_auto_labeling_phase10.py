from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from reefvision.db.models import PredictionProposal
from reefvision.ml.providers import PixelBox
from reefvision.services.independent_segmentation_auto_labeling import (
    VLMBoxDetection,
    _parse_detections,
    run_independent_segmentation_auto_labeling,
)
from reefvision.services.independent_segmentation_pipeline import (
    run_independent_segmentation_pipeline,
)
from reefvision.services.mask_consensus import IndependentMaskCandidate
from reefvision.storage.masks import resolve_prediction_mask_png
from reefvision.tests.test_segmentation_prediction_review_safety import (
    _seed_review_proposals,
)


@dataclass(frozen=True)
class _FakeDetector:
    branch_id: str
    model_name: str
    x_offset_fraction: float

    def detect(
        self,
        *,
        image_png: bytes,
        width: int,
        height: int,
        concept_prompt: str,
        minimum_confidence: float,
    ) -> list[VLMBoxDetection]:
        assert image_png.startswith(b"\x89PNG")
        assert width > 0 and height > 0
        assert concept_prompt == "soft coral"
        assert minimum_confidence == 0.2
        left = max(0.0, width * (0.10 + self.x_offset_fraction))
        top = height * 0.10
        right = min(float(width), width * (0.65 + self.x_offset_fraction))
        bottom = height * 0.65
        return [
            VLMBoxDetection(
                detection_id=f"{self.branch_id}-0",
                branch_id=self.branch_id,
                model_name=self.model_name,
                confidence=0.9,
                box=PixelBox(x_min=left, y_min=top, x_max=right, y_max=bottom),
            )
        ]


class _FakeRefiner:
    model_id = "fake-sam2"
    model_checksum = "a" * 64

    def refine(
        self,
        *,
        image_id: str,
        image_path,
        class_key: str,
        detections: list[VLMBoxDetection],
    ) -> list[IndependentMaskCandidate]:
        assert image_path.is_file()
        with Image.open(image_path) as source:
            width, height = source.size
        result: list[IndependentMaskCandidate] = []
        for detection in detections:
            mask = np.zeros((height, width), dtype=bool)
            box = detection.box
            mask[
                max(0, int(box.y_min)) : min(height, int(box.y_max)),
                max(0, int(box.x_min)) : min(width, int(box.x_max)),
            ] = True
            result.append(
                IndependentMaskCandidate(
                    candidate_id=detection.detection_id,
                    branch_id=detection.branch_id,
                    image_id=image_id,
                    class_key=class_key,
                    confidence=0.9,
                    mask=mask,
                    provenance={"refined_by": "fake-sam2"},
                )
            )
        return result

    def close(self) -> None:
        raise AssertionError("Injected refiners must not be closed by the service")


def _settings(client: TestClient):
    app = cast(FastAPI, client.app)
    return app, app.state.settings.model_copy(
        update={"allow_remote_vision": True, "safe_mode": False}
    )


def test_independent_pipeline_creates_reviewable_consensus_proposal(
    client: TestClient,
) -> None:
    fixture = _seed_review_proposals(client, geometry_kind="raster_mask")
    app, settings = _settings(client)
    with app.state.session_factory() as session:
        source = session.get(PredictionProposal, fixture.proposal_ids[0])
        assert source is not None
        label_class_id = source.label_class_id
        inference_job_id = source.inference_job_id
    assert label_class_id is not None

    result = run_independent_segmentation_auto_labeling(
        settings,
        app.state.session_factory,
        primary_prediction_ids=[fixture.proposal_ids[0]],
        primary_model_id=fixture.model_id,
        primary_inference_job_id=inference_job_id,
        sam2_model_id=fixture.model_id,
        label_class_id=label_class_id,
        predicted_label="soft coral",
        concept_prompt="soft coral",
        workflow_run_id="workflow-run-exact",
        workflow_node_id="mask-consensus",
        required_votes=2,
        iou_threshold=0.1,
        aggregation="pixel_majority",
        minimum_vlm_confidence=0.2,
        auto_accept=False,
        detectors=[
            _FakeDetector("gemini_sam2", "gemini-test", 0.00),
            _FakeDetector("openai_sam2", "openai-test", 0.03),
        ],
        refiner=_FakeRefiner(),
    )

    assert result.image_count == 1
    assert result.consensus_count >= 1
    assert result.proposal_count >= 1
    assert result.accepted_count == 0
    proposal_id = result.images[0].proposal_ids[0]
    with app.state.session_factory() as session:
        proposal = session.get(PredictionProposal, proposal_id)
        assert proposal is not None
        assert proposal.review_status == "pending"
        assert proposal.geometry_kind == "raster_mask"
        assert proposal.mask_path is not None
        provenance = dict(proposal.provenance_json or {})
        assert provenance["consensus_method"] == "independent_mask_generation"
        assert provenance["aggregation"] == "pixel_majority"
        assert len(provenance["branch_ids"]) >= 2
        project = proposal.project
        path = resolve_prediction_mask_png(
            settings,
            project_storage_root=project.storage_root,
            proposal_id=proposal.id,
            relative_path=proposal.mask_path,
        )
        assert path.is_file()


def test_two_vlm_sam2_branches_can_label_image_when_sam3_misses(
    client: TestClient,
) -> None:
    fixture = _seed_review_proposals(client, geometry_kind="raster_mask")
    app, settings = _settings(client)

    result = run_independent_segmentation_pipeline(
        settings,
        app.state.session_factory,
        image_ids=[fixture.image_id],
        primary_prediction_ids=[],
        primary_model_id=fixture.model_id,
        primary_inference_job_id=fixture.job_id,
        sam2_model_id=fixture.model_id,
        label_class_id=fixture.label_class_id,
        predicted_label="soft coral",
        concept_prompt="soft coral",
        workflow_run_id="workflow-run-no-primary",
        workflow_node_id="independent-mask-consensus",
        required_votes=2,
        iou_threshold=0.1,
        aggregation="pixel_majority",
        minimum_vlm_confidence=0.2,
        auto_accept=False,
        detectors=[
            _FakeDetector("gemini_sam2", "gemini-test", 0.00),
            _FakeDetector("openai_sam2", "openai-test", 0.03),
        ],
        refiner=_FakeRefiner(),
    )

    assert result.failed_image_count == 0
    assert result.consensus_count == 1
    assert result.images[0].primary_candidate_count == 0
    assert result.images[0].refined_mask_count == 2
    assert len(result.images[0].proposal_ids) == 1
    with app.state.session_factory() as session:
        proposal = session.get(PredictionProposal, result.images[0].proposal_ids[0])
        assert proposal is not None
        provenance = dict(proposal.provenance_json or {})
        assert set(provenance["branch_ids"]) == {"gemini_sam2", "openai_sam2"}


def test_vlm_detection_parser_rejects_invalid_and_low_confidence_boxes() -> None:
    parsed = _parse_detections(
        """{
          "detections": [
            {"x_min": 1, "y_min": 2, "x_max": 10, "y_max": 12, "confidence": 0.9},
            {"x_min": -1, "y_min": 2, "x_max": 10, "y_max": 12, "confidence": 0.9},
            {"x_min": 1, "y_min": 2, "x_max": 10, "y_max": 12, "confidence": 0.1}
          ]
        }""",
        branch_id="openai_sam2",
        model_name="gpt-test",
        width=64,
        height=64,
        minimum_confidence=0.25,
    )

    assert len(parsed) == 1
    assert parsed[0].box == PixelBox(x_min=1, y_min=2, x_max=10, y_max=12)
