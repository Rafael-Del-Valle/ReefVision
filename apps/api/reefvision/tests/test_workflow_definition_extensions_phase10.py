from fastapi.testclient import TestClient


def test_executable_depth_embedding_filter_and_rgbd_measurement_nodes_are_exposed(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/workflow-node-definitions")
    assert response.status_code == 200, response.text
    definitions = {item["node_type"]: item for item in response.json()}

    assert definitions["depth_estimation"]["outputs"] == [
        {"name": "depth_maps", "data_type": "depth_maps", "required": True}
    ]
    assert definitions["embedding_generation"]["outputs"] == [
        {"name": "embeddings", "data_type": "embeddings", "required": True}
    ]
    assert definitions["filter"]["inputs"] == [
        {"name": "artifact", "data_type": "artifact", "required": True}
    ]

    measurement_inputs = {
        item["name"]: item for item in definitions["measurement"]["inputs"]
    }
    assert measurement_inputs["masks"] == {
        "name": "masks",
        "data_type": "masks",
        "required": True,
    }
    assert measurement_inputs["depth_maps"] == {
        "name": "depth_maps",
        "data_type": "depth_maps",
        "required": False,
    }
