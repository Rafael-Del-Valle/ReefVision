"""Synthetic label classes used only by ReefVision tests.

These are deliberately not a product project template. Production projects
start with a blank class list; tests that exercise annotation/class behavior
seed the labels they need through the public Classes API.
"""

from __future__ import annotations

from typing import Any, cast

from fastapi.testclient import TestClient

SYNTHETIC_LABEL_CLASSES: tuple[dict[str, object], ...] = (
    {
        "class_index": 0,
        "name": "Muricea Closed",
        "scientific_name": "Muricea pendula",
        "state_name": "Closed",
        "display_color": "#E76F51",
    },
    {
        "class_index": 1,
        "name": "Thesea Closed",
        "scientific_name": "Thesea nivea",
        "state_name": "Closed",
        "display_color": "#F4A261",
    },
    {
        "class_index": 2,
        "name": "Muricea Open",
        "scientific_name": "Muricea pendula",
        "state_name": "Open",
        "display_color": "#E9C46A",
    },
    {
        "class_index": 3,
        "name": "Swiftia Open",
        "scientific_name": "Swiftia exserta",
        "state_name": "Open",
        "display_color": "#2A9D8F",
    },
    {
        "class_index": 4,
        "name": "Swiftia Closed",
        "scientific_name": "Swiftia exserta",
        "state_name": "Closed",
        "display_color": "#457B9D",
    },
    {
        "class_index": 5,
        "name": "Thesea Open",
        "scientific_name": "Thesea nivea",
        "state_name": "Open",
        "display_color": "#9B5DE5",
    },
)


def seed_synthetic_label_classes(
    client: TestClient,
    project: dict[str, Any],
) -> dict[str, Any]:
    for display_order, item in enumerate(SYNTHETIC_LABEL_CLASSES):
        response = client.post(
            f"/api/v1/projects/{project['id']}/classes",
            json={
                "class_index": item["class_index"],
                "display_order": display_order,
                "name": item["name"],
                "scientific_name": item["scientific_name"],
                "state_name": item["state_name"],
                "display_color": item["display_color"],
            },
        )

        assert response.status_code == 201, response.text

    refreshed = client.get(f"/api/v1/projects/{project['id']}")

    assert refreshed.status_code == 200, refreshed.text

    return cast(
        dict[str, Any],
        refreshed.json(),
    )
