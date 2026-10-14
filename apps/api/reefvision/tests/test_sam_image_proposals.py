from __future__ import annotations

from typing import Any, cast

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select

from reefvision.db.models import Job, MaskAnnotation, PredictionProposal
from reefvision.jobs.sam_image_proposals import process_sam_image_proposals_job
from reefvision.ml.sam_image_proposals import MaskCandidate, candidate_iou, mask_iou, tile_boxes
from reefvision.repositories.jobs import JobRepository
from reefvision.schemas.sam_image_proposals import SamImageProposalsRequest
from reefvision.services.jobs import JobService
from reefvision.services.sam_image_proposals import SamImageProposalsService
from reefvision.tests.test_annotations import create_project, import_one


def test_generation_bounds() -> None:
    with pytest.raises(ValidationError):
        SamImageProposalsRequest(image_id="invalid", points_per_side=99)


def test_mask_iou_preserves_touching_instances() -> None:
    first = np.zeros((20, 30), dtype=bool)
    second = first.copy()
    first[2:10, 3:12] = True
    second[2:10, 12:20] = True
    assert mask_iou(first, second) == 0
    assert mask_iou(first, first) == 1


def test_tiles_cover_non_square_image_with_overlap() -> None:
    boxes = tile_boxes(2600, 1600, 1024)
    covered = np.zeros((1600, 2600), dtype=bool)
    for x1, y1, x2, y2 in boxes:
        covered[y1:y2, x1:x2] = True
        assert x2 - x1 <= 1024 and y2 - y1 <= 1024
    assert covered.all()
    assert len(boxes) <= 16


def test_offset_mask_iou_uses_pixels_not_overlapping_boxes() -> None:
    a = np.zeros((20, 30), dtype=bool)
    a[2:10, 3:12] = True
    b = a.copy()
    assert candidate_iou(MaskCandidate(a, 0, 0, 1, 1), MaskCandidate(b, 1, 0, 1, 1)) == 0.8


@pytest.fixture
def generation_context(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    project = create_project(client, "Automatic SAM")
    image_id = import_one(client, str(project["id"]), size=(100, 80))["successful"][0]["image_id"]
    app = cast(FastAPI, client.app)
    status = {
        "ready": True,
        "path": str(tmp_path),
        "revision": "test-revision",
        "weight_sha256": "a" * 64,
        "reason": None,
    }
    for module in ("services", "jobs"):
        monkeypatch.setattr(
            f"reefvision.{module}.sam_image_proposals.sam2_status", lambda *_: status
        )
    return app, project, image_id


def _job(context: Any) -> str:
    app, project, image_id = context
    with app.state.session_factory() as session:
        job = SamImageProposalsService(session, app.state.settings).create(
            str(project["id"]), SamImageProposalsRequest(image_id=image_id)
        )
        return str(job.id)


def _candidate(left: int, score: float = 0.9) -> MaskCandidate:
    mask = np.zeros((80, 100), dtype=bool)
    mask[8:25, left : left + 15] = True
    return MaskCandidate(mask, 0, 0, score, 0.99)


def test_multiple_class_agnostic_proposals_atomic_review_and_duplicate_suppression(
    client: TestClient,
    generation_context: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, project, image_id = generation_context
    factory, settings = app.state.session_factory, app.state.settings
    candidates = [_candidate(5), _candidate(5, 0.85), _candidate(20), _candidate(50)]
    monkeypatch.setattr(
        "reefvision.jobs.sam_image_proposals.generate_candidates", lambda *_: iter(candidates)
    )
    with factory() as session:
        session.add(
            MaskAnnotation(
                image_id=image_id,
                label_class_id=project["label_classes"][0]["id"],
                polygon_json=[[50, 8], [64, 8], [64, 24], [50, 24]],
                geometry_kind="polygon",
                status="verified",
            )
        )
        session.commit()
    job_id = _job(generation_context)
    assert process_sam_image_proposals_job(settings, factory, job_id)
    with factory() as session:
        job = session.get(Job, job_id)
        assert job.status == "succeeded"
        ids = job.result_json["proposal_ids"]
        assert len(ids) == 2
        proposals = list(session.scalars(select(PredictionProposal)))
        assert all(
            item.label_class_id is None and item.review_status == "pending" for item in proposals
        )
        assert all(item.inference_job_id == job_id for item in proposals)
        assert session.scalar(select(func.count()).select_from(MaskAnnotation)) == 1
    accepted = client.post(
        f"/api/v1/prediction-proposals/{ids[0]}/accept",
        json={"label_class_id": project["label_classes"][0]["id"]},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["mask_annotation"]["geometry_kind"] == "raster_mask"
    second = _job(generation_context)
    assert process_sam_image_proposals_job(settings, factory, second)
    with factory() as session:
        assert session.get(Job, second).result_json["proposal_count"] == 0
        assert session.scalar(select(func.count()).select_from(MaskAnnotation)) == 2


@pytest.mark.parametrize("outcome", ["cancel", "failure", "zero", "timeout"])
def test_terminal_states_have_no_partial_predictions(
    generation_context: Any,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    app, _, _ = generation_context
    factory, settings = app.state.session_factory, app.state.settings
    job_id = _job(generation_context)

    def generate(_image: Any, _path: Any, _request: Any, checkpoint: Any) -> Any:
        if outcome == "zero":
            return
        yield _candidate(5)
        if outcome == "failure":
            raise RuntimeError("corrupt checkpoint output")
        if outcome == "cancel":
            with factory() as session:
                JobService(session).cancel(job_id)
        if outcome == "timeout":
            monkeypatch.setattr("reefvision.jobs.sam_image_proposals.time.monotonic", lambda: 1e15)
        checkpoint("extracting_candidates", 1, 16)

    monkeypatch.setattr("reefvision.jobs.sam_image_proposals.generate_candidates", generate)
    process_sam_image_proposals_job(settings, factory, job_id)
    with factory() as session:
        job = session.get(Job, job_id)
        assert (
            job.status
            == {
                "cancel": "cancelled",
                "failure": "failed",
                "zero": "succeeded",
                "timeout": "failed",
            }[outcome]
        )
        assert session.scalar(select(func.count()).select_from(PredictionProposal)) == 0
        assert session.scalar(select(func.count()).select_from(MaskAnnotation)) == 0


def test_restart_and_retry_use_persisted_request(
    generation_context: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, _, _ = generation_context
    factory, settings = app.state.session_factory, app.state.settings
    job_id = _job(generation_context)
    with factory() as session:
        session.get(Job, job_id).status = "running"
        session.commit()
        assert JobRepository(session).recover_interrupted_jobs() >= 1
        session.commit()
    monkeypatch.setattr(
        "reefvision.jobs.sam_image_proposals.generate_candidates", lambda *_: iter([])
    )
    assert process_sam_image_proposals_job(settings, factory, job_id)
    with factory() as session:
        job = session.get(Job, job_id)
        assert job.status == "succeeded"
        job.status = "failed"
        session.commit()
        assert JobService(session).retry(job_id).status == "queued"


def test_missing_provider_is_actionable_without_starting_job(
    generation_context: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from reefvision.domain.errors import ValidationError as DomainValidationError

    monkeypatch.setattr(
        "reefvision.services.sam_image_proposals.sam2_status",
        lambda *_: {"ready": False, "reason": "Local checkpoint missing"},
    )
    with pytest.raises(DomainValidationError, match="Choose/download SAM"):
        _job(generation_context)


def test_large_image_rejects_unbounded_tiles() -> None:
    from reefvision.domain.errors import ValidationError as DomainValidationError

    with pytest.raises(DomainValidationError, match="bounded SAM budget"):
        tile_boxes(100_000, 80_000, 512)


def test_api_contract_and_duplicate_submission(client: TestClient, generation_context: Any) -> None:
    app, project, image_id = generation_context
    from reefvision.api.routes.sam_image_proposals import router

    # Also exercise the standalone router before the frontend integration commit.
    if not any(getattr(route, "path", "").endswith("/sam-image-proposals") for route in app.routes):
        app.include_router(router, prefix="/api/v1")
    response = client.post(
        f"/api/v1/projects/{project['id']}/sam-image-proposals",
        json={"image_id": image_id, "device": "cpu", "variant": "base-plus"},
    )
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "queued"
    assert response.json()["request_json"]["variant"] == "base-plus"
    duplicate = client.post(
        f"/api/v1/projects/{project['id']}/sam-image-proposals", json={"image_id": image_id}
    )
    assert duplicate.status_code == 409
    cancelled = client.post(f"/api/v1/jobs/{response.json()['id']}/cancel")
    assert cancelled.status_code == 200, cancelled.text


def test_point_grid_adapter_reuses_embedding_and_emits_multiple_masks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    import torch
    from PIL import Image

    from reefvision.ml.sam_image_proposals import generate_candidates

    prompts = []
    encodings = []

    class Inputs(dict):
        def to(self, _device: Any) -> Any:
            return self

    class Processor:
        def __call__(self, **_kwargs: Any) -> Any:
            return Inputs(
                pixel_values=torch.zeros(1, 3, 80, 100), original_sizes=torch.tensor([[80, 100]])
            )

        def post_process_masks(self, masks: Any, _sizes: Any, **kwargs: Any) -> Any:
            assert kwargs["binarize"] is False
            return masks

    class Model:
        def get_image_embeddings(self, _pixels: Any) -> Any:
            encodings.append(True)
            return [torch.zeros(1)]

        def __call__(self, **kwargs: Any) -> Any:
            assert "pixel_values" not in kwargs and kwargs["multimask_output"] is True
            prompts.append(kwargs["input_points"].tolist())
            masks = torch.full((1, 1, 3, 80, 100), -2.0)
            for index in range(3):
                masks[0, 0, index, 5:10, 5 + index * 20 : 10 + index * 20] = 2
            return SimpleNamespace(pred_masks=masks, iou_scores=torch.tensor([[[0.9, 0.85, 0.95]]]))

    monkeypatch.setattr(
        "reefvision.ml.sam_image_proposals.load_runtime", lambda *_: (Model(), Processor(), "cpu")
    )
    updates = []
    generated = list(
        generate_candidates(
            Image.new("RGB", (100, 80)),
            "unused-local-checkpoint",
            SamImageProposalsRequest(
                image_id="00000000-0000-0000-0000-000000000001", points_per_side=2
            ),
            lambda *args: updates.append(args),
        )
    )
    assert len(generated) == 12
    assert len(encodings) == 1
    assert len(prompts) == 4 and prompts[0] != prompts[-1]
    assert all(candidate.mask.shape == (80, 100) for candidate in generated)
    assert updates[-1] == ("filtering", 4, 4)
