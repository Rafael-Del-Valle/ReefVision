from typing import Any

from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_multispectral import spectral_fixture
from reefvision.tests.test_reviewer_lab_v15 import successful
from reefvision.tests.test_scientific_project_exchange import (
    database_counts,
    export_archive,
    import_archive,
    rewrite,
)
from reefvision.tests.test_workflow_execution_phase10 import _queue_run, _save_graph


def test_spectral_originals_and_bands_rebind_with_two_copies_and_reject_fabricated_estimate(
    client: TestClient, test_settings: Settings
) -> None:
    root, data, _ = spectral_fixture(client)
    pid = root.split("/")[-2]
    capture = successful(client.post(root + "/acquisitions", json=data), 201)
    report = successful(
        client.post(
            root + "/acquisitions/" + capture["id"] + "/indices",
            json={"positive": 1, "negative": 0, "acquisition_sha256": capture["content_sha256"]},
        ),
        201,
    )
    graph = _save_graph(
        client,
        pid,
        {
            "graph_id": "spectral-index-transfer",
            "name": "Generated registered index",
            "nodes": [
                {"node_id": "project", "node_type": "project_source"},
                {
                    "node_id": "index",
                    "node_type": "multispectral_index",
                    "parameters": {
                        "index_id": report["id"],
                        "content_sha256": report["content_sha256"],
                    },
                },
            ],
            "edges": [
                {
                    "edge_id": "replay",
                    "source_node_id": "project",
                    "source_port_id": "project",
                    "target_node_id": "index",
                    "target_port_id": "project",
                }
            ],
        },
    )

    def run(project: str, graph_id: str, expected: dict[str, Any]) -> None:
        queued = _queue_run(client, project, graph_id)
        state = client.app.state
        assert process_workflow_run_job(state.settings, state.session_factory, queued["job_id"])
        detail = successful(client.get("/api/v1/workflow-runs/" + queued["id"]))
        [artifact] = [a for a in detail["artifacts"] if a["data_type"] == "multispectral_index"]
        assert artifact["payload_json"] == expected

    run(pid, graph["id"], report)
    archive = export_archive(client, test_settings, pid)

    def rehash_fabricated_mean(_manifest, rows):
        index = rows["multispectral_indices"][0]
        index["snapshot_json"]["result"]["mean"] = 0.75
        index["content_sha256"] = canonical_json_sha256(index["snapshot_json"])

    tampered = rewrite(archive, rehash_fabricated_mean)
    baselines = database_counts(client)
    inspected = successful(
        client.post(
            "/api/v1/exchange-packages/inspect",
            files={"file": ("changed.zip", tampered, "application/zip")},
        )
    )
    assert not inspected["compatible"] and any("reproduced" in m for m in inspected["errors"])
    assert import_archive(client, tampered).status_code == 400
    assert database_counts(client) == baselines

    def change_workflow_output(_manifest, rows):
        [artifact] = [
            a for a in rows["workflow_artifacts"] if a["data_type"] == "multispectral_index"
        ]
        artifact["payload_json"]["snapshot"]["result"]["mean"] = 0.75
        artifact["payload_sha256"] = canonical_json_sha256(artifact["payload_json"])
        producer = next(
            n for n in rows["workflow_node_runs"] if n["id"] == artifact["producer_node_run_id"]
        )
        for output in producer["result_json"]["outputs"]:
            if output["artifact_id"] == artifact["id"]:
                output["payload_sha256"] = artifact["payload_sha256"]

    changed_output = rewrite(archive, change_workflow_output)
    rejected = successful(
        client.post(
            "/api/v1/exchange-packages/inspect", files={"file": ("output.zip", changed_output)}
        )
    )
    assert not rejected["compatible"] and any("spectral workflow" in m for m in rejected["errors"])
    assert import_archive(client, changed_output).status_code == 400
    assert database_counts(client) == baselines
    index_id = report["id"]
    graph_id = graph["id"]
    for _ in range(2):
        restored = successful(import_archive(client, archive), 201)
        pid = restored["project_id"]
        local = restored["package"]["options_json"]["id_map"]
        index_id, graph_id = local[index_id], local[graph_id]
        rebound = successful(
            client.get(f"/api/v1/projects/{pid}/multispectral/indices/{index_id}/export")
        )
        assert (
            rebound["snapshot"] == report["snapshot"]
            and rebound["content_sha256"] == report["content_sha256"]
        )
        run(pid, graph_id, rebound)
        archive = export_archive(client, test_settings, pid)
