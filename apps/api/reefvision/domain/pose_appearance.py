"""Operating points and open-set retrieval for the native appearance descriptor."""

import math
from collections.abc import Iterable
from typing import TypedDict


class Ranking(TypedDict):
    state: str
    selected: str | None
    best_score: float | None
    margin: float | None
    candidates: list[tuple[str, float]]


def calibration(genuine: list[float], impostor: list[float], maximum_false_rate: float) -> float:
    """Maximize development true accepts under the declared impostor-pair limit."""
    if not genuine or not impostor or not 0 <= maximum_false_rate <= 1:
        raise ValueError("Calibration requires genuine and impostor development pairs")
    if any(not math.isfinite(s) or abs(s) > 1 for s in (*genuine, *impostor)):
        raise ValueError("Appearance scores must be finite cosine similarities")
    # An operating point just above a tie rejects the entire tied group; values above
    # one represent a valid abstain-all calibration when evidence is inseparable.
    ordered = sorted(impostor, reverse=True)
    allowed = math.floor(len(ordered) * maximum_false_rate)
    return -1.0 if allowed == len(ordered) else math.nextafter(ordered[allowed], math.inf)


def rank(candidates: list[tuple[str, float]], threshold: float, minimum_margin: float) -> Ranking:
    ordered = sorted(candidates, key=lambda item: (-item[1], item[0]))
    best = ordered[0][1] if ordered else None
    margin = best - ordered[1][1] if best is not None and len(ordered) > 1 else None
    state = "proposed"
    if best is None or best < threshold:
        state = "abstained"
    elif margin is not None and (margin == 0 or margin < minimum_margin):
        state = "ambiguous"
    return {
        "state": state,
        "selected": ordered[0][0] if state == "proposed" else None,
        "best_score": best,
        "margin": margin,
        "candidates": ordered,
    }


def rates(rows: Iterable[tuple[set[str], set[str], str | None]]) -> dict[str, float | int | None]:
    genuine = impostor = missed = false = probes = selected_count = 0
    for truth, eligible, selected in rows:
        probes += 1
        genuine += len(truth)
        impostor += len(eligible - truth)
        missed += len(truth) - int(selected in truth)
        false += int(selected is not None and selected not in truth)
        selected_count += int(selected is not None)
    return {
        "probes": probes,
        "proposed": selected_count,
        "genuine_pairs": genuine,
        "impostor_pairs": impostor,
        "false_links": false,
        "missed_links": missed,
        "false_match_rate": false / impostor if impostor else None,
        "missed_match_rate": missed / genuine if genuine else None,
        "incorrect_proposal_fraction": false / selected_count if selected_count else None,
    }
