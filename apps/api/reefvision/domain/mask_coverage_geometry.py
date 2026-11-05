"""Exact set operations over source-pixel half-open row runs."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

PixelRun = tuple[int, int, int]
PixelRuns = tuple[PixelRun, ...]


def _normalized(*collections: Iterable[PixelRun]) -> PixelRuns:
    by_row: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for collection in collections:
        for y, start, end in collection:
            if y < 0 or start < 0 or end <= start:
                raise ValueError("Pixel runs must be nonnegative, nonempty half-open intervals")
            by_row[y].append((start, end))
    output: list[PixelRun] = []
    for y in sorted(by_row):
        intervals = sorted(by_row[y])
        current_start, current_end = intervals[0]
        for start, end in intervals[1:]:
            if start <= current_end:
                current_end = max(current_end, end)
            else:
                output.append((y, current_start, current_end))
                current_start, current_end = start, end
        output.append((y, current_start, current_end))
    return tuple(output)


def union_runs(*collections: Iterable[PixelRun]) -> PixelRuns:
    """Return a sorted, non-overlapping union of zero or more run collections."""
    return _normalized(*collections)


def intersect_runs(left: Iterable[PixelRun], right: Iterable[PixelRun]) -> PixelRuns:
    """Return the exact shared pixels of two run collections."""
    normalized_left = _normalized(left)
    normalized_right = _normalized(right)
    output: list[PixelRun] = []
    left_index = 0
    right_index = 0
    while left_index < len(normalized_left) and right_index < len(normalized_right):
        left_y, left_start, left_end = normalized_left[left_index]
        right_y, right_start, right_end = normalized_right[right_index]
        if left_y < right_y:
            left_index += 1
            continue
        if right_y < left_y:
            right_index += 1
            continue
        start = max(left_start, right_start)
        end = min(left_end, right_end)
        if start < end:
            output.append((left_y, start, end))
        if left_end <= right_end:
            left_index += 1
        if right_end <= left_end:
            right_index += 1
    return tuple(output)


def run_area(runs: Iterable[PixelRun]) -> int:
    """Count occupied pixels after normalizing possible overlap."""
    return sum(end - start for _, start, end in _normalized(runs))
