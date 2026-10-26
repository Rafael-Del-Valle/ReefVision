"""Do not count a tank twice when its registered sampling level uses aliases."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from reefvision.domain.errors import ValidationError
from reefvision.schemas.ecology_measurement_candidates import EcologyProjectedUnitSummary
from reefvision.services.ecology_measurement_candidates import (
    summarize_projected_population_summaries,
)
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_ecology_image_evidence_1_2 import _workflow


def _unit(unit_type: str, organism: str, parent: str) -> EcologyProjectedUnitSummary:
    return EcologyProjectedUnitSummary(
        experimental_unit_type=unit_type,
        experimental_unit_id="tank-1",
        metric="box_width",
        units=["mm"],
        organism_keys=[organism],
        complete_organism_keys=[organism],
        incomplete_organism_keys=[],
        parent_colony_keys=[parent],
        sampling_windows_utc=["2026-04-03/2026-04-05"],
        unit_status="candidate",
        mean_absolute_change=2.0,
        mean_percent_change=20.0,
    )


@pytest.mark.parametrize("alias", ["aquarium", "aquaria", "tanks", "Tank-level"])
def test_population_rejects_aliases_of_one_independent_tank(alias: str) -> None:
    """An alias must not turn one physical tank into two statistical replicates."""
    rows = [_unit("tank", "fragment-A", "parent-A"), _unit(alias, "fragment-B", "parent-B")]
    with pytest.raises(ValidationError, match="Duplicate projected experimental-unit metric"):
        summarize_projected_population_summaries(rows)
    with pytest.raises(ValidationError, match="Duplicate projected experimental-unit metric"):
        summarize_projected_population_summaries(list(reversed(rows)))


def test_distinct_tanks_remain_distinct_declared_units() -> None:
    second = _unit("aquarium", "fragment-B", "parent-B").model_copy(
        update={"experimental_unit_id": "tank-2"}
    )
    summaries = summarize_projected_population_summaries(
        [_unit("tank", "fragment-A", "parent-A"), second]
    )
    # Different alias labels remain separate descriptive strata, with one
    # declared unit each; neither is verified as independent.
    assert sum(row.declared_unit_count for row in summaries) == 2
    assert all(row.independent_unit_inference_allowed is False for row in summaries)
    assert all(row.review_gate == "scientist_review_required" for row in summaries)


def test_registered_aliases_remain_reviewable_in_api_and_saved_workflow(
    client: TestClient,
) -> None:
    project = create_project(client, "Tank aliases are one biological sampling level")
    project_id = str(project["id"])
    url = f"/api/v1/projects/{project_id}/ecology/organisms"
    for parent in ("parent-A", "parent-B"):
        registered = client.post(
            url,
            json={
                "organism_key": parent,
                "kind": "colony",
                "reason": "Registered parent colony for sampling-design audit",
            },
        )
        assert registered.status_code == 201, registered.text
    for organism, parent, unit_type in (
        ("fragment-A", "parent-A", "tank"),
        ("fragment-B", "parent-B", "aquarium"),
    ):
        registered = client.post(
            url,
            json={
                "organism_key": organism,
                "kind": "fragment",
                "parent_colony_key": parent,
                "experimental_unit_type": unit_type,
                "experimental_unit_id": "tank-1",
                "reason": "Same physical tank recorded with a biological unit alias",
            },
        )
        assert registered.status_code == 201, registered.text
    registry = client.get(f"/api/v1/projects/{project_id}/ecology/identity-registry")
    assert registry.status_code == 200, registry.text
    assert registry.json()["review_gate"] == "scientist_review_required"
    assert {
        row["experimental_unit_type"]
        for row in registry.json()["identities"]
        if row["kind"] == "fragment"
    } == {"tank", "aquarium"}
    workflow = _workflow(client, project_id)
    assert workflow["run"]["status"] == "succeeded"
    registry_artifacts = [
        row for row in workflow["artifacts"] if row["data_type"] == "ecology_identity_registry"
    ]
    assert len(registry_artifacts) == 1
    assert registry_artifacts[0]["payload_json"] == registry.json()
    candidate_artifacts = [
        row
        for row in workflow["artifacts"]
        if row["data_type"] == "ecology_measurement_candidates"
    ]
    assert len(candidate_artifacts) == 1
    assert candidate_artifacts[0]["payload_json"]["projected_population_summaries"] == []
