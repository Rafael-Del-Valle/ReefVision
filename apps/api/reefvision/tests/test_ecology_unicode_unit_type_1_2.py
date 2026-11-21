"""Unicode technical labels must not become biological replicates."""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.domain.ecology_lineage_policy import (
    classify_ecological_unit_level,
    ecological_unit_types_equivalent,
)
from reefvision.domain.experimental_unit_policy import require_ecological_unit_type
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_ecology_unit_type_aliases_1_2 import _case


@pytest.mark.parametrize(
    "technical_type",
    [
        "\uff49\uff4d\uff41\uff47\uff45",
        "\uff56\uff49\uff44\uff45\uff4f\uff3f\uff46\uff52\uff41\uff4d\uff45",
        "im\u200bage",
    ],
    ids=["fullwidth-image", "fullwidth-video-frame", "zero-width-image"],
)
def test_unicode_technical_labels_rejected_without_rewriting_source(
    technical_type: str,
) -> None:
    assert any(ord(char) > 127 for char in technical_type), "fixture must contain Unicode"
    with pytest.raises(ValueError, match=r"technical replicates|control or invisible"):
        require_ecological_unit_type(technical_type)


@pytest.mark.parametrize("kind", ["longitudinal", "paired"])
@pytest.mark.parametrize(
    "technical_type",
    [
        "\uff49\uff4d\uff41\uff47\uff45",
        "\uff56\uff49\uff44\uff45\uff4f\uff3f\uff46\uff52\uff41\uff4d\uff45",
        "im\u200bage",
    ],
    ids=["fullwidth-image", "fullwidth-video-frame", "zero-width-image"],
)
def test_unicode_technical_unit_fails_standalone_and_saved_workflow(
    client: TestClient, kind: str, technical_type: str
) -> None:
    assert any(ord(char) > 127 for char in technical_type), "fixture must contain Unicode"
    endpoint, payload, graph, artifact_type = _case(kind)
    rows_key = "observations" if kind == "longitudinal" else "pairs"
    rows = payload[rows_key]
    for row in rows:
        row["experimental_unit_type"] = technical_type
    graph["nodes"][1]["parameters"][rows_key] = rows

    standalone = client.post(endpoint, json=payload)
    assert standalone.status_code == 422, standalone.text
    assert "technical replicates" in standalone.text or "control or invisible" in standalone.text

    project_id = str(create_project(client, f"Unicode technical QC {kind}")["id"])
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
            app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
        )
        is False
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "failed"
    assert all(row["data_type"] != artifact_type for row in detail.json()["artifacts"])


@pytest.mark.parametrize("kind", ["longitudinal", "paired"])
def test_compatibility_biological_alias_keeps_one_unverified_unit_in_saved_workflow(
    client: TestClient, kind: str
) -> None:
    fullwidth_tank = "\uff54\uff41\uff4e\uff4b"
    assert len(fullwidth_tank) == 4, "fixture must be four fullwidth Unicode letters"
    assert require_ecological_unit_type(fullwidth_tank) == fullwidth_tank
    assert classify_ecological_unit_level(fullwidth_tank) == "tank"
    assert ecological_unit_types_equivalent(fullwidth_tank, "aquarium")

    endpoint, payload, graph, artifact_type = _case(kind)
    rows_key = "observations" if kind == "longitudinal" else "pairs"
    rows = payload[rows_key]
    rows[0]["experimental_unit_type"] = fullwidth_tank
    graph["nodes"][1]["parameters"][rows_key] = rows
    standalone = client.post(endpoint, json=payload)
    assert standalone.status_code == 200, standalone.text
    assert standalone.json()["evidence_level"] == "caller_supplied_unverified"

    project_id = str(create_project(client, f"Unicode tank alias {kind}")["id"])
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
            app.state.settings, app.state.session_factory, str(queued.json()["job_id"])
        )
        is True
    )
    detail = client.get(f"/api/v1/workflow-runs/{queued.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    artifacts = [row for row in detail.json()["artifacts"] if row["data_type"] == artifact_type]
    assert len(artifacts) == 1
    stored = artifacts[0]["payload_json"]
    count_field = "independent_unit_count"
    if kind == "paired":
        count_field = "declared_independent_unit_count"
    assert stored[count_field] == standalone.json()[count_field] == 1
    assert stored["evidence_level"] == "caller_supplied_unverified"
    assert stored["analysis_provenance"] == standalone.json()["analysis_provenance"]
