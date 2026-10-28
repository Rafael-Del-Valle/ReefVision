"""Saved ecological workflows must preserve experimental-design QC warnings."""

from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from reefvision.schemas.ecology_identity import EcologyIdentityRegistryResponse
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_ecology_design_change_audit_1_2 import _register, _revise
from reefvision.tests.test_ecology_image_evidence_1_2 import _workflow


def _shared_parent_design(client: TestClient) -> tuple[str, dict]:
    project_id = str(create_project(client, "Signed ecological design warnings")["id"])
    _register(client, project_id, "parent-1", "colony")
    for key, unit in (("fragment-1", "tank-A"), ("fragment-2", "tank-B")):
        _register(
            client,
            project_id,
            key,
            "fragment",
            parent_colony_key="parent-1",
            experimental_unit_type="tank",
            experimental_unit_id=unit,
        )
    _revise(
        client,
        project_id,
        "fragment-1",
        1,
        kind="fragment",
        parent_colony_key="parent-1",
        experimental_unit_type="tank",
        experimental_unit_id="tank-C",
    )
    response = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert response.status_code == 200, response.text
    snapshot = response.json()
    assert snapshot["design_history_status"] == "design_changes_require_review"
    assert snapshot["design_change_count"] == 1
    assert snapshot["cross_unit_parent_audit_status"] == "shared_parent_requires_review"
    assert snapshot["historical_cross_unit_parent_audit_status"] == (
        "recorded_across_units_requires_review"
    )
    return project_id, snapshot


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("design_history_status", "no_design_changes_recorded", "design-change audit"),
        ("design_change_count", 0, "design-change audit"),
        ("design_change_events", [], "design-change audit"),
        (
            "cross_unit_parent_audit_status",
            "no_cross_unit_parent_reuse",
            "cross-unit parent audit",
        ),
        ("cross_unit_shared_parent_colony_keys", [], "cross-unit parent audit"),
        ("cross_unit_parent_details", [], "cross-unit parent audit"),
        (
            "historical_cross_unit_parent_audit_status",
            "no_recorded_cross_unit_parent_reuse",
            "historical parent audit",
        ),
        ("historical_cross_unit_parent_details", [], "historical parent audit"),
    ],
)
def test_signed_design_warnings_cannot_be_hidden_in_saved_workflow(
    client: TestClient, field: str, replacement: object, message: str
) -> None:
    project_id, snapshot = _shared_parent_design(client)
    run = _workflow(client, project_id)
    assert run["run"]["status"] == "succeeded"
    artifacts = [
        row for row in run["artifacts"] if row["data_type"] == "ecology_identity_registry"
    ]
    assert len(artifacts) == 1
    assert artifacts[0]["payload_json"] == snapshot
    assert EcologyIdentityRegistryResponse.model_validate(snapshot).review_gate == (
        "scientist_review_required"
    )
    changed = deepcopy(artifacts[0]["payload_json"])
    changed[field] = replacement
    with pytest.raises(ValidationError, match=message):
        EcologyIdentityRegistryResponse.model_validate(changed)


def test_legacy_audit_omissions_remain_unknown_not_falsely_clear(
    client: TestClient,
) -> None:
    _, snapshot = _shared_parent_design(client)
    legacy = deepcopy(snapshot)
    for key in (
        "design_history_status",
        "design_change_count",
        "design_change_events",
        "cross_unit_parent_audit_status",
        "cross_unit_shared_parent_colony_keys",
        "cross_unit_parent_details",
        "historical_cross_unit_parent_audit_status",
        "historical_cross_unit_parent_details",
    ):
        legacy.pop(key)
    typed = EcologyIdentityRegistryResponse.model_validate(legacy)
    assert typed.design_history_status == "history_unavailable"
    assert typed.cross_unit_parent_audit_status == "unavailable"
    assert typed.historical_cross_unit_parent_audit_status == "unavailable"
    assert typed.review_gate == "scientist_review_required"

    altered = deepcopy(legacy)
    altered["design_change_count"] = 1
    with pytest.raises(ValidationError, match="Unavailable ecological design audit"):
        EcologyIdentityRegistryResponse.model_validate(altered)

    altered = deepcopy(legacy)
    altered["cross_unit_shared_parent_colony_keys"] = ["parent-1"]
    with pytest.raises(ValidationError, match="Unavailable ecological parent audit"):
        EcologyIdentityRegistryResponse.model_validate(altered)

    altered = deepcopy(legacy)
    altered["historical_cross_unit_parent_details"] = snapshot[
        "historical_cross_unit_parent_details"
    ]
    with pytest.raises(
        ValidationError, match="Unavailable ecological historical parent audit"
    ):
        EcologyIdentityRegistryResponse.model_validate(altered)


def test_known_design_audit_requires_replayable_history(client: TestClient) -> None:
    _, snapshot = _shared_parent_design(client)
    altered = deepcopy(snapshot)
    for key in ("identity_history", "history_sha256", "history_revision_count"):
        altered.pop(key)
    with pytest.raises(ValidationError, match="design audit requires revision history"):
        EcologyIdentityRegistryResponse.model_validate(altered)
