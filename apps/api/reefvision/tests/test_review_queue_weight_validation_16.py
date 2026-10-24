"""Regression tests for scientifically meaningful QC scoring weights."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from reefvision.schemas.review_queues import ReviewScoreWeights
from reefvision.tests.test_annotations import create_project, import_one


@pytest.mark.parametrize(
    "invalid_weights",
    [
        {"low_mean_confidence": float("inf")},
        {"low_mean_confidence": float("nan")},
        {"low_mean_confidence": 1e308, "low_min_confidence": 1e308},
    ],
)
def test_weight_schema_rejects_nonfinite_inputs_and_overflow(invalid_weights):
    with pytest.raises(PydanticValidationError):
        ReviewScoreWeights.model_validate(invalid_weights)


def test_weight_schema_rejects_all_zero_priority_formula():
    all_zero = {name: 0.0 for name in ReviewScoreWeights.model_fields}
    with pytest.raises(PydanticValidationError, match="finite, positive total"):
        ReviewScoreWeights.model_validate(all_zero)


def test_standalone_qc_api_rejects_invalid_weight_vectors_atomically(client: TestClient):
    project = create_project(client, "QC finite scoring weights")
    defaults = ReviewScoreWeights().model_dump()
    invalid_vectors = [
        {name: 0.0 for name in defaults},
        {**defaults, "low_mean_confidence": 1e308, "low_min_confidence": 1e308},
    ]
    for weights in invalid_vectors:
        response = client.post(
            f"/api/v1/projects/{project['id']}/review-queues",
            json={"signal_weights": weights},
        )
        assert response.status_code == 422, response.text
    listing = client.get(f"/api/v1/projects/{project['id']}/review-queues")
    assert listing.status_code == 200, listing.text
    assert listing.json() == []


def test_standalone_qc_api_allows_selected_positive_weight(client: TestClient):
    project = create_project(client, "QC selected scoring signal")
    imported = import_one(
        client,
        project["id"],
        filename="weighted-qc.png",
        relative_path="qc/weighted-qc.png",
    )
    assert len(imported["successful"]) == 1
    weights = {name: 0.0 for name in ReviewScoreWeights.model_fields}
    weights["unreviewed_state"] = 1.0
    response = client.post(
        f"/api/v1/projects/{project['id']}/review-queues",
        json={"signal_weights": weights},
    )
    assert response.status_code == 201, response.text
    assert response.json()["configuration_json"]["weights"] == weights
    assert response.json()["item_count"] == 1
