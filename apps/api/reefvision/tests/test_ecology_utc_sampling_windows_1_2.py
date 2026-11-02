"""UTC sampling-date alignment for independent ecological experimental units."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from reefvision.domain.longitudinal_monitoring import analyze_longitudinal
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.longitudinal_monitoring import (
    LongitudinalAnalysisRequest,
    LongitudinalAnalysisResponse,
    LongitudinalChange,
)
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_workflow_ecology_1_2 import _graph


def _obs(organism: str, source: str, observed_at: str, value: float) -> dict[str, object]:
    return {
        "organism_id": organism,
        "metric_name": "polyp_count",
        "source_record_id": source,
        "observed_at": observed_at,
        "value": value,
        "unit": "count",
        "experimental_unit_id": "tank-A",
        "experimental_unit_type": "tank",
    }


def _same_date_observations() -> list[dict[str, object]]:
    return [
        _obs("frag-A", "a-first", "2026-04-01T08:00:00Z", 10),
        _obs("frag-A", "a-last", "2026-04-03T11:00:00Z", 12),
        _obs("frag-B", "b-first", "2026-04-01T16:00:00Z", 20),
        _obs("frag-B", "b-last", "2026-04-03T18:00:00Z", 24),
    ]


class _SeasonalOffset(tzinfo):
    """Portable DST-like offsets without a host timezone database."""

    def utcoffset(self, dt: datetime | None) -> timedelta:
        if dt is None:
            return timedelta(hours=-5)
        return timedelta(hours=-4 if (3, 8) <= (dt.month, dt.day) < (11, 1) else -5)

    def dst(self, dt: datetime | None) -> timedelta:
        return timedelta(0)

    def tzname(self, dt: datetime | None) -> str:
        return "seasonal-offset"


@pytest.mark.parametrize(
    ("start_date", "end_date", "expected_hours"),
    [
        ((3, 7), (3, 9), 47),
        ((10, 31), (11, 2), 49),
    ],
)
def test_saved_organism_endpoint_replays_actual_utc_elapsed_hours(
    start_date: tuple[int, int],
    end_date: tuple[int, int],
    expected_hours: int,
) -> None:
    """One shared tzinfo object must not hide spring/fall offset changes."""
    seasonal = _SeasonalOffset()
    start = datetime(2026, *start_date, 12, tzinfo=seasonal)
    end = datetime(2026, *end_date, 12, tzinfo=seasonal)
    assert (end - start).total_seconds() == 48 * 3600
    assert (end.astimezone(UTC) - start.astimezone(UTC)).total_seconds() == (expected_hours * 3600)
    payload = {
        "organism_id": "fragment-A",
        "metric_name": "polyp_count",
        "unit": "count",
        "first_observed_at": start,
        "last_observed_at": end,
        "baseline_source_record_id": "human-start",
        "final_source_record_id": "human-end",
        "initial_value": 10,
        "final_value": 12,
        "absolute_change": 2,
        "percent_change": 20,
        "elapsed_days": expected_hours / 24,
        "change_per_day": 2 / (expected_hours / 24),
        "observation_count": 2,
    }
    parsed = LongitudinalChange.model_validate(payload)
    assert parsed.elapsed_days == pytest.approx(expected_hours / 24)
    # A forged 48-hour wall-clock denominator must fail on both transitions.
    with pytest.raises(PydanticValidationError, match="endpoint arithmetic does not reconcile"):
        LongitudinalChange.model_validate({**payload, "elapsed_days": 2.0, "change_per_day": 1.0})


def _offset_transition_observations() -> list[dict[str, object]]:
    return [
        _obs("frag-A", "a-first", "2026-03-07T12:00:00-05:00", 10),
        _obs("frag-A", "a-last", "2026-03-09T12:00:00-04:00", 12),
        _obs("frag-B", "b-first", "2026-03-07T12:00:00-05:00", 20),
        _obs("frag-B", "b-last", "2026-03-09T12:00:00-04:00", 24),
    ]



def test_population_replay_groups_equivalent_offset_endpoints_by_utc_date() -> None:
    """An offset-rendered date must not create a different biological stratum."""
    result = analyze_longitudinal(
        LongitudinalAnalysisRequest(observations=_same_date_observations())
    )
    payload = result.model_dump(mode="json")
    assert payload["population_summaries"][0]["baseline_date"] == "2026-04-01"
    baseline = datetime.fromisoformat(payload["unit_summaries"][0]["baseline_at"])
    offset_baseline = baseline.astimezone(timezone(timedelta(hours=-10)))
    assert offset_baseline.date().isoformat() == "2026-03-31"
    payload["unit_summaries"][0]["baseline_at"] = offset_baseline.isoformat()

    # An equivalent offset rendering is valid with the unchanged UTC date.
    parsed = LongitudinalAnalysisResponse.model_validate(payload)
    assert parsed.population_summaries[0].baseline_date.isoformat() == "2026-04-01"

    # Changing both the rendered timestamp and the population stratum must
    # not allow a tank to move into a different UTC sampling-date cohort.
    forged = deepcopy(payload)
    forged["population_summaries"][0]["baseline_date"] = "2026-03-31"
    with pytest.raises(PydanticValidationError, match="Population summary strata do not reconcile"):
        LongitudinalAnalysisResponse.model_validate(forged)

    # A naive saved unit timestamp must never acquire the host timezone.
    naive = deepcopy(payload)
    naive["unit_summaries"][0]["baseline_at"] = "2026-04-01T08:00:00"
    with pytest.raises(
        PydanticValidationError, match="Population summary unit endpoints must be timezone-aware"
    ):
        LongitudinalAnalysisResponse.model_validate(naive)


def test_same_utc_dates_different_hours_are_eligible() -> None:
    result = analyze_longitudinal(
        LongitudinalAnalysisRequest(observations=_same_date_observations())
    )
    assert result.evaluated_series_count == 2
    assert result.independent_unit_count == 1
    assert result.excluded_units == []
    assert result.unit_coverage[0].eligible_for_summary is True
    assert result.unit_summaries[0].organism_count == 2
    assert result.unit_summaries[0].mean_absolute_change == 3
    assert result.unit_summaries[0].baseline_at.isoformat() == ("2026-04-01T08:00:00+00:00")
    assert result.unit_summaries[0].final_at.isoformat() == ("2026-04-03T18:00:00+00:00")
    assert result.population_summaries[0].independent_unit_count == 1
    assert result.analysis_provenance.algorithm_version.startswith("ecology-longitudinal-")
    assert result.evidence_level == "caller_supplied_unverified"


def test_timezone_offsets_are_normalized_before_window_comparison() -> None:
    observations = _same_date_observations()
    observations[2]["observed_at"] = "2026-03-31T23:30:00-04:00"
    observations[3]["observed_at"] = "2026-04-03T14:00:00-04:00"
    result = analyze_longitudinal(LongitudinalAnalysisRequest(observations=observations))
    assert len(result.unit_summaries) == 1
    assert result.unit_summaries[0].baseline_at.isoformat() == ("2026-04-01T03:30:00+00:00")
    assert result.unit_summaries[0].final_at.isoformat() == ("2026-04-03T18:00:00+00:00")


def test_different_utc_sampling_dates_still_exclude_unit() -> None:
    observations = _same_date_observations()
    observations[2]["observed_at"] = "2026-04-02T08:00:00Z"
    result = analyze_longitudinal(LongitudinalAnalysisRequest(observations=observations))
    assert result.unit_summaries == []
    assert result.population_summaries == []
    assert result.excluded_units[0].reason == "nonmatching_sampling_window"
    assert result.unit_coverage[0].eligible_for_summary is False


@pytest.mark.parametrize("crosses_offset_transition", [False, True])
def test_standalone_and_saved_workflow_agree_on_date_window(
    client: TestClient, crosses_offset_transition: bool
) -> None:
    observations = (
        _offset_transition_observations()
        if crosses_offset_transition
        else _same_date_observations()
    )
    standalone = client.post(
        "/api/v1/ecology/longitudinal-analysis",
        json={"observations": observations},
    )
    assert standalone.status_code == 200, standalone.text
    assert standalone.json()["unit_summaries"][0]["organism_count"] == 2
    if crosses_offset_transition:
        assert all(
            row["elapsed_days"] == pytest.approx(47 / 24) for row in standalone.json()["changes"]
        )

    project = create_project(client, "UTC-date ecological sampling")
    project_id = str(project["id"])
    graph = _graph(observations)
    plan = client.post(f"/api/v1/projects/{project_id}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": graph, "create_new_revision": True},
    )
    assert saved.status_code == 201, saved.text
    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    assert queued.status_code == 202, queued.text
    app = cast(FastAPI, client.app)
    assert (
        process_workflow_run_job(
            app.state.settings,
            app.state.session_factory,
            str(queued.json()["job_id"]),
        )
        is True
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifacts = [
        item for item in detail.json()["artifacts"] if item["data_type"] == "longitudinal_analysis"
    ]
    assert len(artifacts) == 1
    payload = artifacts[0]["payload_json"]
    assert payload["changes"] == standalone.json()["changes"]
    assert payload["unit_summaries"] == standalone.json()["unit_summaries"]
    assert payload["unit_coverage"] == standalone.json()["unit_coverage"]
    assert payload["analysis_provenance"] == standalone.json()["analysis_provenance"]
    assert payload["evidence_level"] == "caller_supplied_unverified"
    if not crosses_offset_transition:
        # Re-validate the *executed and persisted* typed Workflow Builder output.
        offset_payload = deepcopy(payload)
        offset_payload["unit_summaries"][0]["baseline_at"] = "2026-03-31T22:00:00-10:00"
        assert (
            LongitudinalAnalysisResponse.model_validate(offset_payload).evidence_level
            == "caller_supplied_unverified"
        )
        forged = deepcopy(offset_payload)
        forged["population_summaries"][0]["baseline_date"] = "2026-03-31"
        with pytest.raises(
            PydanticValidationError, match="Population summary strata do not reconcile"
        ):
            LongitudinalAnalysisResponse.model_validate(forged)
