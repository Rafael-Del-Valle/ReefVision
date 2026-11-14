"""Synthetic stationary fields; these do not validate ocean-model accuracy."""

import math

import pytest

from reefvision.domain.current_field import CurrentField, integrate_streamline


def uniform(east=1.0, north=0.0):
    return CurrentField(
        latitudes=(-1.0, 1.0),
        longitudes=(-1.0, 1.0),
        east=((east, east), (east, east)),
        north=((north, north), (north, north)),
    )


def test_bilinear_interpolation_and_descending_axes():
    field = CurrentField(
        latitudes=(2.0, 0.0),
        longitudes=(2.0, 0.0),
        east=((8.0, 4.0), (4.0, 0.0)),
        north=((0.0, 0.0), (0.0, 0.0)),
    )
    assert field.sample(0.5, 1.0) == pytest.approx((3.0, 0.0))


@pytest.mark.parametrize("axis", [(0.0,), (0.0, 0.0), (0.0, 2.0, 1.0), (0.0, math.nan)])
def test_invalid_axes_rejected(axis):
    with pytest.raises(ValueError):
        CurrentField(
            latitudes=axis,
            longitudes=(0.0, 1.0),
            east=((1.0, 1.0),) * len(axis),
            north=((0.0, 0.0),) * len(axis),
        )


def test_all_four_corners_required_even_at_valid_corner():
    field = CurrentField(
        latitudes=(0.0, 1.0),
        longitudes=(0.0, 1.0),
        east=((1.0, None), (1.0, 1.0)),
        north=((0.0, 0.0), (0.0, 0.0)),
    )
    assert field.sample(0.0, 0.0) is None
    assert integrate_streamline(field, 0.0, 0.0).termination == "missing_cell"


def test_no_extrapolation_and_domain_exit():
    field = uniform()
    assert field.sample(0.0, 1.00001) is None
    assert integrate_streamline(field, 0.0, 2.0).termination == "outside_domain"
    result = integrate_streamline(field, 0.0, 0.9999, step_seconds=60.0)
    assert result.termination == "outside_domain"
    assert len(result.points) == 1


@pytest.mark.parametrize("latitude,expected_lon", [(0.0, 0.0053898917), (60.0, 0.010752688)])
def test_uniform_eastward_field_uses_geographic_metre_scale(latitude, expected_lon):
    field = CurrentField(
        latitudes=(latitude - 1, latitude + 1),
        longitudes=(-1.0, 1.0),
        east=((1.0, 1.0), (1.0, 1.0)),
        north=((0.0, 0.0), (0.0, 0.0)),
    )
    result = integrate_streamline(field, latitude, 0.0, step_seconds=60.0, max_steps=10)
    assert result.termination == "max_steps"
    assert len(result.points) == 11
    assert result.points[-1].longitude == pytest.approx(expected_lon, rel=2e-4)
    assert result.points[-1].latitude == latitude
    assert result.length_m == pytest.approx(600.0)


def test_stagnation_determinism_and_length_bound():
    assert integrate_streamline(uniform(0.0), 0.0, 0.0).termination == "stagnation"
    first = integrate_streamline(uniform(), 0.0, 0.0, step_seconds=60, max_length_m=100)
    assert first == integrate_streamline(uniform(), 0.0, 0.0, step_seconds=60, max_length_m=100)
    assert first.termination == "max_length"
    assert first.length_m <= 100
    assert first.algorithm_version


@pytest.mark.parametrize(
    "kwargs",
    [
        {"step_seconds": math.inf},
        {"max_steps": 0},
        {"max_length_m": -1},
        {"stagnation_m_s": math.nan},
    ],
)
def test_invalid_integration_limits_rejected(kwargs):
    with pytest.raises(ValueError):
        integrate_streamline(uniform(), 0.0, 0.0, **kwargs)


def test_rk4_cannot_jump_across_missing_cells():
    # A long eastward step would sample at 0, 2, 2, 4 degrees and miss the hole.
    field = CurrentField(
        latitudes=(-1.0, 1.0),
        longitudes=(0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0),
        east=((445277.963, 445277.963, None, 445277.963, 445277.963, 445277.963, 445277.963),) * 2,
        north=((0.0,) * 7,) * 2,
    )
    result = integrate_streamline(field, 0.0, 0.0, step_seconds=1, max_steps=1, max_length_m=1e6)
    assert result.points[-1].longitude < 0.5
    assert result.length_m < 60000


def test_uniform_northward_field_uses_meridional_radius():
    result = integrate_streamline(uniform(0.0, 1.0), 0.0, 0.0, step_seconds=60, max_steps=10)
    assert result.points[-1].latitude == pytest.approx(0.0054262169, rel=1e-7)
    assert result.points[-1].longitude == 0


@pytest.mark.parametrize("east", [((1.0,), (1.0,)), ((math.inf, 1.0), (1.0, 1.0))])
def test_invalid_component_shape_or_nonfinite_value_rejected(east):
    with pytest.raises(ValueError):
        CurrentField(
            latitudes=(0.0, 1.0), longitudes=(0.0, 1.0), east=east, north=((0.0, 0.0), (0.0, 0.0))
        )


def test_polar_limit_is_explicit_and_invalid_seed_rejected():
    field = CurrentField(
        latitudes=(84.0, 86.0),
        longitudes=(-1.0, 1.0),
        east=((1.0, 1.0),) * 2,
        north=((0.0, 0.0),) * 2,
    )
    assert integrate_streamline(field, 85.0, 0.0).termination == "polar_limit"
    with pytest.raises(ValueError):
        integrate_streamline(field, math.nan, 0.0)


@pytest.mark.parametrize("longitudes", [(-179.0, 179.0), (179.0, -179.0)])
def test_dateline_grid_rejected_before_false_global_interpolation(longitudes):
    # A local current slice straddling 180 degrees cannot be interpolated
    # across 358 degrees while longitude unwrapping remains unsupported.
    with pytest.raises(ValueError, match="longitude gap exceeds 180 degrees"):
        CurrentField(
            latitudes=(-1.0, 1.0),
            longitudes=longitudes,
            east=((1.0, 1.0), (1.0, 1.0)),
            north=((0.0, 0.0), (0.0, 0.0)),
        )
