"""Half-open time intervals on the reviewed hydrophone's sample clock."""

from collections.abc import Sequence
from typing import Any


def classify_window(
    window: tuple[int, int], events: list[tuple[int, int, str]], uncertainty: int, duration: int
) -> str:
    start, end = window
    earliest, latest = start - uncertainty, end + uncertainty
    if earliest < 0 or latest > duration:
        return "outside reviewed recording"
    overlapping = [
        (a, b, state)
        for a, b, state in events
        if a < latest and earliest < b and state != "dismissed"
    ]
    if any(state != "accepted" for _, _, state in overlapping):
        return "unresolved event review"
    if not overlapping:
        return "outside reviewed events"
    if any(a <= earliest and latest <= b for a, b, _ in overlapping):
        return "inside accepted event"
    return "uncertain event boundary"


def paired_difference(rows: Sequence[dict[str, Any]]) -> float | None:
    exposed = [row["roi_mean"] for row in rows if row["exposure"] == "inside accepted event"]
    control = [row["roi_mean"] for row in rows if row["exposure"] == "outside reviewed events"]
    if len(exposed) != 1 or len(control) != 1 or exposed[0] is None or control[0] is None:
        return None
    return float(exposed[0]) - float(control[0])
