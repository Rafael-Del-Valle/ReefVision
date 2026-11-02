"""Persisted longitudinal series counts must reconcile with unverified input provenance."""

from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from reefvision.schemas.longitudinal_monitoring import LongitudinalAnalysisResponse
from reefvision.tests.test_longitudinal_monitoring import observation


def _result(client: TestClient) -> dict[str, object]:
    records = [
        observation("coral-A", "2026-04-01T12:00:00Z", 10, "a0"),
        observation("coral-A", "2026-04-02T12:00:00Z", 12, "a1"),
        observation("coral-B", "2026-04-01T12:00:00Z", 5, "b0"),
    ]
    response = client.post("/api/v1/ecology/longitudinal-analysis", json={"observations": records})
    assert response.status_code == 200, response.text
    return response.json()


def test_saved_series_denominators_accept_valid_incomplete_observation(
    client: TestClient,
) -> None:
    original = _result(client)
    parsed = LongitudinalAnalysisResponse.model_validate(original)
    assert parsed.observation_count == 3
    assert parsed.evaluated_series_count == 1
    assert parsed.incomplete_series_count == 1
    assert parsed.changes[0].observation_count == 2
    assert parsed.analysis_provenance.source_record_ids == ["a0", "a1", "b0"]
    assert parsed.evidence_level == "caller_supplied_unverified"


@pytest.mark.parametrize(
    ("tampering", "error"),
    [
        ("inflated_observation_count", "source provenance"),
        ("missing_source", "source provenance"),
        ("duplicate_source", "source provenance"),
        ("blank_source", "source provenance"),
        ("extra_source", "source provenance"),
        ("inflated_evaluated_series", "series denominator"),
        ("negative_incomplete_series", "series denominator"),
        ("inflated_incomplete_series", "series observation counts"),
        ("inflated_change_observations", "series observation counts"),
        ("orphan_baseline_source", "source endpoints"),
        ("orphan_final_source", "source endpoints"),
    ],
)
def test_saved_series_denominators_reject_forged_scientific_counts(
    client: TestClient, tampering: str, error: str
) -> None:
    forged = deepcopy(_result(client))
    sources = forged["analysis_provenance"]["source_record_ids"]
    change = forged["changes"][0]
    if tampering == "inflated_observation_count":
        forged["observation_count"] += 1
    elif tampering == "missing_source":
        sources.pop()
    elif tampering == "duplicate_source":
        sources[1] = sources[0]
    elif tampering == "blank_source":
        sources[1] = " "
    elif tampering == "extra_source":
        sources.append("invented")
    elif tampering == "inflated_evaluated_series":
        forged["evaluated_series_count"] += 1
    elif tampering == "negative_incomplete_series":
        forged["incomplete_series_count"] = -1
    elif tampering == "inflated_incomplete_series":
        forged["incomplete_series_count"] += 1
    elif tampering == "inflated_change_observations":
        change["observation_count"] += 1
    elif tampering == "orphan_baseline_source":
        change["baseline_source_record_id"] = "invented"
    elif tampering == "orphan_final_source":
        change["final_source_record_id"] = "invented"
    with pytest.raises(PydanticValidationError, match=error):
        LongitudinalAnalysisResponse.model_validate(forged)


def test_saved_series_denominators_reject_duplicate_organism_metric(
    client: TestClient,
) -> None:
    records = [
        observation("A", "2026-04-01T12:00:00Z", 1, "a0"),
        observation("A", "2026-04-02T12:00:00Z", 2, "a1"),
        observation("B", "2026-04-01T12:00:00Z", 3, "b0"),
        observation("B", "2026-04-02T12:00:00Z", 4, "b1"),
    ]
    response = client.post("/api/v1/ecology/longitudinal-analysis", json={"observations": records})
    assert response.status_code == 200, response.text
    original = response.json()
    assert LongitudinalAnalysisResponse.model_validate(original).evaluated_series_count == 2
    forged = deepcopy(original)
    forged["changes"][1]["organism_id"] = "A"
    with pytest.raises(PydanticValidationError, match="duplicate organism/metric"):
        LongitudinalAnalysisResponse.model_validate(forged)


def test_saved_series_denominators_reject_reused_endpoint_across_organisms(
    client: TestClient,
) -> None:
    records = [
        observation("A", "2026-04-01T12:00:00Z", 1, "a0"),
        observation("A", "2026-04-02T12:00:00Z", 2, "a1"),
        observation("B", "2026-04-01T12:00:00Z", 3, "b0"),
        observation("B", "2026-04-02T12:00:00Z", 4, "b1"),
    ]
    response = client.post("/api/v1/ecology/longitudinal-analysis", json={"observations": records})
    assert response.status_code == 200, response.text
    forged = deepcopy(response.json())
    forged["changes"][1]["baseline_source_record_id"] = "a0"
    with pytest.raises(PydanticValidationError, match="source endpoints"):
        LongitudinalAnalysisResponse.model_validate(forged)
