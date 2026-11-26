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


@pytest.mark.parametrize(
    "longitudes",
    [(-170.0, 0.0, 170.0), (170.0, 0.0, -170.0)],
)
def test_domain_rejects_wide_multicolumn_current_field_without_adjacent_gap(longitudes):
    """Direct domain callers must not interpolate a false 340-degree ocean cell.

    Every adjacent spacing is only 170 degrees, so checking gaps alone misses
    this scientifically invalid domain. The service also guards this case,
    but the public interpolation kernel must independently refuse it.
    """
    with pytest.raises(ValueError, match="longitude extent exceeds 180 degrees"):
        CurrentField(
            latitudes=(-1.0, 1.0),
            longitudes=longitudes,
            east=((1.0, 1.0, 1.0), (1.0, 1.0, 1.0)),
            north=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
        )


@pytest.mark.parametrize("invalid", ["1.0", None, 1j, 10**500])
def test_untrusted_numeric_inputs_fail_scientific_qc_without_runtime_type_errors(invalid):
    """Malformed saved graphs must fail closed, not crash numeric validation.

    This rejects strings, complex scalars and overflowing integers while
    preserving explicit missing (None) current components as masked cells.
    """
    with pytest.raises(ValueError, match="Axes require"):
        CurrentField(
            latitudes=(0.0, invalid),
            longitudes=(0.0, 1.0),
            east=((1.0, 1.0), (1.0, 1.0)),
            north=((0.0, 0.0), (0.0, 0.0)),
        )
    components = ((invalid, 1.0), (1.0, 1.0))
    if invalid is None:
        # Explicit None is a documented missing-current mask, not a numeric
        # measurement. No velocity may be fabricated from the other corners.
        field = CurrentField(
            latitudes=(0.0, 1.0),
            longitudes=(0.0, 1.0),
            east=components,
            north=((0.0, 0.0), (0.0, 0.0)),
        )
        assert field.sample(0.0, 0.0) is None
        assert integrate_streamline(field, 0.0, 0.0).termination == "missing_cell"
    else:
        with pytest.raises(ValueError, match="Component values must be finite"):
            CurrentField(
                latitudes=(0.0, 1.0),
                longitudes=(0.0, 1.0),
                east=components,
                north=((0.0, 0.0), (0.0, 0.0)),
            )
    with pytest.raises(ValueError, match="Seed must be finite"):
        integrate_streamline(uniform(), invalid, 0.0)
    with pytest.raises(ValueError, match="Integration limits must be finite"):
        integrate_streamline(uniform(), 0.0, 0.0, step_seconds=invalid)


@pytest.mark.parametrize("east,north", [(500.0, -200.0), (0.0, 0.0), (None, None)])
def test_reused_field_preserves_independent_seed_and_step_limits(east, north):
    field = uniform(east, north)
    for latitude, longitude, step in ((0.0, 0.0, 3600), (0.2, -0.3, 1), (0.0, 0.0, 60)):
        reused = integrate_streamline(
            field, latitude, longitude, step_seconds=step, max_steps=2, max_length_m=1e6
        )
        independent = integrate_streamline(
            uniform(east, north),
            latitude,
            longitude,
            step_seconds=step,
            max_steps=2,
            max_length_m=1e6,
        )
        assert reused == independent
        if east is None:
            assert reused.termination == "missing_cell"
        elif east == 0.0:
            assert reused.termination == "stagnation"
        else:
            assert reused.termination == "max_steps"
            assert reused.length_m <= 2 * step * math.hypot(east, north)


def test_stationary_rk4_reuses_accepted_endpoint_without_resampling(monkeypatch):
    """One initial sample and four per accepted step, even in a nonuniform field."""
    field = CurrentField(
        latitudes=(-1.0, 1.0),
        longitudes=(-1.0, 1.0),
        east=((0.5, 2.0), (1.0, 3.0)),
        north=((0.2, 0.4), (0.6, 0.8)),
    )
    sample = CurrentField.sample
    calls = []

    def counted_sample(self, latitude, longitude):
        calls.append((latitude, longitude))
        return sample(self, latitude, longitude)

    monkeypatch.setattr(CurrentField, "sample", counted_sample)
    result = integrate_streamline(field, 0.0, 0.0, step_seconds=60, max_steps=10)
    assert result.termination == "max_steps"
    assert len(result.points) == 11
    assert len(calls) == 41
    for point in result.points:
        velocity = sample(field, point.latitude, point.longitude)
        assert velocity is not None
        assert point.speed_m_s == math.hypot(*velocity)
    assert result.points[-1].longitude > 0
    assert result.points[-1].latitude > 0


def test_affine_equatorial_current_matches_analytic_solution():
    """An independent closed-form reference for stationary RK4 integration."""
    # At the equator, east = 2 + longitude (m/s), north = 0.
    # WGS84 gives d(longitude)/dt = (2 + longitude) / metres_per_degree.
    field = CurrentField(
        latitudes=(-1.0, 1.0),
        longitudes=(-1.0, 1.0),
        east=((1.0, 3.0), (1.0, 3.0)),
        north=((0.0, 0.0), (0.0, 0.0)),
    )
    metres_per_degree = 6378137.0 * math.pi / 180
    duration = 36000
    expected_lon = 2 * math.expm1(duration / metres_per_degree)
    errors = []
    for step in (3600, 600):
        result = integrate_streamline(
            field, 0.0, 0.0, step_seconds=step, max_steps=duration // step
        )
        assert result.termination == "max_steps"
        assert len(result.points) == duration // step + 1
        assert all(point.latitude == 0.0 for point in result.points)
        endpoint = result.points[-1]
        assert endpoint.longitude == pytest.approx(expected_lon, abs=1e-7, rel=0)
        assert endpoint.speed_m_s == pytest.approx(2 + endpoint.longitude)
        assert result.length_m == pytest.approx(
            endpoint.longitude * metres_per_degree, abs=1e-5, rel=0
        )
        errors.append(abs(endpoint.longitude - expected_lon))
    # A smaller integration step must improve accuracy in this smooth field.
    assert errors[1] < errors[0]


@pytest.mark.parametrize("reverse_lat,reverse_lon", [(True, False), (False, True), (True, True)])
def test_nonuniform_current_axis_order_preserves_signed_flow_and_missing_mask(
    reverse_lat, reverse_lon
):
    """Provider grid storage order must not change scientific integration."""
    latitudes = (-1.0, 0.0, 2.0)
    longitudes = (-2.0, 0.0, 1.0)
    east = ((-2.0, -1.0, -0.5), (-3.0, -2.0, -1.0), (-4.0, -3.0, None))
    north = ((0.5, 1.0, 2.0), (1.0, 2.0, 3.0), (2.0, 3.0, 4.0))
    reference = CurrentField(latitudes, longitudes, east, north)

    def reorder(matrix):
        rows = matrix[::-1] if reverse_lat else matrix
        return tuple(row[::-1] for row in rows) if reverse_lon else rows

    reordered = CurrentField(
        latitudes[::-1] if reverse_lat else latitudes,
        longitudes[::-1] if reverse_lon else longitudes,
        reorder(east),
        reorder(north),
    )
    # The signed vector is an independently calculated bilinear midpoint.
    assert reordered.sample(-0.5, -1.0) == pytest.approx((-2.0, 1.125))
    assert reordered.sample(1.0, 0.5) is None
    assert integrate_streamline(reordered, 1.0, 0.5).termination == "missing_cell"

    expected = integrate_streamline(reference, -0.5, -1.0, step_seconds=60, max_steps=10)
    actual = integrate_streamline(reordered, -0.5, -1.0, step_seconds=60, max_steps=10)
    assert actual == expected
    assert actual.termination == "max_steps"
    assert len(actual.points) == 11
    assert actual.points[-1].longitude < -1.0
    assert actual.points[-1].latitude > -0.5
