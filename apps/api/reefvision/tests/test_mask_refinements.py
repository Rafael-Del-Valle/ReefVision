"""Non-destructive selected-mask refinement and persisted history contracts."""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import MaskAnnotation, MaskAnnotationEvent
from reefvision.ml.providers import AssistPrediction, mask_to_box
from reefvision.tests.test_annotations import create_project, import_one


def setup_mask(client: TestClient) -> tuple[str, str]:
    project = create_project(client)
    image_id = import_one(client, project["id"])["successful"][0]["image_id"]
    mask_id = str(uuid4())
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        session.add(
            MaskAnnotation(
                id=mask_id,
                image_id=image_id,
                label_class_id=project["label_classes"][0]["id"],
                geometry_kind="polygon",
                polygon_json=[[10, 10], [30, 10], [30, 30], [10, 30]],
                x_min=10,
                y_min=10,
                x_max=30,
                y_max=30,
                area_pixels=400,
                provenance_json={"instance_id": "coral-3", "reviewer": "scientist"},
                measurement_json={"surface_model": "none"},
                source_type="human",
                revision=1,
            )
        )
        session.commit()
    return image_id, mask_id


def stub_prediction(monkeypatch: pytest.MonkeyPatch, *, drastic: bool = False) -> None:
    def infer(*args: Any, **kwargs: Any) -> tuple[AssistPrediction, dict[str, Any]]:
        prior = kwargs["prior"]
        assert prior.shape == (60, 80)
        assert prior.sum() == 400
        output = prior.copy()
        if drastic:
            output[:] = True
        else:
            output[10, 10:30] = False
        return AssistPrediction(mask=output, box=mask_to_box(output), score=0.9), {
            "provider_name": "sam2",
            "checkpoint_sha256": "a" * 64,
        }

    monkeypatch.setattr("reefvision.services.mask_refinements.infer_refinement", infer)


def preview(client: TestClient, mask_id: str) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/mask-annotations/{mask_id}/refinements",
        json={
            "variant": "tiny",
            "expected_revision": 1,
        },
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def test_preview_replace_restart_undo_redo(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_prediction(monkeypatch)
    image_id, mask_id = setup_mask(client)
    candidate = preview(client, mask_id)
    assert candidate["old_area_pixels"] == 400
    assert candidate["proposed_area_pixels"] == 380
    assert candidate["iou"] == 0.95
    assert candidate["warnings"]
    unchanged = client.get(f"/api/v1/images/{image_id}/annotations").json()
    assert len(unchanged["mask_annotations"]) == 1
    assert unchanged["mask_annotations"][0]["geometry_kind"] == "polygon"
    assert unchanged["mask_annotations"][0]["revision"] == 1
    url = f"/api/v1/mask-refinements/{candidate['candidate_id']}"
    assert client.get(url).json()["status"] == "pending"
    assert client.get(candidate["mask_url"]).headers["content-type"] == "image/png"
    accepted = client.post(url + "/accept", json={"expected_revision": 1})
    assert accepted.status_code == 200, accepted.text
    mask = accepted.json()["mask_annotation"]
    assert mask["id"] == mask_id
    assert mask["source_type"] == "human"
    assert mask["provenance_json"]["instance_id"] == "coral-3"
    assert mask["area_pixels"] == 380
    assert mask["revision"] == 2
    assert client.post(url + "/accept", json={"expected_revision": 1}).status_code == 409
    undone = client.post(url + "/undo", json={"expected_revision": 2})
    assert undone.status_code == 200, undone.text
    assert undone.json()["mask_annotation"]["polygon_json"] == [
        [10, 10],
        [30, 10],
        [30, 30],
        [10, 30],
    ]
    redone = client.post(url + "/redo", json={"expected_revision": 3})
    assert redone.status_code == 200, redone.text
    assert redone.json()["mask_annotation"]["mask_path"] == mask["mask_path"]
    final = client.get(f"/api/v1/images/{image_id}/annotations").json()
    assert len(final["mask_annotations"]) == 1
    assert final["image"]["annotation_revision"] == 3
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        events = session.query(MaskAnnotationEvent).filter_by(mask_annotation_id=mask_id).all()
        assert [event.event_type for event in events] == [
            "refined",
            "refinement_undone",
            "refinement_redone",
        ]
        assert events[0].before_json["measurement_json"] == {"surface_model": "none"}


def test_stale_mask_discard_and_large_change_guard(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_prediction(monkeypatch, drastic=True)
    _, mask_id = setup_mask(client)
    candidate = preview(client, mask_id)
    url = f"/api/v1/mask-refinements/{candidate['candidate_id']}"
    assert candidate["requires_confirmation"] is True
    assert client.post(url + "/accept", json={"expected_revision": 1}).status_code == 400
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        session.get(MaskAnnotation, mask_id).revision = 2
        session.commit()
    assert (
        client.post(
            url + "/accept", json={"expected_revision": 2, "confirm_large_change": True}
        ).status_code
        == 409
    )
    assert client.post(url + "/discard").json()["status"] == "discarded"
    assert (
        client.post(
            url + "/accept", json={"expected_revision": 2, "confirm_large_change": True}
        ).status_code
        == 409
    )


def test_guiding_prompts_preserve_holes_and_fragments() -> None:
    from reefvision.ml.mask_refinement import guiding_prompts

    prior = np.zeros((40, 60), dtype=bool)
    prior[5:30, 5:30] = True
    prior[12:22, 12:22] = False
    prior[35, 50] = True
    positive, negative, roi = guiding_prompts(prior)
    assert any(p.x == 50.5 and p.y == 35.5 for p in positive)
    assert any(12 <= p.x < 22 and 12 <= p.y < 22 for p in negative)
    assert all(prior[int(p.y), int(p.x)] for p in positive)
    assert all(not prior[int(p.y), int(p.x)] for p in negative)
    assert roi.x_min <= 5 and roi.x_max > 50


def test_edit_expiry_and_unrelated_image_revision(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from reefvision.db.models import ImageAsset, Job
    from reefvision.ml.providers import mask_to_png_base64

    stub_prediction(monkeypatch)
    image_id, mask_id = setup_mask(client)
    candidate = preview(client, mask_id)
    url = f"/api/v1/mask-refinements/{candidate['candidate_id']}"
    edited = np.zeros((60, 80), dtype=bool)
    edited[10:30, 10:30] = True
    edited[18:20, 18:20] = False
    edit = client.put(url + "/geometry", json={"mask_png_base64": mask_to_png_base64(edited)})
    assert edit.status_code == 200, edit.text
    assert edit.json()["requires_confirmation"] is True
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        session.get(ImageAsset, image_id).annotation_revision = 9
        session.commit()
    accepted = client.post(
        url + "/accept", json={"expected_revision": 1, "confirm_large_change": True}
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["image"]["annotation_revision"] == 10
    assert accepted.json()["mask_annotation"]["area_pixels"] == 396
    assert accepted.json()["mask_annotation"]["provenance_json"]["last_refinement"]["edited"]

    # Expiration is persisted; a fresh service/session must reject an expired preview.
    _, other = setup_mask(client)
    expired = preview(client, other)
    with app.state.session_factory() as session:
        job = session.get(Job, expired["candidate_id"])
        job.result_json = {**job.result_json, "expires_at": "2000-01-01T00:00:00+00:00"}
        session.commit()
    assert (
        client.post(
            f"/api/v1/mask-refinements/{expired['candidate_id']}/accept",
            json={"expected_revision": 1},
        ).status_code
        == 409
    )


def test_pending_raster_edit_preserves_model_output_and_blocks_duplicate(
    client: TestClient,
) -> None:
    from reefvision.db.models import PredictionProposal, WorkflowArtifact
    from reefvision.ml.providers import mask_to_png_base64
    from reefvision.services.workflow_prompt_assist import create_prompt_assist_mask_proposals
    from reefvision.tests.test_workflow_prompt_assist_phase10 import (
        FakeAssistProvider,
        _seed_reviewed_boxes,
    )

    project, _, model_id, artifact_id, _ = _seed_reviewed_boxes(client)
    app = cast(FastAPI, client.app)
    ids = []
    with app.state.session_factory() as session:
        for _ in range(2):
            result = create_prompt_assist_mask_proposals(
                session,
                app.state.settings,
                project_id=str(project["id"]),
                boxes_artifact=session.get(WorkflowArtifact, artifact_id),
                model_id=model_id,
                provider_factory=lambda _: FakeAssistProvider(),
            )
            ids.extend(result["proposal_ids"])
        proposal = session.get(PredictionProposal, ids[0])
        old_path = proposal.mask_path
        old_sha = proposal.mask_content_sha256
    raster = np.zeros((80, 100), dtype=bool)
    raster[12:48, 10:42] = True
    raster[12, 10] = False
    response = client.put(
        f"/api/v1/prediction-proposals/{ids[0]}/mask",
        json={"mask_png_base64": mask_to_png_base64(raster)},
    )
    assert response.status_code == 200, response.text
    changed = response.json()
    assert changed["mask_path"] != old_path
    assert changed["mask_content_sha256"] != old_sha
    accepted = client.post(f"/api/v1/prediction-proposals/{ids[0]}/accept", json={})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["proposal"]["review_status"] == "edited_and_accepted"
    duplicate = client.post(f"/api/v1/prediction-proposals/{ids[1]}/accept", json={})
    assert duplicate.status_code == 409, duplicate.text
    assert "Refine selected mask" in duplicate.text
    assert (
        client.put(
            f"/api/v1/prediction-proposals/{ids[0]}/mask",
            json={"mask_png_base64": mask_to_png_base64(raster)},
        ).status_code
        == 409
    )


def test_raster_prior_holes_fragments_and_corrupt_candidate(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from reefvision.db.models import Job
    from reefvision.storage.mask_refinements import save_candidate

    image_id, mask_id = setup_mask(client)
    app = cast(FastAPI, client.app)
    original = np.zeros((60, 80), dtype=bool)
    original[10:30, 10:30] = True
    original[15:20, 15:20] = False
    original[40, 50] = True
    with app.state.session_factory() as session:
        mask = session.get(MaskAnnotation, mask_id)
        project = mask.image.project
        geometry = save_candidate(app.state.settings, project.storage_root, image_id, original)
        for key in ("mask_path", "area_pixels", "x_min", "y_min", "x_max", "y_max"):
            setattr(mask, key, geometry[key])
        mask.geometry_kind = "raster_mask"
        mask.polygon_json = None
        session.commit()

    def infer(**kwargs: Any) -> tuple[AssistPrediction, dict[str, Any]]:
        assert np.array_equal(kwargs["prior"], original)
        return AssistPrediction(mask=original.copy(), box=mask_to_box(original), score=0.9), {}

    monkeypatch.setattr("reefvision.services.mask_refinements.infer_refinement", infer)
    candidate = preview(client, mask_id)
    assert candidate["proposed_area_pixels"] == 376
    with app.state.session_factory() as session:
        job = session.get(Job, candidate["candidate_id"])
        path = app.state.settings.resolved_data_dir / job.result_json["geometry"]["mask_path"]
        path.write_bytes(b"broken")
    response = client.post(
        f"/api/v1/mask-refinements/{candidate['candidate_id']}/accept",
        json={"expected_revision": 1},
    )
    assert response.status_code == 400
    current = client.get(f"/api/v1/images/{image_id}/annotations").json()["mask_annotations"][0]
    assert current["revision"] == 1
    assert current["mask_path"] == geometry["mask_path"]


def test_empty_and_wrong_dimensions(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from reefvision.ml.providers import mask_to_png_base64

    stub_prediction(monkeypatch)
    _, mask_id = setup_mask(client)
    candidate = preview(client, mask_id)
    url = f"/api/v1/mask-refinements/{candidate['candidate_id']}/geometry"
    for raster in (np.zeros((60, 80), dtype=bool), np.ones((20, 30), dtype=bool)):
        assert (
            client.put(url, json={"mask_png_base64": mask_to_png_base64(raster)}).status_code == 400
        )


def test_class_agnostic_bulk_assignment_and_transactional_duplicates(client: TestClient) -> None:
    from reefvision.db.models import PredictionProposal, WorkflowArtifact
    from reefvision.ml.providers import mask_to_png_base64
    from reefvision.services.workflow_prompt_assist import create_prompt_assist_mask_proposals
    from reefvision.tests.test_workflow_prompt_assist_phase10 import (
        FakeAssistProvider,
        _seed_reviewed_boxes,
    )

    project, _, model_id, artifact_id, _ = _seed_reviewed_boxes(client)
    app = cast(FastAPI, client.app)
    ids = []
    with app.state.session_factory() as session:
        for _ in range(2):
            result = create_prompt_assist_mask_proposals(
                session,
                app.state.settings,
                project_id=str(project["id"]),
                boxes_artifact=session.get(WorkflowArtifact, artifact_id),
                model_id=model_id,
                provider_factory=lambda _: FakeAssistProvider(),
            )
            ids.extend(result["proposal_ids"])
        proposal = session.get(PredictionProposal, ids[0])
        proposal.label_class_id = None
        image_id = proposal.image_id
        session.commit()
    bulk_url = "/api/v1/prediction-proposals/bulk-review"
    class_id = project["label_classes"][1]["id"]
    failed = client.post(
        bulk_url, json={"action": "accept", "proposal_ids": ids, "label_class_id": class_id}
    )
    assert failed.status_code == 409, failed.text
    assert client.get(f"/api/v1/images/{image_id}/annotations").json()["mask_annotations"] == []
    raster = np.zeros((80, 100), dtype=bool)
    raster[12:48, 55:85] = True
    assert (
        client.put(
            f"/api/v1/prediction-proposals/{ids[1]}/mask",
            json={"mask_png_base64": mask_to_png_base64(raster)},
        ).status_code
        == 200
    )
    accepted = client.post(
        bulk_url, json={"action": "accept", "proposal_ids": ids, "label_class_id": class_id}
    )
    assert accepted.status_code == 200, accepted.text
    masks = accepted.json()["created_mask_annotations"]
    assert {mask["label_class_id"] for mask in masks} == {
        class_id,
        project["label_classes"][0]["id"],
    }
