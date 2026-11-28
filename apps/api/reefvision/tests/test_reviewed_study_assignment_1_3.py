from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_scientific_project_exchange import export_archive, import_archive
from reefvision.tests.test_workflow_connected_branch_preview_1_2 import _run


def test_reviewed_study_assignment_replays_and_preserves_previous_design(
    client: TestClient, test_settings: Settings
) -> None:
    project = create_project(client, "Tank-level study")
    prefix = f"/api/v1/projects/{project['id']}/ecology"
    reviewed = {
        "tank_code": "Tank-07",
        "site_code": "Lab-East",
        "treatment_code": "Ambient",
        "sampling_unit_type": "fragment",
        "sampling_unit_id": "Sample-01",
        "reviewer": "Reviewer 1",
        "confirm_review": True,
    }
    registration = {
        "kind": "fragment",
        "organism_key": "Fragment-01",
        "reason": "Verified tank roster",
        "experimental_unit_type": "tank",
        "experimental_unit_id": "Tank-07",
        "study_assignment": reviewed,
    }
    registered = client.post(f"{prefix}/organisms", json=registration)
    assert registered.status_code == 201, registered.text
    first = registered.json()
    assert first["study_assignment"]["treatment_code"] == "Ambient"
    assert first["study_assignment"]["review_status"] == "reviewed"

    bad = client.post(
        f"{prefix}/organisms",
        json={
            **registration,
            "organism_key": "Fragment-02",
            "study_assignment": {
                **reviewed,
                "treatment_code": "Heating",
                "sampling_unit_id": "Sample-02",
            },
        },
    )
    assert bad.status_code == 400, bad.text
    assert "treatment" in bad.text

    revised = client.post(
        f"{prefix}/organisms/Fragment-01/revisions",
        json={
            key: value
            for key, value in {
                **registration,
                "expected_revision": 1,
                "reason": "Reviewed treatment correction",
                "study_assignment": {**reviewed, "treatment_code": "Shaded"},
            }.items()
            if key != "organism_key"
        },
    )
    assert revised.status_code == 201, revised.text
    registry = client.get(f"{prefix}/identity-registry").json()
    assert [row["study_assignment"]["treatment_code"] for row in registry["identity_history"]] == [
        "Ambient",
        "Shaded",
    ]
    assert registry["design_change_events"][0]["changed_fields"] == ["study_assignment"]

    graph = {
        "graph_id": "study-registry",
        "name": "Reviewed study structure",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {"node_id": "registry", "node_type": "ecology_identity_registry_source"},
        ],
        "edges": [
            {
                "edge_id": "project-registry",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": "registry",
                "target_port_id": "project",
            }
        ],
    }
    detail = _run(client, project["id"], graph)
    assert detail["run"]["status"] == "succeeded", detail
    artifact = next(
        row["payload_json"]
        for row in detail["artifacts"]
        if row["data_type"] == "ecology_identity_registry"
    )
    assert artifact["snapshot_sha256"] == registry["snapshot_sha256"]
    imported = import_archive(client, export_archive(client, test_settings, project["id"]))
    assert imported.status_code == 201, imported.text
    imported_id = imported.json()["project_id"]
    restored = client.get(f"/api/v1/projects/{imported_id}/ecology/identity-registry").json()
    assert [row["study_assignment"] for row in restored["identity_history"]] == [
        row["study_assignment"] for row in registry["identity_history"]
    ]


def test_study_sampling_units_cannot_cross_tanks(client: TestClient) -> None:
    project = create_project(client, "Separate independent tanks")
    endpoint = f"/api/v1/projects/{project['id']}/ecology/organisms"
    for tank, expected_status in (("A", 201), ("B", 400)):
        result = client.post(
            endpoint,
            json={
                "kind": "fragment",
                "organism_key": f"Fragment-{tank}",
                "experimental_unit_type": "tank",
                "experimental_unit_id": tank,
                "reason": "Verified study record",
                "study_assignment": {
                    "tank_code": tank,
                    "site_code": "Site",
                    "sampling_unit_id": "Shared-Sample",
                    "sampling_unit_type": "quadrant",
                    "reviewer": "Reviewer",
                    "confirm_review": True,
                },
            },
        )
        assert result.status_code == expected_status, result.text
