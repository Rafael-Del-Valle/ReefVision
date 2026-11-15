from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import reefvision.jobs.inference as inference_module
from reefvision.config import Settings
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_connected_branch_preview_api_1_2 import _save_calibrated_analysis
from reefvision.tests.test_scientific_project_exchange import (
    database_counts,
    export_archive,
    import_archive,
    rewrite,
)
from reefvision.tests.test_segmentation_phase3 import FakeSegmentationProvider, _seed_segmenter
from reefvision.tests.test_workflow_connected_branch_preview_1_2 import _run


def test_registered_segmenter_requires_review_before_publishing_coral_branches(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, test_settings: Settings
) -> None:
    project = create_project(client, "Segmentation-to-coral graph")
    project_id = project["id"]
    image_id = import_one(client, project_id)["successful"][0]["image_id"]
    label_id = project["label_classes"][0]["id"]
    model = _seed_segmenter(client, project_id, label_id)
    monkeypatch.setattr(
        inference_module, "segmentation_provider_for_name", lambda _: FakeSegmentationProvider()
    )
    graph = {
        "graph_id": "registered-segmentation-coral",
        "name": "Review model mask then extract branch candidates",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "images", "node_type": "project_images"},
            {
                "node_id": "model",
                "node_type": "registered_model_source",
                "parameters": {"model_id": model.id},
            },
            {
                "node_id": "segment",
                "node_type": "segmentation_inference",
                "parameters": {"device": "cpu"},
            },
            {"node_id": "review", "node_type": "mask_review_gate"},
            {"node_id": "branches", "node_type": "ecology_coral_skeleton"},
        ],
        "edges": [
            {
                "edge_id": f"{source}-{target}",
                "source_node_id": source,
                "source_port_id": output,
                "target_node_id": target,
                "target_port_id": port,
            }
            for source, output, target, port in (
                ("project", "project", "images", "project"),
                ("project", "project", "model", "project"),
                ("images", "images", "segment", "images"),
                ("model", "model", "segment", "model"),
                ("segment", "proposals", "review", "proposals"),
                ("review", "masks", "branches", "mask"),
            )
        ],
    }
    waiting = _run(client, project_id, graph)
    assert waiting["run"]["status"] == "waiting_for_review", waiting
    assert not any(row["data_type"] == "coral_skeleton_candidate" for row in waiting["artifacts"])
    proposals = client.get(f"/api/v1/images/{image_id}/prediction-proposals").json()["items"]
    assert len(proposals) == 1 and proposals[0]["review_status"] == "pending"
    accepted = client.post(
        f"/api/v1/prediction-proposals/{proposals[0]['id']}/accept",
        json={"label_class_id": label_id},
    )
    assert accepted.status_code == 200, accepted.text
    mask = accepted.json()["mask_annotation"]
    mask_id = mask["id"]
    session = client.get(f"/api/v1/images/{image_id}/annotations").json()
    saved = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": session["image"]["annotation_revision"],
            "annotation_status": "reviewed",
            "annotations": [],
            "mask_annotations": [
                {
                    "id": mask_id,
                    "label_class_id": label_id,
                    "points": [{"x": x, "y": y} for x, y in mask["polygon_json"]],
                }
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    review = next(row for row in waiting["nodes"] if row["node_id"] == "review")
    resumed = client.post(
        f"/api/v1/workflow-node-runs/{review['id']}/resume-review",
        json={"reviewed_by": "Scientist", "note": "Checked simulated colony outline"},
    )
    assert resumed.status_code == 202, resumed.text
    app = cast(FastAPI, client.app)
    run = waiting["run"]
    assert process_workflow_run_job(app.state.settings, app.state.session_factory, run["job_id"])
    detail = client.get(f"/api/v1/workflow-runs/{run['id']}").json()
    assert detail["run"]["status"] == "succeeded", detail
    proposal = next(
        row["payload_json"]
        for row in detail["artifacts"]
        if row["data_type"] == "coral_skeleton_candidate"
    )
    assert proposal["mask_annotation_id"] == mask_id
    assert proposal["evidence_level"] == "proposal_unverified"
    assert proposal["source_model_id"] == model.id
    assert proposal["source_model_sha256"] == model.sha256
    endpoint = f"/api/v1/projects/{project_id}/ecology"
    colony = post(
        client,
        f"{endpoint}/organisms",
        {"organism_key": "marked", "kind": "colony", "reason": "Fixture"},
    )
    graph_record = post(
        client,
        f"{endpoint}/coral-graphs",
        {
            "identity_revision_id": colony["id"],
            "analysis_id": proposal["analysis_id"],
            "decision": "accepted",
            "reviewer": "Scientist",
            "reason": "Checked centerline against the reviewed mask",
            "observed_at": "2026-01-01T00:00:00Z",
        },
    )
    assert graph_record["snapshot"]["edges"]
    assert graph_record["snapshot"]["source_model_sha256"] == model.sha256
    result = client.get(f"{endpoint}/coral-graphs/{graph_record['id']}/measurements.csv")
    assert result.status_code == 200, result.text
    assert graph_record["snapshot"]["edges"][0]["id"] in result.text
    assert model.sha256 in result.text
    copied = import_archive(client, export_archive(client, test_settings, project_id))
    assert copied.status_code == 201, copied.text
    imported = copied.json()
    copied_ids = imported["package"]["options_json"]["id_map"]
    restored = client.get(
        f"/api/v1/projects/{imported['project_id']}/ecology/coral-graphs/{copied_ids[graph_record['id']]}"
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["snapshot"] == graph_record["snapshot"]


def test_saved_workflow_extracts_calibrated_branch_candidates_from_verified_mask(
    client: TestClient,
    test_settings: Settings,
) -> None:
    image_id, analysis, _ = _save_calibrated_analysis(client)
    project_id = client.get(f"/api/v1/images/{image_id}").json()["project_id"]
    graph = {
        "graph_id": "calibrated-coral-branch-candidates",
        "name": "Extract verified colony mask branches",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "masks",
                "node_type": "verified_masks_source",
                "parameters": {"image_ids": [image_id]},
            },
            {"node_id": "branches", "node_type": "ecology_coral_skeleton"},
        ],
        "edges": [
            {
                "edge_id": "project-masks",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "masks",
                "target_port_id": "project",
            },
            {
                "edge_id": "masks-branches",
                "source_node_id": "masks",
                "source_port_id": "masks",
                "target_node_id": "branches",
                "target_port_id": "mask",
            },
        ],
    }
    first = _run(client, project_id, graph)
    second = _run(client, project_id, graph)
    assert first["run"]["status"] == second["run"]["status"] == "succeeded", second
    candidates = [
        item["payload_json"]
        for run in [first, second]
        for item in run["artifacts"]
        if item["data_type"] == "coral_skeleton_candidate"
    ]
    assert len(candidates) == 2
    assert candidates[0] == candidates[1]
    proposal = candidates[0]
    assert proposal["analysis_id"] == analysis["id"]
    assert proposal["analysis_sha256"] == analysis["result_sha256"]
    assert proposal["evidence_level"] == "proposal_unverified"
    assert proposal["review_gate"] == "scientist_review_required"
    assert proposal["physical_unit"] == "mm"
    assert proposal["total_length_physical"] == 9.75
    assert len(proposal["nodes"]) == 2
    assert len(proposal["edges"]) == 1
    review = client.get(f"/api/v1/projects/{project_id}/ecology/coral-graphs")
    assert review.status_code == 200, review.text
    assert review.json() == []

    imported = import_archive(client, export_archive(client, test_settings, project_id))
    assert imported.status_code == 201, imported.text
    value = imported.json()
    mapped = value["package"]["options_json"]["id_map"]
    copied = client.get(f"/api/v1/workflow-runs/{mapped[first['run']['id']]}")
    assert copied.status_code == 200, copied.text
    restored = next(
        item["payload_json"]
        for item in copied.json()["artifacts"]
        if item["data_type"] == "coral_skeleton_candidate"
    )
    assert restored["analysis_id"] == mapped[analysis["id"]]
    assert restored["image_id"] == mapped[image_id]
    assert restored["total_length_physical"] == proposal["total_length_physical"]


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

    restored = post(
        client,
        endpoint,
        {
            **change,
            "base_revision_id": updated["id"],
            "decision": "accepted",
            "edit": None,
            "restore_revision_id": original["id"],
        },
    )
    assert restored["snapshot"]["edges"] == original["snapshot"]["edges"]
    assert restored["snapshot"]["restored_from_sha256"] == original["content_sha256"]
    redone = post(
        client,
        endpoint,
        {
            **change,
            "base_revision_id": restored["id"],
            "decision": "accepted",
            "edit": None,
            "restore_revision_id": updated["id"],
        },
    )
    assert redone["snapshot"]["edges"] == updated["snapshot"]["edges"]
    assert redone["snapshot"]["restored_from_sha256"] == updated["content_sha256"]


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

    def change_growth(_manifest: dict[str, Any], sections: dict[str, Any]) -> None:
        forged = sections["coral_growth_records"][0]
        result = forged["payload_json"]
        result["total"]["absolute_change"] = 250
        forged["content_sha256"] = canonical_json_sha256(result)

    def change_source(_manifest: dict[str, Any], sections: dict[str, Any]) -> None:
        source = next(
            row
            for row in sections["skeleton_analysis_revisions"]
            if row["id"] == first_analysis["id"]
        )
        source["result_json"]["removed_spur_count"] += 1

    def change_correspondence(_manifest: dict[str, Any], sections: dict[str, Any]) -> None:
        row = sections["coral_branch_correspondence_revisions"][0]
        match = row["payload_json"]["matches"][0]
        match["status"] = "missing"
        match["later_branch_ids"] = []
        row["content_sha256"] = canonical_json_sha256(row["payload_json"])

    for edit, message in (
        (change_growth, "does not replay"),
        (change_source, "does not match the exchange snapshot"),
        (change_correspondence, "Review each branch exactly once"),
    ):
        tampered = rewrite(raw, edit)
        before_counts = database_counts(client)
        inspected = client.post(
            "/api/v1/exchange-packages/inspect",
            files={"file": ("tampered.zip", tampered, "application/zip")},
        )
        assert not inspected.json()["compatible"]
        assert message in " ".join(inspected.json()["errors"])
        assert import_archive(client, tampered).status_code == 400
        assert database_counts(client) == before_counts
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


def test_unrelated_split_cannot_clear_a_reviewed_gap(client: TestClient) -> None:
    image_id, source, _ = _save_calibrated_analysis(client)
    project_id = client.get(f"/api/v1/images/{image_id}").json()["project_id"]
    base = f"/api/v1/projects/{project_id}/ecology"
    colony = post(
        client,
        f"{base}/organisms",
        {
            "organism_key": "gap-colony",
            "kind": "colony",
            "reason": "Permanent field ID",
        },
    )
    request = {
        "identity_revision_id": colony["id"],
        "analysis_id": source["id"],
        "decision": "accepted",
        "reviewer": "Scientist",
        "reason": "Reviewed visible trace",
        "observed_at": "2026-03-10T10:00:00Z",
    }
    gap = {
        "disposition": "occluded",
        "points": [{"x": 3, "y": 3}, {"x": 4, "y": 3}],
        "reason": "Overlapping animal",
    }
    original = post(client, f"{base}/coral-graphs", {**request, "gaps": [gap]})
    branch = original["snapshot"]["edges"][0]
    split = {
        **request,
        "base_revision_id": original["id"],
        "edit": {
            "kind": "split",
            "branch_ids": [branch["id"]],
            "points": [branch["pixels"][3]],
        },
    }
    forged = client.post(
        f"{base}/coral-graphs",
        json={
            **split,
            "gaps": [{**gap, "disposition": "observed_attachment"}],
        },
    )
    assert forged.status_code == 400, forged.text
    assert "measured attachment path" in forged.text
    saved = post(client, f"{base}/coral-graphs", split)
    assert saved["snapshot"]["gaps"] == [gap]
    assert not saved["snapshot"]["eligible_for_growth"]
