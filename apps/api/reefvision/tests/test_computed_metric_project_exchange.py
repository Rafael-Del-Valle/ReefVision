"""Computed scientific outputs must remain reproducible after project exchange."""

from copy import deepcopy
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.scientific_data import content_hash
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_computed_metrics import (
    add_records,
    create_density_definition,
    scientific_record,
)
from reefvision.tests.test_scientific_project_exchange import (
    database_counts,
    export_archive,
    import_archive,
    rewrite,
)
from reefvision.tests.test_workflow_computed_metrics import (
    metric_graph,
    save_and_queue,
)
from reefvision.tests.test_workflow_environmental_threshold import threshold_query


def _source_project(client: TestClient) -> tuple[dict, list[dict], dict, dict, dict]:
    project = create_project(client, "Portable computed science")
    literal_source_id = project["id"]
    organisms, area = add_records(
        client,
        project["id"],
        [
            scientific_record(
                "organism_count",
                20,
                "count",
                uncertainty={"value": 2, "kind": "standard_deviation"},
                provenance={
                    "source": "Reef survey",
                    "dataset_id": literal_source_id,
                    "acquired_at": "2026-04-03T13:05:00Z",
                },
            ),
            scientific_record(
                "surveyed_area",
                100,
                "cm2",
                uncertainty={"value": 5, "kind": "standard_deviation"},
                provenance={
                    "source": "Reef survey",
                    "dataset_id": literal_source_id,
                    "acquired_at": "2026-04-03T13:05:00Z",
                },
            ),
        ],
    )
    definition = create_density_definition(client, project["id"])
    run = save_and_queue(
        client,
        project["id"],
        metric_graph(definition["id"], organisms["id"], area["id"]),
    )
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run["job_id"])
    )
    result_page = client.get(f"/api/v1/projects/{project['id']}/computed-metric-results")
    assert result_page.status_code == 200, result_page.text
    result = result_page.json()["items"][0]
    event = client.post(
        f"/api/v1/projects/{project['id']}/environment/events/definitions",
        json={"name": "Warm water", "query": threshold_query()},
    )
    assert event.status_code == 201, event.text
    return project, [organisms, area], definition, result, event.json()


def test_computed_results_and_event_definitions_round_trip_with_reproducible_inputs(
    client: TestClient, test_settings
) -> None:
    project, source_records, source_definition, source_result, source_event = _source_project(
        client
    )
    raw = export_archive(client, test_settings, project["id"])

    inspection = client.post(
        "/api/v1/exchange-packages/inspect", files={"file": ("computed.zip", raw)}
    )
    assert inspection.status_code == 200, inspection.text
    assert inspection.json()["format_version"] == "1.1"
    assert inspection.json()["section_counts"]["computed_metric_definitions"] == 1
    assert inspection.json()["section_counts"]["computed_metric_results"] == 1
    assert inspection.json()["section_counts"]["environmental_event_definitions"] == 1

    imported = import_archive(client, raw)
    assert imported.status_code == 201, imported.text
    imported_project_id = imported.json()["project_id"]
    assert imported_project_id != project["id"]
    assert imported.json()["imported_counts"]["computed_metric_definitions"] == 1
    assert imported.json()["imported_counts"]["computed_metric_results"] == 1
    assert imported.json()["imported_counts"]["environmental_event_definitions"] == 1

    definitions = client.get(
        f"/api/v1/projects/{imported_project_id}/computed-metric-definitions"
    ).json()["items"]
    results = client.get(f"/api/v1/projects/{imported_project_id}/computed-metric-results").json()[
        "items"
    ]
    events = client.get(
        f"/api/v1/projects/{imported_project_id}/environment/events/definitions"
    ).json()["items"]
    assert len(definitions) == len(results) == len(events) == 1
    restored_definition, restored_result, restored_event = definitions[0], results[0], events[0]
    assert restored_definition["id"] != source_definition["id"]
    assert restored_definition["definition_sha256"] == source_definition["definition_sha256"]
    assert restored_result["id"] != source_result["id"]
    assert restored_result["value"] == pytest.approx(source_result["value"])
    assert restored_result["unit"] == source_result["unit"]
    assert restored_result["definition_id"] == restored_definition["id"]
    assert restored_result["workflow_run_id"] not in (None, source_result["workflow_run_id"])
    assert restored_result["workflow_node_run_id"] not in (
        None,
        source_result["workflow_node_run_id"],
    )
    assert set(restored_result["input_record_ids"].values()).isdisjoint(
        {item["id"] for item in source_records}
    )
    # Dataset IDs are literal source provenance, not project-scoped foreign keys.
    assert (
        restored_result["input_snapshot"]["organisms"]["provenance"]["dataset_id"]
        == (project["id"])
    )
    assert restored_event["id"] != source_event["id"]
    assert restored_event["definition_sha256"] == source_event["definition_sha256"]

    recalculated = client.post(
        f"/api/v1/projects/{imported_project_id}/computed-metric-definitions/"
        f"{restored_definition['id']}/calculate",
        json={"inputs": restored_result["input_record_ids"]},
    )
    assert recalculated.status_code == 201, recalculated.text
    assert recalculated.json()["value"] == pytest.approx(source_result["value"])
    assert recalculated.json()["uncertainty"] == pytest.approx(source_result["uncertainty"])
    evaluated = client.post(
        f"/api/v1/projects/{imported_project_id}/environment/events/definitions/"
        f"{restored_event['id']}/evaluate"
    )
    assert evaluated.status_code == 200, evaluated.text
    assert evaluated.json()["definition_sha256"] == source_event["definition_sha256"]


@pytest.mark.parametrize("record_kind", ["computed definition", "event definition"])
def test_standalone_scientific_definitions_select_enriched_exchange_and_survive_import(
    client: TestClient, test_settings, record_kind: str
) -> None:
    project = create_project(client, f"Portable {record_kind}")
    if record_kind == "computed definition":
        source = create_density_definition(client, project["id"])
        section = "computed_metric_definitions"
        endpoint = "computed-metric-definitions"
    else:
        response = client.post(
            f"/api/v1/projects/{project['id']}/environment/events/definitions",
            json={"name": "Warm water", "query": threshold_query()},
        )
        assert response.status_code == 201, response.text
        source = response.json()
        section = "environmental_event_definitions"
        endpoint = "environment/events/definitions"

    raw = export_archive(client, test_settings, project["id"])
    inspection = client.post(
        "/api/v1/exchange-packages/inspect", files={"file": ("standalone.zip", raw)}
    )
    assert inspection.status_code == 200, inspection.text
    assert inspection.json()["format_version"] == "1.1"
    assert inspection.json()["section_counts"][section] == 1

    imported = import_archive(client, raw)
    assert imported.status_code == 201, imported.text
    restored = client.get(f"/api/v1/projects/{imported.json()['project_id']}/{endpoint}").json()[
        "items"
    ]
    assert len(restored) == 1
    assert restored[0]["id"] != source["id"]
    assert restored[0]["definition_sha256"] == source["definition_sha256"]


@pytest.mark.parametrize(
    "corruption",
    [
        "definition_hash",
        "result_hash",
        "missing_input",
        "mismatched_snapshot",
        "mismatched_subject",
        "mismatched_definition_provenance",
        "mismatched_category_provenance",
        "mismatched_workflow_run",
        "foreign_project",
        "unsupported_formula",
    ],
)
def test_computed_exchange_rejects_invalid_inventory_atomically(
    client: TestClient, test_settings, corruption: str
) -> None:
    project, _, _, _, _ = _source_project(client)
    raw = export_archive(client, test_settings, project["id"])

    def change(_manifest, sections):
        definition = sections["computed_metric_definitions"][0]
        result = sections["computed_metric_results"][0]
        if corruption == "definition_hash":
            definition["definition_sha256"] = "0" * 64
        elif corruption == "result_hash":
            result["payload_json"]["value"] = 999
        elif corruption == "missing_input":
            result["payload_json"]["input_record_ids"]["organisms"] = "missing"
            result["content_sha256"] = content_hash(result["payload_json"])
        elif corruption == "mismatched_snapshot":
            snapshot = result["payload_json"]["input_snapshot"]["organisms"]
            snapshot["value"] = 999
            result["content_sha256"] = content_hash(result["payload_json"])
        elif corruption == "mismatched_subject":
            result["payload_json"]["subject"] = {"frame_index": 99}
            result["content_sha256"] = content_hash(result["payload_json"])
        elif corruption == "mismatched_definition_provenance":
            result["payload_json"]["provenance"]["definition_sha256"] = "0" * 64
            result["content_sha256"] = content_hash(result["payload_json"])
        elif corruption == "mismatched_category_provenance":
            result["payload_json"]["provenance"]["source_categories"] = ["model_prediction"]
            result["content_sha256"] = content_hash(result["payload_json"])
        elif corruption == "mismatched_workflow_run":
            unrelated_run = deepcopy(sections["workflow_runs"][0])
            unrelated_run["id"] = "11111111-1111-4111-8111-111111111111"
            sections["workflow_runs"].append(unrelated_run)
            result["workflow_run_id"] = unrelated_run["id"]
        elif corruption == "foreign_project":
            result["project_id"] = "foreign"
        else:
            definition["formula_version"] = "unsupported-engine"
            definition["definition_sha256"] = content_hash(
                {
                    "name": definition["name"],
                    "expression": definition["expression"],
                    "formula_version": definition["formula_version"],
                    "inputs": definition["input_spec_json"],
                    "output_unit": definition["output_unit"],
                }
            )
            result_payload = deepcopy(result["payload_json"])
            result_payload["formula_version"] = definition["formula_version"]
            result_payload["definition_sha256"] = definition["definition_sha256"]
            result_payload["provenance"]["formula_engine"] = definition["formula_version"]
            result_payload["provenance"]["definition_sha256"] = definition["definition_sha256"]
            result["payload_json"] = result_payload
            result["content_sha256"] = content_hash(result_payload)

    damaged = rewrite(raw, change)
    before_counts = database_counts(client)
    before_folders = set((test_settings.resolved_data_dir / "projects").iterdir())
    response = import_archive(client, damaged)
    assert response.status_code == 400, response.text
    assert database_counts(client) == before_counts
    assert set((test_settings.resolved_data_dir / "projects").iterdir()) == before_folders
