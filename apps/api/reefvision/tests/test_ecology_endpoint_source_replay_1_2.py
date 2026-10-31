"""A rehashed saved ecological endpoint cannot invent source-linked growth evidence."""

from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from reefvision.schemas.ecology_measurement_candidates import (
    EcologyMeasurementCandidatesResponse,
    EcologyProjectedEndpointChange,
)
from reefvision.tests.test_ecology_image_evidence_1_2 import _workflow
from reefvision.tests.test_ecology_projected_series_csv_1_2 import (
    _dated_artifact,
    _resign_derived_evidence,
)
from reefvision.tests.test_ecology_projected_visit_coverage_1_2 import _source


def test_current_api_and_executed_workflow_replay_unverified_source(
    client: TestClient,
) -> None:
    project_id, _ = _source(client)
    api = client.get(
        f"/api/v1/projects/{project_id}/ecology/calibrated-measurement-candidates"
    )
    assert api.status_code == 200, api.text
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    artifacts = [
        item
        for item in workflow["artifacts"]
        if item["data_type"] == "ecology_measurement_candidates"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == api.json()
    for payload in (api.json(), artifacts[0]["payload_json"]):
        checked = EcologyMeasurementCandidatesResponse.model_validate(payload)
        assert checked.review_gate == "scientist_review_required"
        assert checked.evidence_level == "linked_unverified"


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("baseline_image_id", "fabricated-image"),
        ("final_annotation_evidence_id", "fabricated-annotation"),
        ("final_calibration_evidence_id", "fabricated-calibration"),
        ("identity_revision", 999),
        ("experimental_unit_id", "fabricated-tank"),
        ("observed_timepoint_count", 3),
    ],
)
def test_rehashed_current_endpoint_rejects_unlinked_evidence(
    client: TestClient, field: str, replacement: str | int
) -> None:
    original = _dated_artifact(client)
    assert EcologyMeasurementCandidatesResponse.model_validate(
        original.model_dump(mode="json")
    ).projected_endpoint_changes
    endpoint = original.projected_endpoint_changes[0].model_copy(
        update={field: replacement}
    )
    # The endpoint remains arithmetically valid and the source/report digests
    # are both recomputed; only independent source-row linkage can reject it.
    assert EcologyProjectedEndpointChange.model_validate(
        endpoint.model_dump(mode="json")
    )
    forged = _resign_derived_evidence(
        original.model_copy(update={"projected_endpoint_changes": [endpoint]})
    )
    with pytest.raises(PydanticValidationError, match="Current projected endpoint"):
        EcologyMeasurementCandidatesResponse.model_validate(
            forged.model_dump(mode="json")
        )


def test_rehashed_endpoint_rejects_fabricated_but_consistent_growth(
    client: TestClient,
) -> None:
    original = _dated_artifact(client)
    endpoint = original.projected_endpoint_changes[0]
    changed_final = endpoint.final_value + 1
    delta = changed_final - endpoint.baseline_value
    percent = 100 * delta / endpoint.baseline_value
    forged_endpoint = endpoint.model_copy(
        update={
            "final_value": changed_final,
            "absolute_change": delta,
            "percent_change": percent,
            "projected_absolute_change_per_day": delta / endpoint.elapsed_days,
            "projected_baseline_percent_change_per_day": percent / endpoint.elapsed_days,
        }
    )
    EcologyProjectedEndpointChange.model_validate(
        forged_endpoint.model_dump(mode="json")
    )
    forged = _resign_derived_evidence(
        original.model_copy(update={"projected_endpoint_changes": [forged_endpoint]})
    )
    with pytest.raises(
        PydanticValidationError, match="does not match source candidates"
    ):
        EcologyMeasurementCandidatesResponse.model_validate(
            forged.model_dump(mode="json")
        )


def test_rehashed_duplicate_endpoint_is_not_an_extra_replicate(
    client: TestClient,
) -> None:
    original = _dated_artifact(client)
    endpoint = original.projected_endpoint_changes[0]
    forged = _resign_derived_evidence(
        original.model_copy(update={"projected_endpoint_changes": [endpoint, endpoint]})
    )
    with pytest.raises(
        PydanticValidationError, match="lacks a valid source date series"
    ):
        EcologyMeasurementCandidatesResponse.model_validate(
            forged.model_dump(mode="json")
        )


def test_historical_endpoint_contract_remains_readable(client: TestClient) -> None:
    original = _dated_artifact(client)
    legacy = deepcopy(original.model_dump(mode="json"))
    legacy["source_fingerprint_contract"] = "ecology-measurement-candidates-0020"
    parsed = EcologyMeasurementCandidatesResponse.model_validate(legacy)
    assert parsed.projected_endpoint_changes[0].review_gate == "scientist_review_required"
