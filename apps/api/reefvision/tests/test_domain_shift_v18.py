from uuid import uuid4

import pytest
from pydantic import ValidationError

from reefvision.schemas.domain_shift_v18 import DomainShiftDraft
from reefvision.services.domain_shift_metrics_v18 import summarize_domain_shift


def declaration(**changes: object) -> DomainShiftDraft:
    settings = {
        "comparison_id": str(uuid4()),
        "comparison_sha256": "2" * 64,
        "reference": {"label": "Clear reference", "groups": ["A", "B", "Unobserved"]},
        "target": {"label": "Turbid target", "groups": ["C", "D", "No truth"]},
        "independent_unit": "Manually declared independent recording",
        "preprocessing": "original",
    }
    return DomainShiftDraft.model_validate({**settings, **changes})


def group(group_id: str, pairs: list[tuple[float, float]]) -> dict:
    return {
        "group_id": group_id,
        "observations": [
            {
                "media_kind": "image",
                "media_id": str(uuid4()),
                "metrics": [{"name": "matches", "unit": "count", "left": left, "right": right}],
            }
            for left, right in pairs
        ],
    }


def test_domain_shift_equal_weights_groups_and_retains_unobserved_and_unscored_units() -> None:
    no_truth = {
        "group_id": "No truth",
        "observations": [
            {
                "media_kind": "image",
                "media_id": str(uuid4()),
                "metrics": [],
                "exclusion": "Frozen image was not human reviewed",
            }
        ],
    }
    rows = [
        group("A", [(1, 2)] * 9),
        group("B", [(3, 4)]),
        group("C", [(4, 6)] * 4),
        group("D", [(8, 10)]),
        no_truth,
    ]
    report = summarize_domain_shift(declaration(), rows, "held_out")
    metric = report["metrics"][0]
    assert metric["left"]["reference_mean"] == 2
    assert metric["left"]["target_mean"] == 6
    assert metric["left"]["target_minus_reference"] == 4
    assert metric["right"]["target_minus_reference"] == 5
    assert metric["paired_gap"]["target_minus_reference"] == 1
    assert metric["left"]["se"] == pytest.approx(5**0.5)
    assert metric["left"]["ci95"] is not None
    assert metric["paired_gap"]["ci95"] is None
    states = {row["group_id"]: row["status"] for row in report["groups"]}
    assert states == {
        "A": "included",
        "B": "included",
        "C": "included",
        "D": "included",
        "Unobserved": "missing",
        "No truth": "excluded",
    }
    assert "not human reviewed" in str(report["groups"])


def test_unknown_or_overlapping_lineage_withholds_performance_and_still_shows_roster() -> None:
    rows = [group("A", [(1, 2)]), group("C", [(4, 6)])]
    for state in ("exploratory", "overlap"):
        report = summarize_domain_shift(declaration(), rows, state)
        assert report["metrics"] == []
        assert report["status"] == "withheld"
        assert len(report["groups"]) == 6
    with pytest.raises(ValidationError, match="disjoint acquisition groups"):
        declaration(target={"label": "Test", "groups": [" a "]})


def test_group_missing_a_side_never_creates_zero_or_interval() -> None:
    rows = [group("A", [(1, 2)]), group("C", [(2, 4)])]
    rows[1]["observations"][0]["metrics"][0]["right"] = None
    report = summarize_domain_shift(declaration(), rows, "held_out")
    metric = report["metrics"][0]["left"]
    assert metric["reference_mean"] == 1
    assert metric["target_mean"] is None
    assert metric["target_minus_reference"] is None
    assert metric["ci95"] is None
