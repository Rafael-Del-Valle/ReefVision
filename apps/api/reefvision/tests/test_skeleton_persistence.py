from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.domain.errors import ValidationError
from reefvision.schemas.skeletonization import (
    SkeletonAnalysisCreateRequest,
    SkeletonAnalysisReviewRequest,
)
from reefvision.services.skeletonization import SkeletonizationService
from reefvision.tests.test_annotations import create_project, import_one


def _seed_mask(client: TestClient) -> tuple[str, str]:
    project = create_project(client, "Persisted skeleton analysis")
    report = import_one(client, project["id"], size=(80, 60))
    image_id = report["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]
    mask_id = "719e247d-31f9-4f19-b0ba-4725cd781b66"
    response = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [],
            "mask_annotations": [
                {
                    "id": mask_id,
                    "label_class_id": class_id,
                    "geometry_kind": "polygon",
                    "points": [
                        {"x": 10, "y": 20},
                        {"x": 60, "y": 20},
                        {"x": 60, "y": 30},
                        {"x": 10, "y": 30},
                    ],
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    return image_id, mask_id


def test_persisted_analysis_is_deduplicated_and_hashed(
    client: TestClient,
) -> None:
    _image_id, mask_id = _seed_mask(client)
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        service = SkeletonizationService(session, app.state.settings)
        payload = SkeletonAnalysisCreateRequest()
        first = service.persist_analysis(mask_id, payload)
        second = service.persist_analysis(mask_id, payload)

        assert second.id == first.id
        assert first.analysis_revision == 1
        assert first.source_kind == "automatic"
        assert len(first.input_mask_sha256) == 64
        assert len(first.parameters_sha256) == 64
        assert len(first.result_sha256) == 64
        assert first.result.mask_annotation_id == mask_id
        assert first.stale is False



def test_persisted_analysis_review_is_explicit(client: TestClient) -> None:
    _image_id, mask_id = _seed_mask(client)
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        service = SkeletonizationService(session, app.state.settings)
        record = service.persist_analysis(
            mask_id,
            SkeletonAnalysisCreateRequest(),
        )
        reviewed = service.review_persisted_analysis(
            record.id,
            SkeletonAnalysisReviewRequest(
                review_status="approved",
                note="Reviewed against the source mask.",
            ),
        )

        assert reviewed.review_status == "approved"
        assert reviewed.reviewed_by == "local_user"
        assert reviewed.reviewed_at is not None
        assert reviewed.review_note == "Reviewed against the source mask."
        assert len(service.list_persisted_analyses(mask_id)) == 1



def test_calibration_change_marks_saved_analysis_stale(
    client: TestClient,
) -> None:
    image_id, mask_id = _seed_mask(client)
    app = cast(FastAPI, client.app)

    with app.state.session_factory() as session:
        service = SkeletonizationService(session, app.state.settings)
        original = service.persist_analysis(
            mask_id,
            SkeletonAnalysisCreateRequest(),
        )

    calibrated = client.put(
        f"/api/v1/images/{image_id}/measurement-calibration",
        json={
            "distance_per_pixel": 0.1,
            "unit": "mm",
            "source": "manual",
        },
    )
    assert calibrated.status_code == 200, calibrated.text

    with app.state.session_factory() as session:
        service = SkeletonizationService(session, app.state.settings)
        stale = service.get_persisted_analysis(original.id)

        assert stale.stale_calibration is True
        assert stale.stale is True

        with pytest.raises(
            ValidationError,
            match="must be regenerated before review",
        ):
            service.review_persisted_analysis(
                original.id,
                SkeletonAnalysisReviewRequest(
                    review_status="approved",
                ),
            )

        regenerated = service.persist_analysis(
            mask_id,
            SkeletonAnalysisCreateRequest(),
        )
        assert regenerated.id != original.id
        assert regenerated.calibration_sha256 is not None
        assert regenerated.result.calibrated is True
        assert regenerated.stale is False
