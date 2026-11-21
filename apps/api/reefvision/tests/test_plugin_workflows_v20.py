from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.jobs.project_exchange import process_project_exchange_export_job
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.tests.test_local_plugins_v20 import enable, install, package, source
from reefvision.tests.test_scientific_project_exchange import import_archive


def plugin_graph(pin: dict[str, str]) -> dict[str, Any]:
    return {
        "graph_id": "rgb-measurement",
        "name": "Measure green fraction",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "green", "node_type": "plugin_image_measurement", "parameters": pin},
        ],
        "edges": [
            {
                "edge_id": "input",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "green",
                "target_port_id": "project",
            }
        ],
    }


def test_measurement_review_pauses_until_explicit_acknowledgement(
    client: TestClient, test_settings: Settings
) -> None:
    project, image = source(client)
    plugin = enable(client, install(client, package("f64.const 0.5")))
    graph = plugin_graph(
        {"plugin_record_id": plugin["id"], "package_sha256": plugin["package_sha256"], **image}
    )
    graph["nodes"].append({"node_id": "review", "node_type": "measurement_review_gate"})
    graph["edges"].append(
        {
            "edge_id": "measure-review",
            "source_node_id": "green",
            "source_port_id": "measurement",
            "target_node_id": "review",
            "target_port_id": "measurement",
        }
    )
    base = f"/api/v1/projects/{project}"
    saved = client.post(base + "/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    queued = client.post(base + "/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert queued.status_code == 202, queued.text
    run = queued.json()
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(test_settings, app.state.session_factory, run["job_id"])
    url = "/api/v1/workflow-runs/" + run["id"]
    first = client.get(url).json()
    assert first["run"]["status"] == "waiting_for_review"
    assert not any(a["producer_port_id"] == "reviewed" for a in first["artifacts"])
    measured = next(a for a in first["artifacts"] if a["producer_port_id"] == "measurement")
    gate = next(n for n in first["nodes"] if n["node_id"] == "review")
    resume = client.post(
        "/api/v1/workflow-node-runs/" + gate["id"] + "/resume-review",
        json={"reviewed_by": "Fixture reviewer", "note": "Checked value, units and original hash."},
    )
    assert resume.status_code == 202, resume.text
    assert process_workflow_run_job(test_settings, app.state.session_factory, run["job_id"])
    final = client.get(url).json()
    assert final["run"]["status"] == "succeeded"
    assert next(a for a in final["artifacts"] if a["producer_port_id"] == "measurement") == measured
    review = next(
        a["payload_json"] for a in final["artifacts"] if a["producer_port_id"] == "reviewed"
    )
    assert review["review_approval"]["reviewed_by"] == "Fixture reviewer"
    assert review["review_approval"]["input_artifact_ids"] == [measured["id"]]
    assert review["record_ids"] == measured["payload_json"]["record_ids"]
    assert client.get(base + "/plugin-measurements").json()["items"][0]["qc"] == "unassessed"


def test_saved_plugin_runs_require_active_exact_version_and_preserve_history(
    client: TestClient, test_settings: Settings
) -> None:
    project, image = source(client)
    plugin = enable(client, install(client, package("f64.const 0.5")))
    pin = {"plugin_record_id": plugin["id"], "package_sha256": plugin["package_sha256"], **image}
    graph = plugin_graph(pin)
    base = f"/api/v1/projects/{project}"
    endpoint = base + "/workflow-graphs"
    plan = client.post(endpoint + "/plan", json=graph)
    assert plan.status_code == 200 and plan.json()["executable"], plan.text
    invalid = deepcopy(graph)
    invalid["edges"][0]["source_port_id"] = "measurement"
    assert not client.post(endpoint + "/plan", json=invalid).json()["valid"]
    saved = client.post(endpoint, json={"graph": graph})
    assert saved.status_code == 201, saved.text
    record = saved.json()
    app = cast(FastAPI, client.app)

    def run(project_base: str, graph_record_id: str) -> dict:
        queued = client.post(
            project_base + "/workflow-runs", json={"graph_record_id": graph_record_id}
        )
        assert queued.status_code == 202, queued.text
        assert process_workflow_run_job(
            test_settings, app.state.session_factory, queued.json()["job_id"]
        )
        detail = client.get("/api/v1/workflow-runs/" + queued.json()["id"]).json()
        assert detail["run"]["status"] == "succeeded", detail
        return detail

    first, second = run(base, record["id"]), run(base, record["id"])
    assert first["run"]["id"] != second["run"]["id"]
    assert first["run"]["graph_sha256"] == second["run"]["graph_sha256"] == record["graph_sha256"]

    def measurement(detail: dict) -> dict:
        return next(a for a in detail["artifacts"] if a["producer_port_id"] == "measurement")

    output = measurement(first)
    assert output["data_type"] == "scientific_record_collection"
    assert measurement(second)["payload_sha256"] == output["payload_sha256"]
    assert output["payload_json"]["plugin"]["package_sha256"] == pin["package_sha256"]
    assert output["payload_json"]["value"] == 0.5
    original_id = output["payload_json"]["record_ids"][0]
    assert client.get(base + "/plugin-measurements").json()["items"][0]["id"] == original_id
    enable(client, plugin, False)
    blocked = client.post(endpoint + "/plan", json=graph).json()
    assert not blocked["executable"] and any(
        "enable" in i["message"].lower() for i in blocked["issues"]
    )
    assert (
        client.post(base + "/workflow-runs", json={"graph_record_id": record["id"]}).status_code
        == 400
    )
    assert client.get(endpoint).json()[0]["graph_sha256"] == record["graph_sha256"]
    assert measurement(client.get("/api/v1/workflow-runs/" + first["run"]["id"]).json()) == output

    archive = client.post(
        base + "/exchange-packages", json={"include_media": True, "include_model_weights": False}
    ).json()
    assert process_project_exchange_export_job(
        test_settings, app.state.session_factory, archive["job_id"]
    )
    download = client.get("/api/v1/exchange-packages/" + archive["package"]["id"] + "/download")
    assert download.status_code == 200
    imported = import_archive(client, download.content)
    assert imported.status_code == 201, imported.text
    copied = imported.json()
    copybase = "/api/v1/projects/" + copied["project_id"]
    mapping = copied["package"]["options_json"]["id_map"]
    copied_graph = client.get(copybase + "/workflow-graphs").json()[0]
    params = copied_graph["graph_json"]["nodes"][1]["parameters"]
    assert params == {**pin, "image_id": mapping[image["image_id"]]}
    assert not client.post(
        copybase + "/workflow-graphs/plan", json=copied_graph["graph_json"]
    ).json()["executable"]
    assert (
        client.get(copybase + "/plugin-measurements").json()["items"][0]["provenance"][
            "processing_parameters"
        ]["package_sha256"]
        == pin["package_sha256"]
    )
    enable(client, plugin)
    replay = run(copybase, copied_graph["id"])
    assert measurement(replay)["payload_json"]["value"] == 0.5
