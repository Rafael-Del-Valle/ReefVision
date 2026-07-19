from __future__ import annotations

from reefvision.ml.active_learning_selection import (
    SelectionCandidate,
    select_candidates,
)


def _candidates() -> list[SelectionCandidate]:
    return [
        SelectionCandidate(
            candidate_id="a",
            embedding=(1.0, 0.0),
            probabilities=(0.5, 0.5),
            ensemble_probabilities=((0.9, 0.1), (0.1, 0.9)),
            group_id="fragment-1",
        ),
        SelectionCandidate(
            candidate_id="b",
            embedding=(0.99, 0.01),
            probabilities=(0.95, 0.05),
            ensemble_probabilities=((0.9, 0.1), (0.85, 0.15)),
            group_id="fragment-1",
        ),
        SelectionCandidate(
            candidate_id="c",
            embedding=(0.0, 1.0),
            probabilities=(0.55, 0.45),
            ensemble_probabilities=((0.8, 0.2), (0.2, 0.8)),
            group_id="fragment-2",
        ),
        SelectionCandidate(
            candidate_id="d",
            embedding=(-1.0, 0.0),
            probabilities=(0.7, 0.3),
            group_id="fragment-3",
        ),
    ]


def test_k_center_is_deterministic_diverse_and_respects_groups() -> None:
    first = select_candidates(
        _candidates(),
        budget=3,
        strategy="k_center",
        seed=7,
        group_limit=1,
    )
    second = select_candidates(
        _candidates(),
        budget=3,
        strategy="k_center",
        seed=7,
        group_limit=1,
    )
    assert [item.candidate_id for item in first] == [item.candidate_id for item in second]
    assert len(first) == 3
    assert len({item.group_id for item in first}) == 3
    assert all(item.score >= 0 for item in first)
    assert all(item.explanation for item in first)


def test_ensemble_disagreement_prioritizes_conflicting_models() -> None:
    selected = select_candidates(
        _candidates(),
        budget=2,
        strategy="ensemble_disagreement",
    )
    assert selected[0].candidate_id in {"a", "c"}
    assert selected[0].disagreement >= selected[1].disagreement
