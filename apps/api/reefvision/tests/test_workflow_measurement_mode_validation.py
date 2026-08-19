from fastapi.testclient import TestClient

from reefvision.tests.test_annotations import create_project


def test_coral_measurement_mode_still_requires_masks(client: TestClient) -> None:
    project = create_project(client, "Workflow measurement validation")
    response = client.post(
        f"/api/v1/projects/{project['id']}/workflows/validate",
        json={
            "name": "Missing coral mask",
            "nodes": [
                {
                    "id": "measure",
                    "node_type": "measurement",
                    "configuration": {},
                }
            ],
            "edges": [],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["valid"] is False
    assert any(
        issue["code"] == "measurement_mode_input_missing"
        and issue["node_id"] == "measure"
        and "masks" in issue["message"]
        for issue in payload["issues"]
    )


def test_video_depth_3d_mode_requires_video_and_tracks(client: TestClient) -> None:
    project = create_project(client, "Workflow 3D validation")
    response = client.post(
        f"/api/v1/projects/{project['id']}/workflows/validate",
        json={
            "name": "Incomplete 3D workflow",
            "nodes": [
                {"id": "video", "node_type": "video_input", "configuration": {}},
                {
                    "id": "measure3d",
                    "node_type": "measurement",
                    "configuration": {"measurement_mode": "video_depth_3d"},
                },
            ],
            "edges": [
                {
                    "source_node_id": "video",
                    "source_port": "video",
                    "target_node_id": "measure3d",
                    "target_port": "video",
                }
            ],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["valid"] is False
    missing = [
        issue
        for issue in payload["issues"]
        if issue["code"] == "measurement_mode_input_missing"
        and issue["node_id"] == "measure3d"
    ]
    assert len(missing) == 1
    assert "tracks" in missing[0]["message"]
