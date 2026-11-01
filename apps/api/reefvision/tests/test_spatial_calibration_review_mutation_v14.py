"""Mutation-safe durable spatial calibration reviews remain provisional evidence."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from reefvision.schemas.spatial_mesh_preview_v14 import MeshCalibrationReviewEvidence
from reefvision.services.spatial_calibration_review_v14 import SpatialCalibrationReviewService
from reefvision.tests.test_annotations import create_project

OBJ = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("independent_review_decision", "verified"),
        ("independent_reviewer_id", "operator-1"),
        ("reviewed_meters_per_unit", -0.01),
        ("reviewed_meters_per_unit", True),
        ("reviewed_geometry_sha256", "not-a-sha"),
    ],
)
def test_mutated_review_cannot_be_persisted(
    client: TestClient, field: str, value: object
) -> None:
    project_id = str(create_project(client, "Mutation-safe calibration receipt")["id"])
    base = f"/api/v1/projects/{project_id}"
    imported = client.post(f"{base}/spatial/assets", files={"file": ("colony.obj", OBJ)})
    assert imported.status_code == 201, imported.text
    asset = imported.json()
    evidence = {
        "calibration_operator_id": "operator-1",
        "independent_reviewer_id": "reviewer-2",
        "independent_review_decision": "inconclusive",
        "independent_review_note": "Provisional source ruler review",
        "reviewed_at_utc": "2026-10-02T12:00:00Z",
        "reviewed_geometry_sha256": "a" * 64,
        "reviewed_source_payload_sha256": asset["sha256"],
        "reviewed_spatial_source_asset_id": asset["id"],
        "reviewed_meters_per_unit": 0.01,
        "reviewed_calibration_method": "ruler",
        "reviewed_calibration_evidence": "Unverified survey ruler",
        "reviewed_relative_scale_uncertainty": 0.05,
    }
    mutable = MeshCalibrationReviewEvidence.model_validate(evidence)
    # Pydantic does not validate assignment by default; direct service callers
    # must not be able to persist invalid evidence after initial construction.
    setattr(mutable, field, value)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        service = SpatialCalibrationReviewService(session, app.state.settings)
        with pytest.raises(PydanticValidationError):
            service.create(project_id, asset["id"], mutable)
        assert service.list(project_id, asset["id"]) == []
        valid = service.create(
            project_id, asset["id"], MeshCalibrationReviewEvidence.model_validate(evidence)
        )
        assert valid.calibration_verified is False
        assert valid.reviewer_authenticated is False
        assert [record.id for record in service.list(project_id, asset["id"])] == [valid.id]
    fetched = client.get(f"{base}/spatial/assets/{asset['id']}/calibration-reviews/{valid.id}")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["evidence_sha256"] == valid.evidence_sha256
