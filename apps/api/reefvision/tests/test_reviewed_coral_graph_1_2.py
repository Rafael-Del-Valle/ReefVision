from typing import Any, cast
from uuid import uuid4

from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.tests.test_annotations import import_one
from reefvision.tests.test_connected_branch_preview_api_1_2 import _save_calibrated_analysis
from reefvision.tests.test_scientific_project_exchange import export_archive, import_archive
from reefvision.tests.test_workflow_connected_branch_preview_1_2 import _run


def test_reviewed_graph_records_keep_rejected_edit_and_stable_edges(client: TestClient) -> None:
    image_id, source, path = _save_calibrated_analysis(client)
    project_id = client.get(f"/api/v1/images/{image_id}").json()["project_id"]
    prefix = f"/api/v1/projects/{project_id}/ecology"
    identity = client.post(
        f"{prefix}/organisms",
        json={"organism_key": "colony-1", "kind": "colony", "reason": "Marked colony"},
    )
    assert identity.status_code == 201, identity.text
    endpoint = f"{prefix}/coral-graphs"
    initial = client.post(
        endpoint,
        json={
            "identity_revision_id": identity.json()["id"],
            "analysis_id": source["id"],
            "decision": "accepted",
            "reviewer": "Scientist",
            "reason": "Traced the reviewed mask",
            "observed_at": "2026-01-01T10:00:00Z",
        },
    )
    assert initial.status_code == 201, initial.text
    original = initial.json()
    change = {
        "identity_revision_id": identity.json()["id"],
        "analysis_id": source["id"],
        "base_revision_id": original["id"],
        "decision": "rejected",
        "reviewer": "Scientist",
        "reason": "Review attempt",
        "observed_at": "2026-01-01T10:00:00Z",
        "edit": {"kind": "add", "points": path},
    }
    rejected = client.post(endpoint, json=change)
    assert rejected.status_code == 201, rejected.text
    assert rejected.json()["decision"] == "rejected"
    assert client.get(f"{endpoint}/{original['id']}").json()["current"]
    accepted = client.post(endpoint, json={**change, "decision": "accepted"})
    assert accepted.status_code == 201, accepted.text
    updated = accepted.json()
    assert updated["graph_id"] == original["graph_id"]
    assert updated["snapshot"]["total_physical"] == original["snapshot"]["total_physical"] + 0.75
    assert len(updated["snapshot"]["supersession"]) == 1
    assert not client.get(f"{endpoint}/{original['id']}").json()["current"]
    assert client.get(f"{endpoint}/{rejected.json()['id']}").json()["decision"] == "rejected"
    stale = client.post(endpoint, json={**change, "decision": "accepted"})
    assert stale.status_code == 409, stale.text


def test_two_date_growth_saved_workflow_exchange_and_stale_review(
    client: TestClient,
    test_settings: Settings,
) -> None:
    first_image, first_analysis, _ = _save_calibrated_analysis(client)
    project_id = client.get(f"/api/v1/images/{first_image}").json()["project_id"]
    endpoint = f"/api/v1/projects/{project_id}/ecology"
    identity = post(
        client,
        f"{endpoint}/organisms",
        {"organism_key": "growth-colony", "kind": "colony", "reason": "Field label"},
    )
    project = client.get(f"/api/v1/projects/{project_id}").json()
    second_image = import_one(client, project_id, size=(82, 60))["successful"][0]["image_id"]
    second_mask = str(uuid4())
    annotation = client.put(
        f"/api/v1/images/{second_image}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [],
            "mask_annotations": [
                {
                    "id": second_mask,
                    "label_class_id": project["label_classes"][0]["id"],
                    "geometry_kind": "polygon",
                    "points": [
                        {"x": x, "y": y} for x, y in [(10, 20), (64, 20), (64, 30), (10, 30)]
                    ],
                }
            ],
        },
    )
    assert annotation.status_code == 200, annotation.text
    calibration_url = f"/api/v1/images/{second_image}/measurement-calibration"
    calibration = {"distance_per_pixel": 0.25, "source": "manual_scale_bar", "unit": "mm"}
    assert client.put(calibration_url, json=calibration).status_code == 200
    analysis = client.post(f"/api/v1/mask-annotations/{second_mask}/skeleton-analyses", json={})
    assert analysis.status_code == 200, analysis.text
    reviews = [
        {
            "identity_revision_id": identity["id"],
            "analysis_id": analysis_id,
            "decision": "accepted",
            "reviewer": "Scientist",
            "reason": "Verified marked colony and trace",
            "observed_at": observed,
        }
        for analysis_id, observed in [
            (first_analysis["id"], "2026-01-01T10:00:00Z"),
            (analysis.json()["id"], "2026-01-03T10:00:00Z"),
        ]
    ]
    before, after = [post(client, f"{endpoint}/coral-graphs", request) for request in reviews]
    payload = {
        "earlier_graph_revision_id": before["id"],
        "later_graph_revision_id": after["id"],
        "reviewer": "Scientist",
        "reason": "Same terminal endpoints and unique specimen label",
        "matches": [
            {
                "status": "matched",
                "earlier_branch_ids": [before["snapshot"]["edges"][0]["id"]],
                "later_branch_ids": [after["snapshot"]["edges"][0]["id"]],
                "reason": "Same stem with visible endpoints",
            }
        ],
    }
    correspondence = post(client, f"{endpoint}/coral-correspondences", payload)
    result = post(
        client, f"{endpoint}/coral-growth", {"correspondence_revision_id": correspondence["id"]}
    )
    assert result["snapshot"]["total"]["absolute_change"] == 1
    assert result["snapshot"]["branches"][0]["change"]["change_per_day"] == 0.5
    assert result["stale_reasons"] == []
    assert (
        "absolute_change" in client.get(f"{endpoint}/coral-growth/{result['id']}/results.csv").text
    )

    definition = {
        "graph_id": "coral-growth-replay",
        "name": "Coral growth replay",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "growth",
                "node_type": "ecology_coral_growth",
                "parameters": {"correspondence_revision_id": correspondence["id"]},
            },
        ],
        "edges": [
            {
                "edge_id": "project-growth",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "growth",
                "target_port_id": "project",
            }
        ],
    }
    run = _run(client, project_id, definition)
    assert run["run"]["status"] == "succeeded", run
    matching = next(row for row in run["artifacts"] if row["data_type"] == "coral_branch_growth")
    assert matching["payload_json"]["snapshot"] == result["snapshot"]
    assert matching["payload_json"]["content_sha256"] == result["content_sha256"]

    revised = post(
        client,
        f"{endpoint}/coral-correspondences",
        {
            **payload,
            "base_revision_id": correspondence["id"],
            "reason": "Rechecked both dates",
        },
    )
    old = client.get(f"{endpoint}/coral-growth/{result['id']}").json()
    assert old["snapshot"] == result["snapshot"]
    assert old["stale_reasons"] == ["superseded_correspondence"]
    assert (
        client.post(
            f"{endpoint}/coral-growth", json={"correspondence_revision_id": correspondence["id"]}
        ).status_code
        == 409
    )
    second = post(client, f"{endpoint}/coral-growth", {"correspondence_revision_id": revised["id"]})
    assert second["stale_reasons"] == []

    raw = export_archive(client, test_settings, project_id)
    imported = import_archive(client, raw)
    assert imported.status_code == 201, imported.text
    value = imported.json()
    mapped = value["package"]["options_json"]["id_map"]
    copied_endpoint = f"/api/v1/projects/{value['project_id']}/ecology"
    copied = client.get(f"{copied_endpoint}/coral-growth/{mapped[second['id']]}")
    assert copied.status_code == 200, copied.text
    assert copied.json()["snapshot"] == second["snapshot"]
    assert copied.json()["stale_reasons"] == []
    historic = client.get(f"{copied_endpoint}/coral-growth/{mapped[result['id']]}").json()
    assert historic["stale_reasons"] == old["stale_reasons"]

    assert (
        client.put(calibration_url, json={**calibration, "distance_per_pixel": 0.5}).status_code
        == 200
    )
    stale = client.get(f"{endpoint}/coral-growth/{second['id']}").json()
    assert stale["stale_reasons"] == ["later_source_calibration_changed"]
    assert stale["snapshot"] == second["snapshot"]


def post(client: TestClient, endpoint: str, data: dict[str, Any]) -> dict[str, Any]:
    response = client.post(endpoint, json=data)
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def test_reviewed_graph_refresh_keeps_ids_and_corrects_stale_calibration(
    client: TestClient,
) -> None:
    image_id, source, _ = _save_calibrated_analysis(client)
    project_id = client.get(f"/api/v1/images/{image_id}").json()["project_id"]
    base = f"/api/v1/projects/{project_id}/ecology"
    colony = post(
        client,
        f"{base}/organisms",
        {
            "organism_key": "same-colony",
            "kind": "colony",
            "reason": "Permanent field ID",
        },
    )
    request = {
        "identity_revision_id": colony["id"],
        "analysis_id": source["id"],
        "decision": "accepted",
        "reviewer": "Scientist",
        "reason": "Measured source mask",
        "observed_at": "2026-03-10T10:00:00Z",
    }
    first = post(client, f"{base}/coral-graphs", request)
    graph_url = f"{base}/coral-graphs/{first['id']}"
    response = client.put(
        f"/api/v1/images/{image_id}/measurement-calibration",
        json={
            "distance_per_pixel": 0.5,
            "unit": "mm",
            "source": "manual_scale_bar",
        },
    )
    assert response.is_success, response.text
    assert client.get(graph_url).json()["stale_reasons"] == ["source_calibration_changed"]
    analysis = client.post(
        f"/api/v1/mask-annotations/{source['mask_annotation_id']}/skeleton-analyses", json={}
    )
    assert analysis.is_success, analysis.text
    refreshed = post(
        client,
        f"{base}/coral-graphs",
        {
            **request,
            "analysis_id": analysis.json()["id"],
            "base_revision_id": first["id"],
        },
    )
    assert refreshed["graph_id"] == first["graph_id"]
    assert refreshed["snapshot"]["nodes"] == first["snapshot"]["nodes"]
    assert refreshed["snapshot"]["edges"][0]["id"] == first["snapshot"]["edges"][0]["id"]
    assert refreshed["snapshot"]["total_physical"] == 2 * first["snapshot"]["total_physical"]
    assert refreshed["current"]
    assert client.get(graph_url).json()["snapshot"] == first["snapshot"]
