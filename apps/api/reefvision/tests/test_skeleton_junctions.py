from reefvision.services.skeleton_algorithms import (
    classify_skeleton_pixels,
    consolidate_junction_clusters,
)


def _cross_mask() -> tuple[bytes, int, int]:
    width = 7
    height = 7
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
    data = bytearray(width * height)
    for x, y in foreground:
        data[y * width + x] = 255
    return bytes(data), width, height


def test_cross_junction_pixels_collapse_to_one_graph_node() -> None:
    features = classify_skeleton_pixels(_cross_mask())

    clusters = consolidate_junction_clusters(features)

    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster.id == "junction-0001"
    assert len(cluster.pixels) == 5
    assert cluster.centroid_x == 3.0
    assert cluster.centroid_y == 3.0
    assert cluster.representative_x == 3
    assert cluster.representative_y == 3
    assert set(cluster.external_connections) == {
        (3, 1),
        (1, 3),
        (5, 3),
        (3, 5),
    }


def test_junction_ids_are_deterministic_in_image_order() -> None:
    width = 12
    height = 7
    foreground = {
        (2, 1),
        (2, 2),
        (1, 2),
        (3, 2),
        (2, 3),
        (9, 3),
        (9, 4),
        (8, 4),
        (10, 4),
        (9, 5),
    }
    data = bytearray(width * height)
    for x, y in foreground:
        data[y * width + x] = 255

    first = consolidate_junction_clusters(
        classify_skeleton_pixels((bytes(data), width, height))
    )
    second = consolidate_junction_clusters(
        classify_skeleton_pixels((bytes(data), width, height))
    )

    assert [cluster.id for cluster in first] == [
        "junction-0001",
        "junction-0002",
    ]
    assert first == second
