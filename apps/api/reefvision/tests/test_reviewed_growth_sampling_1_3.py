from io import BytesIO
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image

from reefvision.config import Settings
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_ecology_annotation_evidence_1_2 import _annotation_link
from reefvision.tests.test_ecology_calibration_evidence_1_2 import (
    _link_calibration,
    _save_calibration,
)
from reefvision.tests.test_ecology_image_evidence_1_2 import _link
from reefvision.tests.test_scientific_project_exchange import export_archive, import_archive
from reefvision.tests.test_workflow_connected_branch_preview_1_2 import _run


def test_reviewed_growth_retains_missing_scheduled_visits_and_complete_unit_population(
    client: TestClient,
    test_settings: Settings,
) -> None:
    project = create_project(client, "Reviewed longitudinal roster")
    project_id = project["id"]
    endpoint = f"/api/v1/projects/{project_id}/ecology"
    rosters = {"Tank-1": ["colony-a", "b"], "Tank-2": ["c"]}
    for tank, roster in rosters.items():
        for organism in roster:
            registered = client.post(
                f"{endpoint}/organisms",
                json={
                    "organism_key": organism,
                    "experimental_unit_type": "tank",
                    "experimental_unit_id": tank,
                    "kind": "individual",
                    "reason": "Reviewed planned roster",
                },
            )
            assert registered.status_code == 201, registered.text
    sources = []
    for day, width in ((1, 20), (2, 25), (3, 28)):
        image = BytesIO()
        exif = Image.Exif()
        exif[36867] = f"2026:11:{day:02d} 12:00:00"
        exif[36881] = "+00:00"
        Image.new("RGB", (80, 60), (day * 20, 0, 0)).save(image, format="JPEG", exif=exif)
        imported = client.post(
            f"/api/v1/projects/{project_id}/imports/images",
            files={"files": (f"visit-{day}.jpg", image.getvalue(), "image/jpeg")},
        )
        assert imported.status_code == 200, imported.text
        image_id = imported.json()["successful"][0]["image_id"]
        link = _link(client, project_id, "colony-a", image_id)
        assert link.status_code == 201, link.text
        annotation_id = str(uuid4())
        annotated = client.put(
            f"/api/v1/images/{image_id}/annotations",
            json={
                "base_revision": 0,
                "annotation_status": "reviewed",
                "annotations": [
                    {
                        "id": annotation_id,
                        "label_class_id": project["label_classes"][0]["id"],
                        "x_min": 5,
                        "x_max": 5 + width,
                        "y_min": 8,
                        "y_max": 20,
                    }
                ],
            },
        )
        assert annotated.status_code == 200, annotated.text
        annotation_link = _annotation_link(
            client, project_id, link.json()["id"], "box", annotation_id
        )
        assert annotation_link.status_code == 201, annotation_link.text
        _save_calibration(client, image_id)
        calibration = _link_calibration(client, project_id, annotation_link.json())
        assert calibration.status_code == 201, calibration.text
        sources.append({"calibration_evidence_id": calibration.json()["id"]})

    growth = f"{endpoint}/verified-analyses"
    selected = {
        "kind": "growth",
        "metric": "box_width",
        "sources": sources,
        "sampling_plan": [
            {
                "experimental_unit_id": unit,
                "organism_keys": roster,
                "dates": ["2026-11-01", "2026-11-02", "2026-11-03"],
            }
            for unit, roster in rosters.items()
        ],
    }
    body = {
        "selection": selected,
        "reviewed_by": "Rater",
        "review_note": "Checked exact expected roster, photo selections and calendar.",
        "confirm_reviewed_selection": True,
    }
    completed = client.post(growth, json=body)
    assert completed.status_code == 201, completed.text
    saved = completed.json()
    result = saved["snapshot"]["result"]
    assert [row["observed_organism_visits"] for row in result["planned_sampling_effort"]] == [3, 0]
    assert [row["missing_organism_visits"] for row in result["planned_sampling_effort"]] == [3, 3]
    assert result["unit_summaries"] == []
    assert result["population_summaries"] == []
    assert len(result["changes"]) == 1
    assert result["planned_sampling_date_coverage"][1]["missing_organism_ids"] == ["b"]

    graph = {
        "graph_id": "reviewed-planned-visits",
        "name": "Reviewed planned visits",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "growth",
                "node_type": "ecology_verified_analysis",
                "parameters": {"analysis_id": saved["id"]},
            },
        ],
        "edges": [
            {
                "edge_id": "review",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "growth",
                "target_port_id": "project",
            }
        ],
    }
    workflow = _run(client, project_id, graph)
    artifact = next(
        row["payload_json"]
        for row in workflow["artifacts"]
        if row["data_type"] == "verified_ecology_analysis"
    )
    assert artifact == saved
    assert "missing_observations" in client.get(f"{growth}/{saved['id']}/results.csv").text

    imported = import_archive(client, export_archive(client, test_settings, project_id))
    assert imported.status_code == 201, imported.text
    archived = imported.json()
    mapped = archived["package"]["options_json"]["id_map"][saved["id"]]
    copied_url = f"/api/v1/projects/{archived['project_id']}/ecology/verified-analyses/{mapped}"
    assert client.get(copied_url).json()["stale"] is False

    correction = client.post(
        f"{endpoint}/organisms/b/revisions",
        json={
            "expected_revision": 1,
            "kind": "individual",
            "reason": "Moved to a different tank",
            "experimental_unit_type": "tank",
            "experimental_unit_id": "Tank-3",
        },
    )
    assert correction.status_code == 201, correction.text
    stale = client.get(f"{growth}/{saved['id']}").json()
    assert stale["stale"] is True
    assert stale["snapshot"] == saved["snapshot"]
