"""Environmental analyses round-trip with rebuilt hashes and isolated identifiers."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_environmental_analysis_temporal import _records
from reefvision.tests.test_scientific_data import observation
from reefvision.tests.test_scientific_project_exchange import (
    database_counts,
    export_archive,
    import_archive,
    rewrite,
)
from reefvision.tests.test_workflow_environmental_analysis import _execute, lunar_graph


def _source(client: TestClient, *, retain: bool = False) -> tuple[dict, list[dict], list[dict]]:
    project = create_project(client, "Portable environmental analyses")
    records = _records(
        client,
        project["id"],
        [
            observation(
                variable="coral_count",
                value=4,
                unit="count",
                observed_at="2026-04-03T13:00:00Z",
            ),
            observation(value=68, unit="degF", observed_at="2026-04-03T12:55:00Z"),
            observation(value=70, unit="degF", observed_at="2026-04-03T13:05:00Z"),
        ],
    )
    base = f"/api/v1/projects/{project['id']}/environment/analyses"
    lunar = client.post(
        f"{base}/lunar-context",
        json={"name": "Portable lunar", "observed_at": ["2024-04-08T18:21:00Z"]},
    )
    assert lunar.status_code == 201, lunar.text
    join = client.post(
        f"{base}/observation-environment-join",
        json={
            "name": "Portable join",
            "observation_record_ids": [records[0]["id"]],
            "environmental_variable": "water_temperature",
            "max_time_delta_s": 30 if retain else 600,
            "max_distance_m": 1000,
            "require_depth_match": False,
            **(
                {
                    "unmatched_policy": "retain",
                    "study_assignments": [
                        {
                            "observation_record_id": records[0]["id"],
                            "subject_id": "fragment-a",
                            "experimental_unit_id": project["id"],
                            "experimental_unit_kind": "tank",
                            "treatment": "control",
                            "timepoint": "baseline",
                        }
                    ],
                }
                if retain
                else {}
            ),
        },
    )
    assert join.status_code == 201, join.text
    lag = client.post(
        f"{base}/lagged-comparison",
        json={
            "name": "Portable lag",
            "join_result_id": join.json()["result"]["id"],
            "lags_s": [-300, 300],
        },
    )
    assert lag.status_code == 201, lag.text
    definitions = [
        lunar.json()["definition"],
        join.json()["definition"],
        lag.json()["definition"],
    ]
    results = [lunar.json()["results"][0], join.json()["result"], lag.json()["result"]]
    return project, definitions, results


@pytest.mark.parametrize("retain", [False, True])
def test_environmental_analysis_round_trip_remaps_links_and_rebuilds_hashes(
    client: TestClient, test_settings, retain: bool
) -> None:
    project, source_definitions, source_results = _source(client, retain=retain)
    raw = export_archive(client, test_settings, project["id"])
    inspection = client.post(
        "/api/v1/exchange-packages/inspect", files={"file": ("analysis.zip", raw)}
    )
    assert inspection.status_code == 200, inspection.text
    assert inspection.json()["section_counts"]["environmental_analysis_definitions"] == 3
    assert inspection.json()["section_counts"]["environmental_analysis_results"] == 3

    imported = import_archive(client, raw)
    assert imported.status_code == 201, imported.text
    imported_project_id = imported.json()["project_id"]
    assert imported_project_id != project["id"]
    assert imported.json()["imported_counts"]["environmental_analysis_definitions"] == 3
    assert imported.json()["imported_counts"]["environmental_analysis_results"] == 3
    base = f"/api/v1/projects/{imported_project_id}/environment/analyses"
    definitions = client.get(f"{base}/definitions").json()["items"]
    results = client.get(f"{base}/results").json()["items"]
    assert len(definitions) == len(results) == 3
    definition_by_kind = {item["analysis_kind"]: item for item in definitions}
    result_by_kind = {item["analysis_kind"]: item for item in results}
    source_definition_ids = {item["id"] for item in source_definitions}
    source_result_ids = {item["id"] for item in source_results}
    assert source_definition_ids.isdisjoint(item["id"] for item in definitions)
    assert source_result_ids.isdisjoint(item["id"] for item in results)

    lunar = result_by_kind["lunar_context"]
    assert lunar["payload"]["project_id"] == imported_project_id
    assert lunar["payload"]["phase"] == "new_moon"
    join = result_by_kind["observation_environment_join"]
    assert join["definition_id"] == definition_by_kind["observation_environment_join"]["id"]
    assert all(
        source_id not in {record["id"] for record in _source_records(source_results)}
        for source_id in join["source_record_ids"]
    )
    lag = result_by_kind["lagged_comparison"]
    assert lag["source_analysis_result_ids"] == [join["id"]]
    assert lag["input_snapshot"]["join_result_sha256"] == join["content_sha256"]
    if retain:
        pair = join["payload"]["unmatched"][0]
        assert pair["study_assignment"]["observation_record_id"] == pair["observation_record_id"]
        assert pair["study_assignment"]["experimental_unit_id"] == project["id"]
        assert lag["payload"]["experimental_unit_reuse_counts"] == {project["id"]: 2}
        assert lag["payload"]["sampling_effort"] == {"requested": 2, "matched": 2, "unmatched": 0}
    assert definition_by_kind["lagged_comparison"]["configuration"]["join_result_id"] == join["id"]
    for result in results:
        opened = client.get(f"{base}/results/{result['id']}")
        assert opened.status_code == 200, opened.text
        assert opened.json()["content_sha256"] == result["content_sha256"]


def _source_records(results: list[dict]) -> list[dict[str, str]]:
    return [{"id": identifier} for result in results for identifier in result["source_record_ids"]]


def test_workflow_analysis_lineage_is_remapped_and_current_after_import(
    client: TestClient, test_settings
) -> None:
    project = create_project(client, "Portable workflow analysis")
    source_run, artifact = _execute(client, project["id"], lunar_graph())
    source_result_id = artifact["payload_json"]["result_id"]
    raw = export_archive(client, test_settings, project["id"])

    imported = import_archive(client, raw)
    assert imported.status_code == 201, imported.text
    project_id = imported.json()["project_id"]
    base = f"/api/v1/projects/{project_id}/environment/analyses"
    results = client.get(f"{base}/results").json()["items"]
    result = next(item for item in results if item["analysis_kind"] == "lunar_context")
    assert result["id"] != source_result_id
    assert result["workflow_run_id"] != source_run["id"]
    assert result["workflow_node_run_id"]
    imported_run = client.get(f"/api/v1/workflow-runs/{result['workflow_run_id']}")
    assert imported_run.status_code == 200, imported_run.text
    assert imported_run.json()["run"]["project_id"] == project_id
    restored_artifact = next(
        row
        for row in imported_run.json()["artifacts"]
        if row["data_type"] == "environmental_analysis_result"
    )["payload_json"]
    assert restored_artifact["content_sha256"] == result["content_sha256"]
    assert restored_artifact["payload"] == result["payload"]
    validation = client.get(f"{base}/results/{result['id']}/validation")
    assert validation.status_code == 200, validation.text
    assert validation.json()["current"] is True


@pytest.mark.parametrize("damage", ["hash", "missing_source"])
def test_corrupt_environmental_analysis_import_is_atomic(
    client: TestClient, test_settings, damage: str
) -> None:
    project, _, _ = _source(client)
    raw = export_archive(client, test_settings, project["id"])

    def change(_manifest, sections):
        result = next(
            row
            for row in sections["environmental_analysis_results"]
            if row["analysis_kind"] == "observation_environment_join"
        )
        if damage == "hash":
            result["payload_json"]["interpretation"] = "causal"
        else:
            result["source_record_ids_json"] = ["00000000-0000-0000-0000-000000000000"]

    before = database_counts(client)
    imported = import_archive(client, rewrite(raw, change))
    assert imported.status_code == 400, imported.text
    assert database_counts(client) == before
