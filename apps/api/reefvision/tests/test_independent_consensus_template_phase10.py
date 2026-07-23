from fastapi.testclient import TestClient


def test_independent_mask_workflow_template_exposes_exact_article_mode(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/workflow-templates")
    assert response.status_code == 200, response.text
    templates = {item["template_id"]: item for item in response.json()}
    template = templates["independent-mask-segmentation-auto-labeling"]
    node = next(
        item
        for item in template["workflow"]["nodes"]
        if item["id"] == "independent-mask-consensus"
    )
    consensus = node["configuration"]["multi_model_consensus"]
    assert consensus["mode"] == "independent_masks"
    assert consensus["required_votes"] == 2
    assert consensus["aggregation"] == "pixel_majority"
    assert consensus["auto_accept"] is False
    assert consensus["allow_remote_review"] is False
    assert consensus["sam2_model_id"].startswith("<select-")
