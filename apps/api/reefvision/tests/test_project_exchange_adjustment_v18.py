from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from reefvision.domain.errors import ValidationError
from reefvision.services.project_exchange_adjustment_v18 import (
    SECTION,
    remap_adjustment_parameters,
    restore_adjustment_row,
    validate_adjustment_exchange,
)
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_image_adjustments_v18 import make_source, save_recipe


def test_adjustment_archive_preserves_original_receipt_across_two_mappings(
    client: TestClient,
) -> None:
    project, image_id, original = make_source(client)
    project_id = project["id"]
    saved = save_recipe(client, image_id, original)
    receipt = saved["receipt"]
    pin = {
        "recipe_id": saved["id"],
        "content_sha256": saved["content_sha256"],
        "original_sha256": receipt["original_sha256"],
        "rendition_sha256": receipt["rendition_sha256"],
    }
    payload = {
        "project_id": project_id,
        "image_ids": [image_id],
        "image_adjustment": pin,
        "receipt": receipt,
    }
    node = {
        "id": str(uuid4()),
        "node_type": "underwater_adjustment",
        "parameters_json": {"image_id": image_id, **pin},
    }
    image = client.get(f"/api/v1/images/{image_id}").json()
    rows = {
        "images": [image],
        SECTION: [{**saved, "receipt_json": receipt}],
        "workflow_node_runs": [node],
        "workflow_artifacts": [
            {
                "data_type": "adjusted_image_reference",
                "producer_node_run_id": node["id"],
                "producer_port_id": "images",
                "payload_json": payload,
                "payload_sha256": canonical_json_sha256(payload),
            }
        ],
    }
    validate_adjustment_exchange(project_id, rows, read_image=lambda _: original)
    validate_adjustment_exchange(project_id, rows, read_image=lambda _: None)
    forged = deepcopy(rows)
    forged[SECTION][0]["receipt_json"]["rgb_sha256"] = "0" * 64
    forged[SECTION][0]["content_sha256"] = canonical_json_sha256(forged[SECTION][0]["receipt_json"])
    with pytest.raises(ValidationError, match="reproduce its derived hashes"):
        validate_adjustment_exchange(project_id, forged, read_image=lambda _: original)

    swapped = deepcopy(rows)
    swapped["workflow_node_runs"][0]["parameters_json"]["image_id"] = str(uuid4())
    with pytest.raises(ValidationError, match="different original image"):
        validate_adjustment_exchange(project_id, swapped, read_image=lambda _: original)

    mappings: dict[str, str] = {}
    local_project, local_image, local_recipe = project_id, image_id, saved["id"]
    for _ in range(2):
        ids = {value: str(uuid4()) for value in (local_project, local_image, local_recipe)}
        next_project, next_image, next_recipe = (
            ids[key] for key in (local_project, local_image, local_recipe)
        )
        new_rows = deepcopy(rows)
        new_rows["images"][0].update(id=next_image, project_id=next_project)
        previous = rows[SECTION][0]
        new_recipe = new_rows[SECTION][0]
        new_recipe.update(id=next_recipe, project_id=next_project, image_id=next_image)
        new_recipe["receipt_json"] = {"invalid generic rewrite": True}
        restore_adjustment_row(SECTION, previous, new_recipe, ids)
        new_rows["workflow_node_runs"][0]["parameters_json"] = remap_adjustment_parameters(
            rows["workflow_node_runs"][0]["parameters_json"],
            ids,
        )
        restore_adjustment_row(
            "workflow_artifacts",
            rows["workflow_artifacts"][0],
            new_rows["workflow_artifacts"][0],
            ids,
        )
        mappings = {origin: ids.get(local, local) for origin, local in mappings.items()}
        for previous_id, current_id in ids.items():
            mappings.setdefault(previous_id, current_id)
        validate_adjustment_exchange(
            next_project, new_rows, origin_ids=mappings, read_image=lambda _: original
        )
        assert new_recipe["receipt_json"] == receipt
        assert new_recipe["content_sha256"] == saved["content_sha256"]
        assert new_rows["workflow_artifacts"][0]["payload_json"] == payload
        rows = new_rows
        local_project, local_image, local_recipe = next_project, next_image, next_recipe
