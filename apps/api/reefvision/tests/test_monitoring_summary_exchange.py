import json
from io import BytesIO
from typing import Any
from zipfile import ZipFile

from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_monitoring_project_summaries import _selections, _site
from reefvision.tests.test_paired_growth_contrast import _run_graph
from reefvision.tests.test_scientific_project_exchange import (
    MANIFEST,
    database_counts,
    export_archive,
    import_archive,
    rewrite,
)


def test_summary_replays_its_original_projects_across_two_exchanges(
    client: TestClient, test_settings: Settings
) -> None:
    a = _site(client, "Local reference logger", [18, 20])
    b = _site(client, "Regional logger", [20, 20])
    project = a[0]
    base = f"/api/v1/projects/{project}"
    response = client.post(base + "/monitoring/summaries", json=_selections(a, b))
    assert response.is_success, response.text
    original = response.json()
    graph = {
        "graph_id": "monitoring-replay",
        "name": "Compare two observation windows",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "comparison",
                "node_type": "monitoring_project_summary",
                "parameters": {
                    "summary_id": original["id"],
                    "content_sha256": original["content_sha256"],
                },
            },
        ],
        "edges": [
            {
                "edge_id": "project-comparison",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "comparison",
                "target_port_id": "project",
            }
        ],
    }
    saved = client.post(base + "/workflow-graphs", json={"graph": graph})
    assert saved.is_success, saved.text
    expected_rows = original["snapshot"]["rows"]
    assert [row["project_id"] for row in expected_rows] == [a[0], b[0]]
    raw = export_archive(client, test_settings, project)
    with ZipFile(BytesIO(raw)) as archive:
        assert json.loads(archive.read(MANIFEST))["format_version"] == "1.7.1"

    def repoint_owner(manifest: dict[str, Any], sections: dict[str, list[dict[str, Any]]]) -> None:
        row = sections["monitoring_project_summaries"][0]
        row["snapshot_json"]["reference_project_id"] = b[0]
        row["content_sha256"] = canonical_json_sha256(row["snapshot_json"])

    baseline = database_counts(client)
    bad = import_archive(client, rewrite(raw, repoint_owner))
    assert bad.status_code == 400, bad.text
    assert database_counts(client) == baseline
    for _ in range(2):
        copied = import_archive(client, raw)
        assert copied.is_success, copied.text
        dest = copied.json()["project_id"]
        mapping = copied.json()["package"]["options_json"]["origin_id_map"]
        local_summary = client.get(
            f"/api/v1/projects/{dest}/monitoring/summaries/{mapping[original['id']]}"
        )
        assert local_summary.is_success, local_summary.text
        assert local_summary.json()["project_id"] == dest and dest not in {a[0], b[0]}
        assert local_summary.json()["content_sha256"] == original["content_sha256"]
        assert local_summary.json()["snapshot"] == original["snapshot"]
        replay = _run_graph(client, dest, mapping[saved.json()["id"]])
        assert replay["run"]["status"] == "succeeded", replay
        [artifact] = [
            out for out in replay["artifacts"] if out["data_type"] == "monitoring_project_summary"
        ]
        assert artifact["payload_json"] == local_summary.json()
        raw = export_archive(client, test_settings, dest)
