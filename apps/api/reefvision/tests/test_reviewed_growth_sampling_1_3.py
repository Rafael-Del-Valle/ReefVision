from io import BytesIO
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image

from reefvision.config import Settings
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_ecology_calibration_evidence_1_2 import (
    _link_calibration,
    _save_calibration,
)
from reefvision.tests.test_ecology_image_evidence_1_2 import _link
from reefvision.tests.test_scientific_project_exchange import export_archive, import_archive
from reefvision.tests.test_workflow_connected_branch_preview_1_2 import _run


def _growth_sources(
    client: TestClient, project: dict[str, Any], organism: str, visits: list[tuple[int, int]]
) -> list[dict[str, str]]:
    project_id = project["id"]
    sources = []
    for day, width in visits:
        image = BytesIO()
        exif = Image.Exif()
        exif[36867] = f"2026:11:{day:02d} 12:00:00"
        exif[36881] = "+00:00"
        Image.new("RGB", (80, 60), (day * 20, day * width % 255, 0)).save(
            image, format="JPEG", exif=exif
        )
        imported = client.post(
            f"/api/v1/projects/{project_id}/imports/images",
            files={"files": (f"visit-{day}.jpg", image.getvalue(), "image/jpeg")},
        )
        assert imported.status_code == 200, imported.text
        image_id = imported.json()["successful"][0]["image_id"]
        link = _link(client, project_id, organism, image_id)
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
        annotation_link = client.post(
            f"/api/v1/projects/{project_id}/ecology/organisms/{organism}/annotation-evidence",
            json={
                "image_evidence_id": link.json()["id"],
                "annotation_kind": "box",
                "annotation_id": annotation_id,
                "expected_annotation_revision": 1,
                "reason": "Reviewed source-image annotation",
            },
        )
        assert annotation_link.status_code == 201, annotation_link.text
        _save_calibration(client, image_id)
        calibration = _link_calibration(
            client, project_id, annotation_link.json(), organism_key=organism
        )
        assert calibration.status_code == 201, calibration.text
        sources.append({"calibration_evidence_id": calibration.json()["id"]})
    return sources


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
    sources = _growth_sources(client, project, "colony-a", [(1, 20), (2, 25), (3, 28)])

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
    coverage = client.post(
        f"/api/v1/projects/{project_id}/research-reports",
        json={
            "source_kind": "ecology",
            "source_id": saved["id"],
            "figure": "sample_coverage",
            "title": "Scheduled visits",
        },
    )
    assert coverage.status_code == 201, coverage.text
    visits, missing = coverage.json()["snapshot"]["series"]
    assert [(p["y"], p["denominator"]) for p in visits["points"]] == [(3, 6), (0, 3)]
    assert [(p["y"], p["denominator"]) for p in missing["points"]] == [(3, 6), (3, 3)]

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


def test_treatment_figure_weights_tanks_matches_windows_and_reopens(
    client: TestClient, test_settings: Settings
) -> None:
    project = create_project(client, "Tank treatments")
    project_id = project["id"]
    endpoint = f"/api/v1/projects/{project_id}/ecology"
    sources = []
    design = [
        ("fragment-a", "Tank-A", "Ambient", 3, 28),
        ("fragment-b", "Tank-A", "Ambient", 3, 32),
        ("fragment-c", "Tank-B", "Ambient", 3, 36),
        ("fragment-d", "Tank-C", "Shade", 3, 44),
        ("fragment-e", "Tank-D", "Shade", 4, 48),
        ("fragment-f", "Tank-E", None, 3, 52),
    ]
    for organism, tank, treatment, day, width in design:
        registered = client.post(
            f"{endpoint}/organisms",
            json={
                "organism_key": organism,
                "kind": "individual",
                "reason": "Study roster",
                "experimental_unit_type": "tank",
                "experimental_unit_id": tank,
                "study_assignment": {
                    "tank_code": tank,
                    "treatment_code": treatment,
                    "reviewer": "Design reviewer",
                    "confirm_review": True,
                },
            },
        )
        assert registered.status_code == 201, registered.text
        start_width = 20 + ord(organism[-1]) - ord("a")
        sources.extend(
            _growth_sources(
                client, project, organism, [(1, start_width), (day, width + start_width - 20)]
            )
        )
    analysis = client.post(
        f"{endpoint}/verified-analyses",
        json={
            "selection": {"kind": "growth", "metric": "box_width", "sources": sources},
            "reviewed_by": "Measurements reviewer",
            "review_note": "Confirmed selected image-plane measurements.",
            "confirm_reviewed_selection": True,
        },
    )
    assert analysis.status_code == 201, analysis.text
    saved = analysis.json()
    reports = f"/api/v1/projects/{project_id}/research-reports"
    figure = client.post(
        reports,
        json={
            "source_kind": "ecology",
            "source_id": saved["id"],
            "figure": "treatment_summary",
            "title": "Growth by tank treatment",
        },
    )
    assert figure.status_code == 201, figure.text
    report = figure.json()
    snapshot = report["snapshot"]
    assert "sample SD" in snapshot["uncertainty"]
    assert [row["label"] for row in snapshot["series"]] == ["Ambient", "Shade"]
    assert [(r["points"][0]["y"], r["points"][0]["denominator"]) for r in snapshot["series"]] == [
        (3.25, 2),
        (6.0, 1),
    ]
    assert all(len(r["points"]) == 1 for r in snapshot["series"])
    assert any("Tank-D" in text for text in snapshot["exclusions"])
    assert any("Tank-E" in text for text in snapshot["exclusions"])
    imported = import_archive(client, export_archive(client, test_settings, project_id))
    assert imported.status_code == 201, imported.text
    target = imported.json()
    mapped = target["package"]["options_json"]["id_map"][report["id"]]
    copy = client.get(f"/api/v1/projects/{target['project_id']}/research-reports/{mapped}")
    assert copy.status_code == 200, copy.text
    assert copy.json()["snapshot"] == snapshot
    assert not copy.json()["stale"]
    graph = {
        "graph_id": "publication-from-configuration",
        "name": "Publish treatment comparison",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "figure",
                "node_type": "research_publication_figure",
                "parameters": {"configuration": snapshot["configuration"]},
            },
        ],
        "edges": [
            {
                "edge_id": "figure-input",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "figure",
                "target_port_id": "project",
            }
        ],
    }
    run = _run(client, project_id, graph)
    assert run["run"]["status"] == "succeeded", run
    artifact = next(row for row in run["artifacts"] if row["data_type"] == "research_report_figure")
    assert artifact["payload_json"]["content_sha256"] == report["content_sha256"]


def test_treatment_report_excludes_declared_individuals_nested_under_tank_treatment(
    client: TestClient,
) -> None:
    project = create_project(client, "Tank-level treatment with technical repeats")
    project_id = project["id"]
    endpoint = f"/api/v1/projects/{project_id}/ecology"
    sources = []
    for index, (tank, treatment) in enumerate(
        [("Tank-A", "Ambient"), ("Tank-A", "Ambient"), ("Tank-B", "Shade"), ("Tank-B", "Shade")]
    ):
        organism = f"fish-{index}"
        registered = client.post(
            f"{endpoint}/organisms",
            json={
                "organism_key": organism,
                "kind": "individual",
                "reason": "Study roster",
                "experimental_unit_type": "individual",
                "experimental_unit_id": organism,
                "study_assignment": {
                    "tank_code": tank,
                    "treatment_code": treatment,
                    "reviewer": "Design reviewer",
                    "confirm_review": True,
                },
            },
        )
        assert registered.status_code == 201, registered.text
        sources.extend(
            _growth_sources(client, project, organism, [(1, 20 + index), (3, 25 + index)])
        )
    analysis = client.post(
        f"{endpoint}/verified-analyses",
        json={
            "selection": {"kind": "growth", "metric": "box_width", "sources": sources},
            "reviewed_by": "Measurements reviewer",
            "review_note": "Confirmed selected image-plane measurements.",
            "confirm_reviewed_selection": True,
        },
    )
    assert analysis.status_code == 201, analysis.text
    figure = client.post(
        f"/api/v1/projects/{project_id}/research-reports",
        json={
            "source_kind": "ecology",
            "source_id": analysis.json()["id"],
            "figure": "treatment_summary",
            "title": "Growth by tank treatment",
        },
    )
    assert figure.status_code == 400, figure.text
    assert "tank" in figure.json()["detail"].lower()
