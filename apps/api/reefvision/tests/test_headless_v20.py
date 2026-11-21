import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reefvision.tests.test_annotations import create_project


def test_console_creates_opens_a_fresh_offline_profile_and_returns_structured_errors(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "profile"
    env = {**os.environ, "REEFVISION_DATA_DIR": str(tmp_path / "unselected"), "PYTHONUTF8": "1"}

    def call(*args: str, expected: int = 0) -> dict:
        result = subprocess.run(
            [sys.executable, "-m", "reefvision.automation_cli", "--profile", str(profile), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=100,
        )
        assert result.returncode == expected, result.stderr
        return json.loads(result.stdout if expected == 0 else result.stderr)

    created = call("project", "create", "Offline CLI project")
    project = created["result"]["id"]
    assert call("project", "open", project)["result"]["name"] == "Offline CLI project"
    missing = call("project", "open", "00000000-0000-4000-8000-000000000001", expected=2)
    assert missing["error"]["status"] == 404
    assert (profile / "reefvision.db").is_file() and not (
        tmp_path / "unselected" / "reefvision.db"
    ).exists()


def test_sdk_plan_checks_graph_identity_and_rejects_an_unpinned_run(client: TestClient) -> None:
    from reefvision_sdk import AutomationError, ReefVision

    project = create_project(client, "Headless")["id"]

    def transport(method: str, path: str, body):
        response = client.request(method, "/api/v1" + path, json=body)
        return response.status_code, response.content

    sdk = ReefVision("http://127.0.0.1:8133/api/v1", transport=transport)
    assert sdk.open_project(project)["id"] == project
    graph = {
        "schema_version": "workflow-graph-0001",
        "graph_id": "cli-fixture",
        "name": "CLI fixture",
        "nodes": [{"node_id": "project", "node_type": "project_source"}],
        "edges": [],
    }
    saved = client.post(f"/api/v1/projects/{project}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    graph_id, digest = saved.json()["id"], saved.json()["graph_sha256"]
    with pytest.raises(AutomationError, match="checksum"):
        sdk.run_workflow(project, graph_id, "0" * 64)
    assert client.get(f"/api/v1/projects/{project}/workflow-runs").json() == []
    assert sdk.plan_workflow(project, graph_id, digest)["valid"]
    run = sdk.run_workflow(project, graph_id, digest)
    assert run["graph_sha256"] == digest and run["status"] == "queued"


def test_real_cli_review_exit_and_explicit_resume(tmp_path: Path) -> None:
    import httpx

    from reefvision.automation_cli import run
    from reefvision.storage.automation_session import profile_service
    from reefvision.tests.test_local_plugins_v20 import enable, install, package, source
    from reefvision.tests.test_plugin_workflows_v20 import plugin_graph

    with (
        profile_service(tmp_path / "review-profile", 60) as sdk,
        httpx.Client(
            base_url=sdk.api_url.removesuffix("/api/v1"),
            timeout=35,
            trust_env=False,
        ) as client,
    ):
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
        saved = client.post(
            f"/api/v1/projects/{project}/workflow-graphs", json={"graph": graph}
        ).json()
        command = ["--api-url", sdk.api_url, "--timeout", "45", "workflow"]
        code, raw = run([*command, "run", project, saved["id"], "--sha256", saved["graph_sha256"]])
        waiting = json.loads(raw)
        assert code == 3 and waiting["status"] == "review_required", raw
        detail = waiting["result"]
        run_id = detail["run"]["id"]
        gate = next(n for n in detail["nodes"] if n["status"] == "waiting_for_review")
        receipt = next(a for a in detail["artifacts"] if a["producer_port_id"] == "measurement")
        resume = [
            *command,
            "resume",
            project,
            run_id,
            "--node",
            gate["id"],
            "--reviewer",
            "Fixture reviewer",
            "--note",
            "Verified value and unit against the original.",
        ]
        final_code, final = run(resume)
        assert final_code == 0, final
        result = json.loads(final)["result"]
        assert result["run"]["id"] == run_id and result["run"]["status"] == "succeeded"
        assert (
            next(a for a in result["artifacts"] if a["producer_port_id"] == "measurement")
            == receipt
        )
        assert (
            next(
                a["payload_json"]
                for a in result["artifacts"]
                if a["producer_port_id"] == "reviewed"
            )["review_approval"]["reviewed_by"]
            == "Fixture reviewer"
        )
        assert run(resume)[0] == 2
