"""Scientific guards for the first ReefVision 1.2 longitudinal analysis increment."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as SchemaValidationError

from reefvision.domain.errors import ValidationError
from reefvision.domain.longitudinal_monitoring import analyze_longitudinal
from reefvision.schemas.longitudinal_monitoring import LongitudinalAnalysisRequest


def observation(
    organism: str,
    when: str,
    value: float,
    source: str,
    *,
    unit: str = "count",
    metric: str = "polyp_count",
) -> dict[str, object]:
    return {
        "organism_id": organism,
        "metric_name": metric,
        "observed_at": when,
        "value": value,
        "source_record_id": source,
        "unit": unit,
    }


def test_per_organism_changes_and_zero_baseline() -> None:
    request = LongitudinalAnalysisRequest(
        observations=[
            observation("coral-A", "2026-07-03T00:00:00Z", 12, "a2"),
            observation("coral-B", "2026-07-03T00:00:00Z", 4, "b2"),
            observation("coral-A", "2026-07-01T00:00:00-05:00", 10, "a1"),
            observation("coral-B", "2026-07-01T00:00:00Z", 0, "b1"),
        ]
    )
    result = analyze_longitudinal(request)
    assert result.analysis_level == "organism"
    assert result.evidence_level == "caller_supplied_unverified"
    assert result.evaluated_series_count == 2
    coral_a, coral_b = result.changes
    assert coral_a.organism_id == "coral-A"
    assert coral_a.absolute_change == 2
    assert coral_a.percent_change == pytest.approx(20.0)
    assert coral_a.elapsed_days == pytest.approx(43 / 24)
    assert coral_b.absolute_change == 4
    assert coral_b.percent_change is None
    assert result.incomplete_series_count == 0


def test_singletons_are_reported_not_treated_as_zero_change() -> None:
    result = analyze_longitudinal(
        LongitudinalAnalysisRequest(
            observations=[
                observation("A", "2026-04-01T12:00:00Z", 2, "a1"),
                observation("B", "2026-04-01T12:00:00Z", 4, "b1"),
            ]
        )
    )
    assert result.evaluated_series_count == 0
    assert result.incomplete_series_count == 2


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        (observation("A", "2026-04-01T12:00:00", 1, "id"), "timezone-aware"),
        (observation("A", "2026-04-01T12:00:00Z", -1, "id"), "greater than"),
        (observation("A", "2026-04-01T12:00:00Z", float("nan"), "id"), "greater than"),
        (observation("A", "2026-04-01T12:00:00Z", float("inf"), "id"), "finite"),
    ],
)
def test_bad_observations_rejected(bad: dict[str, object], message: str) -> None:
    with pytest.raises(SchemaValidationError, match=message):
        LongitudinalAnalysisRequest(
            observations=[bad, observation("B", "2026-04-02T12:00:00Z", 2, "other")]
        )


def test_mixed_units_rejected_not_silently_converted() -> None:
    request = LongitudinalAnalysisRequest(
        observations=[
            observation("A", "2026-04-01T12:00:00Z", 3, "x", unit="mm"),
            observation("A", "2026-04-02T12:00:00Z", 3, "y", unit="cm"),
        ]
    )
    with pytest.raises(ValidationError, match="mix units"):
        analyze_longitudinal(request)


def test_duplicate_source_and_timestamps_rejected() -> None:
    duplicate_source = LongitudinalAnalysisRequest(
        observations=[
            observation("A", "2026-04-01T12:00:00Z", 2, "same"),
            observation("B", "2026-04-02T12:00:00Z", 3, "same"),
        ]
    )
    with pytest.raises(ValidationError, match="source_record_id"):
        analyze_longitudinal(duplicate_source)
    same_time = LongitudinalAnalysisRequest(
        observations=[
            observation("A", "2026-04-01T12:00:00Z", 2, "a"),
            observation("A", "2026-04-01T07:00:00-05:00", 3, "b"),
        ]
    )
    with pytest.raises(ValidationError, match="simultaneous"):
        analyze_longitudinal(same_time)


def test_midpoint_does_not_change_endpoints() -> None:
    request = LongitudinalAnalysisRequest(
        observations=[
            observation("A", "2026-01-01T00:00:00Z", 10, "t1"),
            observation("A", "2026-01-02T00:00:00Z", 40, "t2"),
            observation("A", "2026-01-03T00:00:00Z", 12, "t3"),
        ]
    )
    item = analyze_longitudinal(request).changes[0]
    assert item.observation_count == 3
    assert item.absolute_change == 2
    assert item.elapsed_days == 2
    assert item.change_per_day == 1


def test_api_reports_unverified_evidence(client: TestClient) -> None:
    observations = [
        observation("A", "2026-04-01T00:00:00Z", 3, "first"),
        observation("A", "2026-04-02T00:00:00Z", 5, "second"),
    ]
    response = client.post(
        "/api/v1/ecology/longitudinal-analysis",
        json={"observations": observations},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["evidence_level"] == "caller_supplied_unverified"
    assert payload["changes"][0]["absolute_change"] == 2
