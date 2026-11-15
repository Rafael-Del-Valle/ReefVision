from reefvision.domain.mask_coverage_geometry import (
    intersect_runs,
    run_area,
    union_runs,
)


def test_union_merges_overlap_without_double_counting() -> None:
    first = ((0, 1, 5), (1, 1, 3))
    second = ((0, 3, 7), (2, 0, 2))

    merged = union_runs(first, second)

    assert merged == ((0, 1, 7), (1, 1, 3), (2, 0, 2))
    assert run_area(first) == 6
    assert run_area(second) == 6
    assert run_area(merged) == 10


def test_intersection_retains_only_shared_pixels() -> None:
    target = ((0, 0, 6), (1, 1, 5), (3, 0, 2))
    roi = ((0, 2, 4), (1, 0, 3), (2, 0, 9))

    overlap = intersect_runs(target, roi)

    assert overlap == ((0, 2, 4), (1, 1, 3))
    assert run_area(overlap) == 4


def test_empty_union_and_intersection_are_explicit_zero() -> None:
    assert union_runs() == ()
    assert union_runs((), ()) == ()
    assert intersect_runs((), ((0, 1, 2),)) == ()
    assert run_area(()) == 0
