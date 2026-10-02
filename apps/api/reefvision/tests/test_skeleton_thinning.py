from __future__ import annotations

from fastapi.testclient import TestClient

from reefvision.services.skeleton_algorithms import (
    classify_skeleton_pixels,
    zhang_suen_thin,
)
from reefvision.services.skeletonization import _connected_components_8
from reefvision.tests.test_annotations import create_project, import_one


def _binary(
    width: int,
    height: int,
    foreground: set[tuple[int, int]],
) -> tuple[bytes, int, int]:
    data = bytearray(width * height)
    for x, y in foreground:
        data[y * width + x] = 255
    return bytes(data), width, height


def test_one_pixel_path_is_stable_and_classified_by_graph_degree() -> None:
    mask = _binary(
        7,
        5,
        {(x, 2) for x in range(1, 6)},
    )

    skeleton, iterations = zhang_suen_thin(mask)
    features = classify_skeleton_pixels(skeleton)

    assert iterations == 0
    assert skeleton == mask
    assert sum(feature.kind == "endpoint" for feature in features) == 2
    assert sum(feature.kind == "path" for feature in features) == 3
    assert sum(feature.kind == "junction" for feature in features) == 0
    assert sum(feature.kind == "isolated" for feature in features) == 0


def test_thick_bar_thins_without_breaking_eight_connected_topology() -> None:
    foreground = {
        (x, y)
        for x in range(2, 7)
        for y in range(2, 5)
    }
    mask = _binary(10, 8, foreground)

    skeleton, iterations = zhang_suen_thin(mask)
    features = classify_skeleton_pixels(skeleton)

    assert iterations >= 1
    assert 0 < len(features) < len(foreground)
    assert len(_connected_components_8(skeleton)) == 1
    assert sum(feature.kind == "endpoint" for feature in features) == 2
    assert sum(feature.kind == "junction" for feature in features) == 0


def test_raw_cross_exposes_junction_cluster_for_later_consolidation() -> None:
    foreground = {
        (3, 1),
        (3, 2),
        (3, 3),
        (3, 4),
        (3, 5),
        (1, 3),
        (2, 3),
        (4, 3),
        (5, 3),
    }
    features = classify_skeleton_pixels(_binary(7, 7, foreground))

    assert sum(feature.kind == "endpoint" for feature in features) == 4
    assert sum(feature.kind == "junction" for feature in features) > 1


def test_structure_analysis_endpoint_returns_raw_topology_checked_skeleton(
    client: TestClient,
) -> None:
    project = create_project(client, "Raw coral skeleton analysis")
    report = import_one(client, project["id"], size=(80, 60))
    image_id = report["successful"][0]["image_id"]
    class_id = project["label_classes"][0]["id"]
    mask_id = "97b877c8-eabc-4a3b-98c7-1046269e17e4"

    saved = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [],
            "mask_annotations": [
                {
                    "id": mask_id,
                    "label_class_id": class_id,
                    "geometry_kind": "polygon",
                    "points": [
                        {"x": 10, "y": 20},
                        {"x": 60, "y": 20},
                        {"x": 60, "y": 30},
                        {"x": 10, "y": 30},
                    ],
                }
            ],
        },
    )
    assert saved.status_code == 200, saved.text

    response = client.get(
        f"/api/v1/mask-annotations/{mask_id}/structure-analysis"
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_version"] == "skeleton-analysis-0001"
    assert payload["algorithm"] == "zhang_suen"
    assert payload["algorithm_version"] == "0001"
    assert payload["connectivity"] == 8
    assert payload["pre_thinning_cleanup"] == "binary_normalization_only"
    assert payload["cleanup_removed_pixels"] == 0
    assert payload["automatic_bridge_applied"] is False
    assert payload["input_foreground_pixels"] > payload["raw_skeleton_pixel_count"]
    assert payload["raw_skeleton_component_count"] == 1
    assert payload["topology_preserved"] is True
    assert payload["endpoint_count"] == 2
    assert payload["junction_pixel_count"] == 0
