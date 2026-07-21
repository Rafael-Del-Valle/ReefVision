from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from reefvision.db.models import (
    ImageAsset,
    Job,
    MaskAnnotation,
    MaskAnnotationEvent,
    ModelRegistration,
    PredictionProposal,
    Project,
)
from reefvision.domain.errors import ValidationError
from reefvision.schemas.predictions import PredictionAcceptRequest
from reefvision.services.semantic_predictions import SemanticPredictionService
from reefvision.storage.masks import write_prediction_mask_png
from reefvision.storage.projects import resolve_managed_project_path
from reefvision.tests.test_annotations import create_project, import_one


@dataclass(frozen=True)
class ReviewFixture:
    project_id: str
    project_storage_root: str
    image_id: str
    label_class_id: str
    model_id: str
    job_id: str
    proposal_ids: tuple[str, str]


def _mask_png(
    size: tuple[int, int],
    bounds: tuple[int, int, int, int],
) -> bytes:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rectangle(bounds, fill=255)
    stream = BytesIO()
    mask.save(stream, format="PNG")
    return stream.getvalue()


def _seed_review_proposals(
    client: TestClient,
    *,
    geometry_kind: str,
) -> ReviewFixture:
    project_payload = create_project(client, f"{geometry_kind} review safety")
    report = import_one(client, project_payload["id"])
    image_id = report["successful"][0]["image_id"]
    label_class_id = project_payload["label_classes"][0]["id"]
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        project = session.get(Project, project_payload["id"])
        image = session.get(ImageAsset, image_id)
        assert project is not None
        assert image is not None
        token = uuid4().hex
        model = ModelRegistration(
            project_id=project.id,
            purpose="segmenter",
            display_name=f"Review segmenter {token}",
            source_filename="review-segmenter.pt",
            managed_path=f"{project.storage_root}/models/{token}.pt",
            sha256=token.ljust(64, "0"),
            file_size_bytes=1,
            framework="ultralytics",
            task="segment",
            provider_name="ultralytics",
            provider_version="review-test",
            class_map_json={
                "labels": ["soft coral"],
                "mapping": {"soft coral": label_class_id},
            },
            input_size_json={"imgsz": 640},
            metadata_json={"proposal_geometry": geometry_kind},
        )
        job = Job(
            project_id=project.id,
            job_type="inference",
            status="succeeded",
            progress_current=1,
            progress_total=1,
            request_json={"model_task": "segment"},
        )
        session.add_all([model, job])
        session.flush()

        proposal_ids: list[str] = []
        for index in range(2):
            proposal_id = str(uuid4())
            left = 8 + index * 24
            top = 6 + index * 18
            right = left + 28
            bottom = top + 24
            polygon = [
                [float(left), float(top)],
                [float(right), float(top + 2)],
                [float(right - 3), float(bottom)],
                [float(left + 2), float(bottom - 2)],
            ]
            mask_path: str | None = None
            mask_checksum: str | None = None
            if geometry_kind == "raster_mask":
                stored = write_prediction_mask_png(
                    app.state.settings,
                    project_storage_root=project.storage_root,
                    proposal_id=proposal_id,
                    png_bytes=_mask_png(
                        (image.width_px, image.height_px),
                        (left, top, right - 1, bottom - 1),
                    ),
                    expected_width=image.width_px,
                    expected_height=image.height_px,
                )
                mask_path = stored.relative_path
                mask_checksum = stored.content_sha256
            proposal = PredictionProposal(
                id=proposal_id,
                project_id=project.id,
                image_id=image.id,
                model_id=model.id,
                inference_job_id=job.id,
                model_checksum=model.sha256,
                label_class_id=label_class_id,
                predicted_label="soft coral",
                predicted_index=index + 3,
                confidence=0.93 - index * 0.1,
                geometry_kind=geometry_kind,
                polygon_json=polygon if geometry_kind == "polygon_mask" else None,
                mask_path=mask_path,
                mask_content_sha256=mask_checksum,
                x_min=float(left),
                y_min=float(top),
                x_max=float(right),
                y_max=float(bottom),
                review_status="pending",
                inference_settings_json={"task": "segment", "device": "cpu"},
                provenance_json={
                    "provider_name": "ultralytics",
                    "source_run_marker": "run-42",
                    "instance_number": index,
                },
            )
            session.add(proposal)
            proposal_ids.append(proposal_id)
        session.commit()

    return ReviewFixture(
        project_id=project_payload["id"],
        project_storage_root=project.storage_root,
        image_id=image_id,
        label_class_id=label_class_id,
        model_id=model.id,
        job_id=job.id,
        proposal_ids=(proposal_ids[0], proposal_ids[1]),
    )


def _assert_source_provenance(
    provenance: dict[str, object],
    fixture: ReviewFixture,
    proposal_id: str,
) -> None:
    assert provenance["source_model_id"] == fixture.model_id
    assert provenance["source_prediction_id"] == proposal_id
    assert provenance["inference_job_id"] == fixture.job_id
    assert provenance["source_run_id"] == fixture.job_id
    assert provenance["original_predicted_index"] == 3
    assert provenance["original_label_class_id"] == fixture.label_class_id
    assert provenance["original_predicted_box"] == {
        "x_min": 8.0,
        "y_min": 6.0,
        "x_max": 36.0,
        "y_max": 30.0,
    }
    assert provenance["source_proposal_provenance"] == {
        "provider_name": "ultralytics",
        "source_run_marker": "run-42",
        "instance_number": 0,
    }


def test_polygon_accept_is_idempotent_rejects_and_remains_editable(
    client: TestClient,
) -> None:
    fixture = _seed_review_proposals(client, geometry_kind="polygon_mask")
    proposal_id, rejected_id = fixture.proposal_ids
    accept_url = f"/api/v1/prediction-proposals/{proposal_id}/accept"

    accepted = client.post(accept_url, json={"label_class_id": fixture.label_class_id})
    repeated = client.post(accept_url, json={"label_class_id": fixture.label_class_id})
    rejected = client.post(f"/api/v1/prediction-proposals/{rejected_id}/reject")

    assert accepted.status_code == 200, accepted.text
    assert repeated.status_code == 200, repeated.text
    assert rejected.status_code == 200, rejected.text
    accepted_mask = accepted.json()["mask_annotation"]
    repeated_mask = repeated.json()["mask_annotation"]
    assert repeated_mask["id"] == accepted_mask["id"]
    assert repeated.json()["proposal"]["accepted_mask_annotation_id"] == accepted_mask["id"]
    assert rejected.json()["proposal"]["review_status"] == "rejected"
    _assert_source_provenance(accepted_mask["provenance_json"], fixture, proposal_id)

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        image = session.get(ImageAsset, fixture.image_id)
        assert image is not None
        assert image.annotation_revision == 1
        assert session.query(MaskAnnotation).filter_by(image_id=fixture.image_id).count() == 1
        assert session.query(MaskAnnotationEvent).filter_by(image_id=fixture.image_id).count() == 1

    edited = client.put(
        f"/api/v1/images/{fixture.image_id}/annotations",
        json={
            "base_revision": 1,
            "annotation_status": "in_progress",
            "annotations": [],
            "mask_annotations": [
                {
                    "id": accepted_mask["id"],
                    "label_class_id": fixture.label_class_id,
                    "geometry_kind": "polygon",
                    "points": [
                        {"x": 9, "y": 7},
                        {"x": 37, "y": 9},
                        {"x": 34, "y": 31},
                        {"x": 11, "y": 29},
                    ],
                }
            ],
        },
    )
    assert edited.status_code == 200, edited.text
    edited_mask = edited.json()["mask_annotations"][0]
    assert edited_mask["source_type"] == "accepted_prediction"
    assert edited_mask["revision"] == 2
    _assert_source_provenance(edited_mask["provenance_json"], fixture, proposal_id)


def test_raster_accept_is_idempotent_rejects_and_remains_editable(
    client: TestClient,
) -> None:
    fixture = _seed_review_proposals(client, geometry_kind="raster_mask")
    proposal_id, rejected_id = fixture.proposal_ids
    accept_url = f"/api/v1/prediction-proposals/{proposal_id}/accept"

    accepted = client.post(accept_url, json={"label_class_id": fixture.label_class_id})
    assert accepted.status_code == 200, accepted.text
    accepted_mask = accepted.json()["mask_annotation"]
    app = cast(FastAPI, client.app)
    accepted_path = resolve_managed_project_path(
        app.state.settings,
        accepted_mask["mask_path"],
    )
    files_before_retry = set(accepted_path.parent.glob("*.png"))

    repeated = client.post(accept_url, json={"label_class_id": fixture.label_class_id})
    rejected = client.post(f"/api/v1/prediction-proposals/{rejected_id}/reject")

    assert repeated.status_code == 200, repeated.text
    assert rejected.status_code == 200, rejected.text
    assert repeated.json()["mask_annotation"]["id"] == accepted_mask["id"]
    assert set(accepted_path.parent.glob("*.png")) == files_before_retry
    assert rejected.json()["proposal"]["review_status"] == "rejected"
    _assert_source_provenance(accepted_mask["provenance_json"], fixture, proposal_id)

    with app.state.session_factory() as session:
        image = session.get(ImageAsset, fixture.image_id)
        assert image is not None
        assert image.annotation_revision == 1
        assert session.query(MaskAnnotation).filter_by(image_id=fixture.image_id).count() == 1
        assert session.query(MaskAnnotationEvent).filter_by(image_id=fixture.image_id).count() == 1

    edited = client.post(
        f"/api/v1/images/{fixture.image_id}/raster-mask-edits",
        json={
            "base_revision": 1,
            "mask_annotation_id": accepted_mask["id"],
            "label_class_id": fixture.label_class_id,
            "mode": "paint",
            "brush_radius": 2,
            "strokes": [{"points": [{"x": 45, "y": 40}]}],
        },
    )
    assert edited.status_code == 200, edited.text
    edited_mask = edited.json()["mask_annotation"]
    assert edited_mask["source_type"] == "accepted_prediction"
    assert edited_mask["revision"] == 2
    _assert_source_provenance(edited_mask["provenance_json"], fixture, proposal_id)


def test_raster_preview_rejects_a_noncanonical_managed_path(
    client: TestClient,
) -> None:
    fixture = _seed_review_proposals(client, geometry_kind="raster_mask")
    proposal_id = fixture.proposal_ids[0]
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        proposal = session.get(PredictionProposal, proposal_id)
        image = session.get(ImageAsset, fixture.image_id)
        assert proposal is not None
        assert image is not None
        proposal.mask_path = image.managed_path
        session.commit()

    with app.state.session_factory() as session:
        service = SemanticPredictionService(session, app.state.settings)
        with pytest.raises(ValidationError, match="prediction-masks"):
            service.raster_mask_file(proposal_id)


def test_raster_preview_rejects_a_path_alias_for_the_canonical_mask(
    client: TestClient,
) -> None:
    fixture = _seed_review_proposals(client, geometry_kind="raster_mask")
    proposal_id = fixture.proposal_ids[0]
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        proposal = session.get(PredictionProposal, proposal_id)
        assert proposal is not None
        assert proposal.mask_path is not None
        proposal.mask_path = proposal.mask_path.replace(
            "/prediction-masks/",
            "/prediction-masks/./",
        )
        session.commit()

    with app.state.session_factory() as session:
        service = SemanticPredictionService(session, app.state.settings)
        with pytest.raises(ValidationError, match="does not match"):
            service.raster_mask_file(proposal_id)


def test_raster_accept_removes_copied_mask_when_event_creation_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _seed_review_proposals(client, geometry_kind="raster_mask")
    proposal_id = fixture.proposal_ids[0]
    app = cast(FastAPI, client.app)
    annotation_directory = resolve_managed_project_path(
        app.state.settings,
        f"{fixture.project_storage_root}/masks/{fixture.image_id}",
    )
    files_before = (
        set(annotation_directory.glob("*.png")) if annotation_directory.exists() else set()
    )

    with app.state.session_factory() as session:
        service = SemanticPredictionService(session, app.state.settings)

        def fail_add_event(_event: MaskAnnotationEvent) -> None:
            raise RuntimeError("forced review event failure")

        monkeypatch.setattr(service.mask_annotations, "add_event", fail_add_event)
        with pytest.raises(RuntimeError, match="forced review event failure"):
            service.accept(
                proposal_id,
                PredictionAcceptRequest(label_class_id=fixture.label_class_id),
            )

    files_after = (
        set(annotation_directory.glob("*.png")) if annotation_directory.exists() else set()
    )
    assert files_after == files_before
    with app.state.session_factory() as session:
        proposal = session.get(PredictionProposal, proposal_id)
        assert proposal is not None
        assert proposal.review_status == "pending"
        assert proposal.accepted_mask_annotation_id is None
        assert session.query(MaskAnnotation).filter_by(image_id=fixture.image_id).count() == 0
        assert session.query(MaskAnnotationEvent).filter_by(image_id=fixture.image_id).count() == 0


def test_raster_accept_removes_copied_mask_when_commit_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _seed_review_proposals(client, geometry_kind="raster_mask")
    proposal_id = fixture.proposal_ids[0]
    app = cast(FastAPI, client.app)
    annotation_directory = resolve_managed_project_path(
        app.state.settings,
        f"{fixture.project_storage_root}/masks/{fixture.image_id}",
    )
    files_before = (
        set(annotation_directory.glob("*.png")) if annotation_directory.exists() else set()
    )

    with app.state.session_factory() as session:
        service = SemanticPredictionService(session, app.state.settings)

        def fail_commit() -> None:
            raise RuntimeError("forced review commit failure")

        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="forced review commit failure"):
            service.accept(
                proposal_id,
                PredictionAcceptRequest(label_class_id=fixture.label_class_id),
            )

    files_after = (
        set(annotation_directory.glob("*.png")) if annotation_directory.exists() else set()
    )
    assert files_after == files_before
    with app.state.session_factory() as session:
        proposal = session.get(PredictionProposal, proposal_id)
        assert proposal is not None
        assert proposal.review_status == "pending"
        assert proposal.accepted_mask_annotation_id is None
        assert session.query(MaskAnnotation).filter_by(image_id=fixture.image_id).count() == 0
        assert session.query(MaskAnnotationEvent).filter_by(image_id=fixture.image_id).count() == 0
