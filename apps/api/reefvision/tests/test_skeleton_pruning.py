from reefvision.services.skeleton_algorithms import (
    classify_skeleton_pixels,
    prune_terminal_spurs,
)


def _mask(
    width: int,
    height: int,
    foreground: set[tuple[int, int]],
) -> tuple[bytes, int, int]:
    data = bytearray(width * height)
    for x, y in foreground:
        data[y * width + x] = 255
    return bytes(data), width, height


def test_zero_threshold_disables_spur_pruning() -> None:
    mask = _mask(
        11,
        11,
        {
            (x, 5) for x in range(1, 10)
        }
        | {
            (5, y) for y in range(3, 10)
        },
    )

    result = prune_terminal_spurs(mask, max_length_pixels=0)

    assert result.mask == mask
    assert result.removals == ()


def test_endpoint_to_endpoint_axis_is_never_pruned() -> None:
    mask = _mask(9, 5, {(x, 2) for x in range(1, 8)})

    result = prune_terminal_spurs(mask, max_length_pixels=100)

    assert result.removals == ()
    assert len(result.graph_nodes) == 2
    assert len(result.graph_edges) == 1


def test_short_terminal_spurs_are_removed_iteratively_with_audit() -> None:
    foreground = {
        (x, 5) for x in range(1, 10)
    } | {
        (5, 4),
        (5, 3),
        (5, 6),
        (5, 7),
    }
    mask = _mask(11, 11, foreground)

    result = prune_terminal_spurs(mask, max_length_pixels=1.0)

    assert len(result.removals) == 2
    assert [removal.iteration for removal in result.removals] == [1, 2]
    assert all(removal.branch_length_pixels == 1.0 for removal in result.removals)
    assert all(len(removal.removed_pixels) == 1 for removal in result.removals)
    assert {(removal.endpoint_x, removal.endpoint_y) for removal in result.removals} == {
        (5, 3),
        (5, 7),
    }

    final_features = classify_skeleton_pixels(result.mask)
    assert sum(feature.kind == "endpoint" for feature in final_features) == 2
    assert sum(feature.kind == "junction" for feature in final_features) == 0
    assert len(result.graph_nodes) == 2
    assert len(result.graph_edges) == 1


def test_spurs_over_threshold_are_preserved() -> None:
    foreground = {
        (x, 5) for x in range(1, 10)
    } | {
        (5, 2),
        (5, 3),
        (5, 4),
        (5, 6),
        (5, 7),
        (5, 8),
    }
    mask = _mask(11, 11, foreground)

    result = prune_terminal_spurs(mask, max_length_pixels=1.0)

    assert result.removals == ()
    assert len(result.graph_edges) == 4
