"""Reviewed annotation aggregates remain reproducible through project exchange."""

from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.scientific_data import content_hash
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_computed_aggregate_metrics import _definition, _import, _save
from reefvision.tests.test_scientific_project_exchange import (
    database_counts,
    export_archive,
    import_archive,
    rewrite,
)
from reefvision.tests.test_workflow_computed_aggregates import aggregate_graph
from reefvision.tests.test_workflow_computed_metrics import save_and_queue


def _source(client: TestClient) -> tuple[dict, dict, dict, list[str]]:
    project = create_project(client, "Portable annotation aggregate")
    first = _import(client, project["id"], 31)
    second = _import(client, project["id"], 32)
    label = str(project["label_classes"][0]["id"])
    _save(client, first, [label, label])
    _save(client, second, [label])
    # This UUID-looking value is researcher metadata, even though it is also a mapped project ID.
    for image_id in (first, second):
        response = client.patch(
            f"/api/v1/images/{image_id}",
            json={"annotation_status": "reviewed", "group_key": project["id"]},
        )
        assert response.status_code == 200, response.text
    definition = _definition(client, project["id"], grouping_level="image_group_key")
    run = save_and_queue(client, project["id"], aggregate_graph(definition["id"], [first, second]))
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run["job_id"])
    )
    result = client.get(f"/api/v1/projects/{project['id']}/computed-aggregate-results").json()[
        "items"
    ][0]
    return project, definition, result, [first, second]


def test_annotation_aggregate_round_trip_remaps_evidence_but_preserves_group_key_literal(
    client: TestClient, test_settings
) -> None:
    project, definition, result, image_ids = _source(client)
    raw = export_archive(client, test_settings, project["id"])
    imported = import_archive(client, raw)
    assert imported.status_code == 201, imported.text
    imported_project_id = imported.json()["project_id"]

    restored_definition = client.get(
        f"/api/v1/projects/{imported_project_id}/computed-aggregate-definitions"
    ).json()["items"][0]
    restored_result = client.get(
        f"/api/v1/projects/{imported_project_id}/computed-aggregate-results"
    ).json()["items"][0]
    assert restored_definition["id"] != definition["id"]
    assert restored_result["id"] != result["id"]
    assert restored_result["definition_id"] == restored_definition["id"]
    assert restored_result["observation_count"] == result["observation_count"] == 3
    assert restored_result["mean_per_independent_unit"] == 3
    assert restored_result["groups"][0]["unit_key"] == project["id"]
    assert set(restored_result["groups"][0]["image_ids"]).isdisjoint(image_ids)
    assert {item["id"] for item in restored_result["observation_snapshot"]}.isdisjoint(
        {item["id"] for item in result["observation_snapshot"]}
    )
    assert restored_result["workflow_run_id"] not in (None, result["workflow_run_id"])
    assert restored_result["workflow_node_run_id"] not in (
        None,
        result["workflow_node_run_id"],
    )
    validation = client.get(
        f"/api/v1/projects/{imported_project_id}/computed-aggregate-results/"
        f"{restored_result['id']}/validation"
    )
    assert validation.status_code == 200, validation.text
    assert validation.json()["current"] is True

    recalculated = client.post(
        f"/api/v1/projects/{imported_project_id}/computed-aggregate-definitions/"
        f"{restored_definition['id']}/calculate",
        json={"image_ids": [item["image_id"] for item in restored_result["image_snapshot"]]},
    )
    assert recalculated.status_code == 201, recalculated.text
    assert recalculated.json()["observation_count"] == result["observation_count"]
    assert recalculated.json()["groups"] == restored_result["groups"]


def test_stale_annotation_aggregate_round_trip_preserves_history_and_recalculates_current_grouping(
    client: TestClient, test_settings
) -> None:
    project, definition, result, image_ids = _source(client)
    historical_groups = deepcopy(result["groups"])
    changed_image_id = image_ids[0]
    changed = client.patch(
        f"/api/v1/images/{changed_image_id}",
        json={"annotation_status": "reviewed", "group_key": "current-colony-a"},
    )
    assert changed.status_code == 200, changed.text

    source_validation = client.get(
        f"/api/v1/projects/{project['id']}/computed-aggregate-results/{result['id']}/validation"
    )
    assert source_validation.status_code == 200, source_validation.text
    assert source_validation.json()["current"] is False
    assert f"image_group_key_changed:{changed_image_id}" in source_validation.json()["reasons"]

    raw = export_archive(client, test_settings, project["id"])
    imported = import_archive(client, raw)
    assert imported.status_code == 201, imported.text
    imported_project_id = imported.json()["project_id"]

    restored_definition = client.get(
        f"/api/v1/projects/{imported_project_id}/computed-aggregate-definitions"
    ).json()["items"][0]
    restored_result = client.get(
        f"/api/v1/projects/{imported_project_id}/computed-aggregate-results"
    ).json()["items"][0]
    assert restored_definition["id"] != definition["id"]
    assert restored_result["id"] != result["id"]
    assert restored_result["groups"] == [
        {
            **historical_groups[0],
            "image_ids": restored_result["groups"][0]["image_ids"],
            "counts_by_class": restored_result["groups"][0]["counts_by_class"],
        }
    ]
    assert restored_result["groups"][0]["unit_key"] == project["id"]
    assert set(restored_result["groups"][0]["image_ids"]).isdisjoint(image_ids)
    assert {item["id"] for item in restored_result["observation_snapshot"]}.isdisjoint(
        {item["id"] for item in result["observation_snapshot"]}
    )
    assert restored_result["provenance"]["evidence_sha256"] == restored_result["evidence_sha256"]
    assert restored_result["workflow_run_id"] not in (None, result["workflow_run_id"])
    assert restored_result["workflow_node_run_id"] not in (
        None,
        result["workflow_node_run_id"],
    )

    imported_validation = client.get(
        f"/api/v1/projects/{imported_project_id}/computed-aggregate-results/"
        f"{restored_result['id']}/validation"
    )
    assert imported_validation.status_code == 200, imported_validation.text
    assert imported_validation.json()["current"] is False
    group_key_reasons = [
        reason
        for reason in imported_validation.json()["reasons"]
        if reason.startswith("image_group_key_changed:")
    ]
    assert len(group_key_reasons) == 1

    selected_image_ids = [item["image_id"] for item in restored_result["image_snapshot"]]
    recalculated = client.post(
        f"/api/v1/projects/{imported_project_id}/computed-aggregate-definitions/"
        f"{restored_definition['id']}/calculate",
        json={"image_ids": selected_image_ids},
    )
    assert recalculated.status_code == 201, recalculated.text
    assert recalculated.json()["id"] != restored_result["id"]
    assert recalculated.json()["independent_unit_count"] == 2
    assert {group["unit_key"] for group in recalculated.json()["groups"]} == {
        project["id"],
        "current-colony-a",
    }
    historical_after = next(
        item
        for item in client.get(
            f"/api/v1/projects/{imported_project_id}/computed-aggregate-results"
        ).json()["items"]
        if item["id"] == restored_result["id"]
    )
    assert historical_after == restored_result


@pytest.mark.parametrize(
    "corruption",
    [
        "definition_hash",
        "result_hash",
        "missing_image",
        "duplicate_observation",
        "wrong_class",
        "group_total",
        "observed_at",
        "snapshot_group_key",
        "group_unit_key",
        "image_checksum",
        "workflow_provenance",
        "provenance_evidence",
    ],
)
def test_annotation_aggregate_exchange_rejects_corruption_atomically(
    client: TestClient, test_settings, corruption: str
) -> None:
    project, _, _, _ = _source(client)
    raw = export_archive(client, test_settings, project["id"])

    def change(_manifest, sections):
        definition = next(
            row
            for row in sections["computed_metric_definitions"]
            if row.get("definition_kind") == "annotation_aggregate"
        )
        result = next(
            row
            for row in sections["computed_metric_results"]
            if row.get("result_kind") == "annotation_aggregate"
        )
        payload = result["payload_json"]
        if corruption == "definition_hash":
            definition["definition_sha256"] = "0" * 64
        elif corruption == "result_hash":
            payload["observation_count"] = 999
        elif corruption == "missing_image":
            payload["image_snapshot"][0]["image_id"] = "missing"
            result["content_sha256"] = content_hash(payload)
        elif corruption == "duplicate_observation":
            payload["observation_snapshot"].append(deepcopy(payload["observation_snapshot"][0]))
            result["content_sha256"] = content_hash(payload)
        elif corruption == "wrong_class":
            payload["observation_snapshot"][0]["label_class_id"] = "missing"
            result["content_sha256"] = content_hash(payload)
        elif corruption == "observed_at":
            result["observed_at"] = "2030-01-01T00:00:00+00:00"
            payload["observed_at"] = result["observed_at"]
            result["content_sha256"] = content_hash(payload)
        elif corruption == "snapshot_group_key":
            payload["image_snapshot"][0]["group_key"] = "tampered-group"
            payload["evidence_sha256"] = content_hash(
                {
                    "definition_sha256": payload["definition_sha256"],
                    "images": payload["image_snapshot"],
                    "observations": payload["observation_snapshot"],
                    "excluded_proposals_by_status": payload["excluded_proposals_by_status"],
                }
            )
            payload["provenance"]["evidence_sha256"] = payload["evidence_sha256"]
            result["content_sha256"] = content_hash(payload)
        elif corruption == "group_unit_key":
            payload["groups"][0]["unit_key"] = "tampered-group"
            result["content_sha256"] = content_hash(payload)
        elif corruption == "image_checksum":
            payload["image_snapshot"][0]["sha256"] = "0" * 64
            payload["evidence_sha256"] = content_hash(
                {
                    "definition_sha256": payload["definition_sha256"],
                    "images": payload["image_snapshot"],
                    "observations": payload["observation_snapshot"],
                    "excluded_proposals_by_status": payload["excluded_proposals_by_status"],
                }
            )
            payload["provenance"]["evidence_sha256"] = payload["evidence_sha256"]
            result["content_sha256"] = content_hash(payload)
        elif corruption == "workflow_provenance":
            result["workflow_node_run_id"] = "missing"
        elif corruption == "provenance_evidence":
            payload["provenance"]["evidence_sha256"] = "0" * 64
            result["content_sha256"] = content_hash(payload)
        else:
            payload["groups"][0]["observation_count"] = 999
            result["content_sha256"] = content_hash(payload)

    damaged = rewrite(raw, change)
    before_counts = database_counts(client)
    before_folders = set((test_settings.resolved_data_dir / "projects").iterdir())
    response = import_archive(client, damaged)
    assert response.status_code == 400, response.text
    assert database_counts(client) == before_counts
    assert set((test_settings.resolved_data_dir / "projects").iterdir()) == before_folders
