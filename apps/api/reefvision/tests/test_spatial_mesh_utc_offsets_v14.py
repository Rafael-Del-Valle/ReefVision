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
    ["2026-10-01T12:00:00+01:00", "2026-10-01T12:00:00-05:00"],
)
def test_longitudinal_replay_rejects_non_utc_offsets(invalid_timestamp: str) -> None:
    before = _preview("survey-1", "2026-10-01T12:00:00Z")
    after = _preview("survey-2", "2026-10-02T12:00:00Z")
    before["provenance"]["observed_at_utc"] = invalid_timestamp
    with pytest.raises(ValueError, match="timezone-aware increasing timestamps"):
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
    with pytest.raises(ValueError, match="timezone-aware increasing timestamps"):
        compare_mesh_observations(before, after)
