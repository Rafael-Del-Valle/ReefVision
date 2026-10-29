"""1.2 scientific inputs must reject coerced counts and forged source claims."""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as SchemaValidationError

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.longitudinal_monitoring import LongitudinalAnalysisRequest
from reefvision.schemas.model_agreement import PairedCountComparisonRequest
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_workflow_ecology_1_2 import (
    _graph as longitudinal_graph,
)
from reefvision.tests.test_workflow_ecology_1_2 import (
    _observations as longitudinal_observations,
)
from reefvision.tests.test_workflow_model_agreement_1_2 import (
    _graph as paired_graph,
)
from reefvision.tests.test_workflow_model_agreement_1_2 import (
    _pairs as paired_observations,
)


@pytest.mark.parametrize("value", [True, False])
def test_longitudinal_rejects_boolean_measurement(client: TestClient, value: bool) -> None:
    observations = longitudinal_observations()
    observations[0]["value"] = value
    payload = {"observations": observations}
    with pytest.raises(SchemaValidationError, match="numeric, not Boolean"):
        LongitudinalAnalysisRequest.model_validate(payload)
    response = client.post("/api/v1/ecology/longitudinal-analysis", json=payload)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("field", ["reference_count", "model_count"])
@pytest.mark.parametrize("value", [True, False])
def test_paired_counts_reject_booleans(client: TestClient, field: str, value: bool) -> None:
    pairs = paired_observations()
    pairs[0][field] = value
    payload = {"pairs": pairs, "reference_kind": "human_consensus"}
    with pytest.raises(SchemaValidationError, match="numeric, not Boolean"):
        PairedCountComparisonRequest.model_validate(payload)
    response = client.post("/api/v1/ecology/paired-count-comparison", json=payload)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("value", ["10", "10.5", None, [], {}])
def test_longitudinal_rejects_coerced_measurements(client: TestClient, value: object) -> None:
    observations = longitudinal_observations()
    observations[0]["value"] = value
    payload = {"observations": observations}
    with pytest.raises(SchemaValidationError, match="JSON number"):
        LongitudinalAnalysisRequest.model_validate(payload)
    response = client.post("/api/v1/ecology/longitudinal-analysis", json=payload)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("field", ["reference_count", "model_count"])
@pytest.mark.parametrize("value", ["10", "10.5", None, [], {}])
def test_paired_counts_reject_coerced_measurements(
    client: TestClient, field: str, value: object
) -> None:
    pairs = paired_observations()
    pairs[0][field] = value
    payload = {"pairs": pairs, "reference_kind": "human_consensus"}
    with pytest.raises(SchemaValidationError, match="JSON numbers"):
        PairedCountComparisonRequest.model_validate(payload)
    response = client.post("/api/v1/ecology/paired-count-comparison", json=payload)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("field", ["reference_count", "model_count"])
@pytest.mark.parametrize("value", [0.5, 1.25, 10.01])
def test_paired_counts_reject_fractional_organisms(
    client: TestClient, field: str, value: float
) -> None:
    pairs = paired_observations()
    pairs[0][field] = value
    payload = {"pairs": pairs, "reference_kind": "human_consensus"}
    with pytest.raises(SchemaValidationError, match="whole numbers"):
        PairedCountComparisonRequest.model_validate(payload)
    response = client.post("/api/v1/ecology/paired-count-comparison", json=payload)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("field", ["reference_count", "model_count"])
def test_paired_counts_reject_unsafe_json_integer_precision(client: TestClient, field: str) -> None:
    """Reject integers that would silently round when parsed as floats."""
    pairs = paired_observations()
    pairs[0][field] = 2**53 + 1
    payload = {"pairs": pairs, "reference_kind": "human_consensus"}
    with pytest.raises(SchemaValidationError, match="safe-integer range"):
        PairedCountComparisonRequest.model_validate(payload)
    response = client.post("/api/v1/ecology/paired-count-comparison", json=payload)
    assert response.status_code == 422, response.text


def test_paired_counts_accept_largest_safe_json_integer(client: TestClient) -> None:
    pairs = paired_observations()
    pairs[0]["reference_count"] = 2**53 - 1
    pairs[0]["model_count"] = 2**53 - 1
    response = client.post(
        "/api/v1/ecology/paired-count-comparison",
        json={"pairs": pairs, "reference_kind": "human_consensus"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["paired_differences"][0]["reference_count"] == 2**53 - 1
    assert response.json()["paired_differences"][0]["signed_difference"] == 0


def test_paired_counts_accept_integral_json_floats(client: TestClient) -> None:
    pairs = paired_observations()
    pairs[0]["reference_count"] = 10.0
    pairs[0]["model_count"] = 12.0
    response = client.post(
        "/api/v1/ecology/paired-count-comparison",
        json={"pairs": pairs, "reference_kind": "human_consensus"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["evidence_level"] == "caller_supplied_unverified"
    assert response.json()["paired_differences"][0]["reference_count"] == 10.0


@pytest.mark.parametrize(
    ("level", "field", "value"),
    [
        ("observation", "verified", True),
        ("observation", "review_status", "approved"),
        ("observation", "calibration_verified", True),
        ("request", "evidence_level", "verified"),
    ],
)
def test_unknown_scientific_claims_fail_closed(
    client: TestClient, level: str, field: str, value: object
) -> None:
    payload: dict[str, Any] = {"observations": longitudinal_observations()}
    if level == "observation":
        payload["observations"][0][field] = value
    else:
        payload[field] = value
    with pytest.raises(SchemaValidationError, match="extra_forbidden"):
        LongitudinalAnalysisRequest.model_validate(payload)
    response = client.post("/api/v1/ecology/longitudinal-analysis", json=payload)
    assert response.status_code == 422, response.text


def test_valid_zero_remains_unverified(client: TestClient) -> None:
    observations = longitudinal_observations()
    observations[0]["value"] = 0
    response = client.post(
        "/api/v1/ecology/longitudinal-analysis",
        json={"observations": observations},
    )
    assert response.status_code == 200, response.text
    assert response.json()["evidence_level"] == "caller_supplied_unverified"
    pairs = paired_observations()
    pairs[0]["reference_count"] = 0
    parsed = PairedCountComparisonRequest.model_validate(
        {"pairs": pairs, "reference_kind": "human_consensus"}
    )
    assert parsed.pairs[0].reference_count == 0.0


@pytest.mark.parametrize(
    "kind",
    [
        "longitudinal",
        "paired",
        "source_claim",
        "longitudinal_string",
        "paired_string",
        "paired_fractional",
        "paired_unsafe_integer",
    ],
)
def test_saved_workflow_rejects_invalid_scientific_input(client: TestClient, kind: str) -> None:
    project = create_project(client, f"Strict ecological input {kind}")
    project_id = str(project["id"])
    if kind in {"longitudinal", "source_claim", "longitudinal_string"}:
        graph = cast(dict[str, Any], longitudinal_graph(longitudinal_observations()))
        rows = graph["nodes"][1]["parameters"]["observations"]
        if kind == "longitudinal":
            rows[0]["value"] = True
        elif kind == "longitudinal_string":
            rows[0]["value"] = "12"
        else:
            rows[0]["verified"] = True
        forbidden_artifact = "longitudinal_analysis"
    else:
        graph = cast(dict[str, Any], paired_graph())
        invalid_count: object = True
        if kind == "paired_string":
            invalid_count = "12"
        elif kind == "paired_fractional":
            invalid_count = 12.5
        elif kind == "paired_unsafe_integer":
            invalid_count = 2**53 + 1
        graph["nodes"][1]["parameters"]["pairs"][0]["model_count"] = invalid_count
        forbidden_artifact = "paired_count_comparison"

    saved = client.post(
        f"/api/v1/projects/{project_id}/workflow-graphs",
        json={"graph": graph, "create_new_revision": True},
    )
    if saved.status_code != 201:
        assert saved.status_code in {400, 422}, saved.text
        return
    queued = client.post(
        f"/api/v1/projects/{project_id}/workflow-runs",
        json={"graph_record_id": saved.json()["id"]},
    )
    if queued.status_code != 202:
        assert queued.status_code in {400, 409, 422}, queued.text
        return
    app = cast(FastAPI, client.app)
    assert (
        process_workflow_run_job(
            app.state.settings,
            app.state.session_factory,
            str(queued.json()["job_id"]),
        )
        is False
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "failed"
    assert not any(
        artifact["data_type"] == forbidden_artifact for artifact in detail.json()["artifacts"]
    )
