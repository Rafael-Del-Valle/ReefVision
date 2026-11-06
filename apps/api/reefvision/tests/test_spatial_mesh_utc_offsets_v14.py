"""UTC evidence integrity for provisional longitudinal coral comparisons."""

import pytest

from reefvision.schemas.spatial_mesh_preview_v14 import MeshPreviewRequest
from reefvision.services.spatial_mesh_longitudinal_v14 import compare_mesh_observations
from reefvision.services.spatial_mesh_surface_v14 import preview_from_request


def _preview(observation_id: str, timestamp: str) -> dict:
    request = MeshPreviewRequest(
        vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]],
        faces=[[0, 1, 2]],
        meters_per_unit=1,
        calibration_method="ruler",
        calibration_evidence="Unreviewed field ruler",
        relative_scale_uncertainty=0.1,
        specimen_id="colony-16",
        observation_id=observation_id,
        observed_at_utc=timestamp,
    )
    result = preview_from_request(request)
    result["project_id"] = "project-1"
    return result


@pytest.mark.parametrize(
    "invalid_timestamp",
    [
        "2026-10-01T12:00:00+01:00",
        "2026-10-01T12:00:00-05:00",
        "2026-10-01T12:00:00+00:00:01",
        "2026-10-01T12:00:00-00:00:01",
    ],
)
def test_longitudinal_replay_rejects_non_utc_offsets(invalid_timestamp: str) -> None:
    before = _preview("survey-1", "2026-10-01T12:00:00Z")
    after = _preview("survey-2", "2026-10-02T12:00:00Z")
    before["provenance"]["observed_at_utc"] = invalid_timestamp
    with pytest.raises(ValueError, match="timestamps"):
        compare_mesh_observations(before, after)


def test_longitudinal_replay_accepts_explicit_zero_utc_offset() -> None:
    before = _preview("survey-1", "2026-10-01T12:00:00Z")
    after = _preview("survey-2", "2026-10-02T12:00:00Z")
    before["provenance"]["observed_at_utc"] = "2026-10-01T12:00:00+00:00"
    assert compare_mesh_observations(before, after)["elapsed_days"] == pytest.approx(1)


@pytest.mark.parametrize("observation", ["before", "after"])
@pytest.mark.parametrize(
    "invalid_timestamp",
    [
        "2026-10-01T12:00:00+01:00",
        "2026-10-01T12:00:00-05:00",
        "2026-10-01T12:00:00",
    ],
)
def test_longitudinal_replay_rejects_invalid_utc_on_either_observation(
    observation: str, invalid_timestamp: str
) -> None:
    before = _preview("survey-1", "2026-10-01T12:00:00Z")
    after = _preview("survey-2", "2026-10-02T12:00:00Z")
    target = before if observation == "before" else after
    target["provenance"]["observed_at_utc"] = invalid_timestamp
    with pytest.raises(ValueError, match="timestamps"):
        compare_mesh_observations(before, after)


@pytest.mark.parametrize(
    ("later_timestamp", "expected_elapsed_days"),
    [
        ("2026-10-01T12:00:00Z", None),
        ("2026-09-30T12:00:00Z", None),
        ("2026-10-02T12:00:00+00:00", 1.0),
    ],
)
def test_longitudinal_replay_requires_forward_time_without_mutating_sources(
    later_timestamp: str, expected_elapsed_days: float | None
) -> None:
    """Temporal QC must not rewrite source evidence on rejection or success."""
    from copy import deepcopy

    before = _preview("survey-1", "2026-10-01T12:00:00Z")
    after = _preview("survey-2", later_timestamp)
    original_before = deepcopy(before)
    original_after = deepcopy(after)
    if expected_elapsed_days is None:
        with pytest.raises(ValueError, match="timestamps"):
            compare_mesh_observations(before, after)
    else:
        comparison = compare_mesh_observations(before, after)
        assert comparison["elapsed_days"] == pytest.approx(expected_elapsed_days)
    assert before == original_before
    assert after == original_after


@pytest.mark.parametrize("observation", ["before", "after"])
def test_unknown_rfc3339_zero_offset_is_not_verified_utc(observation: str) -> None:
    """RFC 3339 -00:00 marks unknown offset, despite datetime normalization."""
    from copy import deepcopy

    before = _preview("survey-1", "2026-10-01T12:00:00Z")
    after = _preview("survey-2", "2026-10-02T12:00:00Z")
    target = before if observation == "before" else after
    target["provenance"]["observed_at_utc"] = (
        "2026-10-01T12:00:00-00:00" if observation == "before" else "2026-10-02T12:00:00-00:00"
    )
    original_before, original_after = deepcopy(before), deepcopy(after)
    with pytest.raises(ValueError, match="explicit RFC 3339 UTC timestamps"):
        compare_mesh_observations(before, after)
    assert before == original_before
    assert after == original_after


@pytest.mark.parametrize(
    "invalid_timestamp",
    [
        "2026-10-01 12:00:00+00:00",
        "2026-10-01T12:00:00+0000",
        "2026-W40-4T12:00:00Z",
        "2026-10-01T12:00:00+00:00:00",
        "2026-10-01T12:00:00z",
    ],
)
@pytest.mark.parametrize("observation", ["before", "after"])
def test_longitudinal_replay_rejects_non_rfc3339_utc_evidence(
    invalid_timestamp: str, observation: str
) -> None:
    """Permissive Python datetime parsing must not certify replayed timestamps."""
    from copy import deepcopy

    before = _preview("survey-1", "2026-10-01T12:00:00Z")
    after = _preview("survey-2", "2026-10-02T12:00:00Z")
    target = before if observation == "before" else after
    target["provenance"]["observed_at_utc"] = invalid_timestamp
    originals = (deepcopy(before), deepcopy(after))
    with pytest.raises(ValueError, match="explicit RFC 3339 UTC timestamps"):
        compare_mesh_observations(before, after)
    assert (before, after) == originals


@pytest.mark.parametrize(
    ("earlier", "later", "expected_days"),
    [
        ("2024-02-28T12:00:00Z", "2024-03-01T12:00:00Z", 2.0),
        ("2026-10-01T12:00:00.000000Z", "2026-10-02T12:00:00.000000+00:00", 1.0),
        ("2026-10-01T12:00:00.500Z", "2026-10-02T12:00:00.500Z", 1.0),
    ],
)
def test_longitudinal_valid_utc_calendar_and_fractional_precision(
    earlier: str, later: str, expected_days: float
) -> None:
    """Valid UTC representations preserve elapsed-time science and source records."""
    from copy import deepcopy

    before = _preview("survey-1", "2026-10-01T12:00:00Z")
    after = _preview("survey-2", "2026-10-02T12:00:00Z")
    before["provenance"]["observed_at_utc"] = earlier
    after["provenance"]["observed_at_utc"] = later
    originals = (deepcopy(before), deepcopy(after))
    comparison = compare_mesh_observations(before, after)
    assert comparison["elapsed_days"] == pytest.approx(expected_days)
    assert (before, after) == originals


@pytest.mark.parametrize("observation", ["before", "after"])
@pytest.mark.parametrize(
    "fraction",
    ["1234567", "0000001", "999999999"],
)
def test_longitudinal_replay_rejects_silently_truncated_submicrosecond_time(
    observation: str, fraction: str
) -> None:
    """Python datetime truncates beyond six digits; never lose source precision."""
    from copy import deepcopy

    before = _preview("survey-1", "2026-10-01T12:00:00Z")
    after = _preview("survey-2", "2026-10-02T12:00:00Z")
    target = before if observation == "before" else after
    date = "2026-10-01" if observation == "before" else "2026-10-02"
    target["provenance"]["observed_at_utc"] = f"{date}T12:00:00.{fraction}Z"
    originals = (deepcopy(before), deepcopy(after))
    with pytest.raises(ValueError, match="explicit RFC 3339 UTC timestamps"):
        compare_mesh_observations(before, after)
    assert (before, after) == originals


@pytest.mark.parametrize(
    ("earlier", "later", "expected_microseconds"),
    [
        ("2026-10-01T12:00:00.000000Z", "2026-10-01T12:00:00.000001Z", 1),
        ("2026-10-01T12:00:00.999999Z", "2026-10-01T12:00:01.000000Z", 1),
        ("2026-10-01T23:59:59.999999Z", "2026-10-02T00:00:00Z", 1),
    ],
)
def test_longitudinal_preserves_supported_microsecond_elapsed_time(
    earlier: str, later: str, expected_microseconds: int
) -> None:
    """Distinct valid observations must not collapse at second boundaries."""
    from copy import deepcopy

    before = _preview("survey-1", "2026-10-01T12:00:00Z")
    after = _preview("survey-2", "2026-10-02T12:00:00Z")
    before["provenance"]["observed_at_utc"] = earlier
    after["provenance"]["observed_at_utc"] = later
    originals = (deepcopy(before), deepcopy(after))
    comparison = compare_mesh_observations(before, after)
    assert comparison["elapsed_days"] == pytest.approx(
        expected_microseconds / 86_400_000_000, rel=1e-9, abs=1e-16
    )
    assert (before, after) == originals
