"""Synthetic Copernicus fixtures; no credentials or live observations are required."""

import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest
import xarray as xr
from pydantic import ValidationError as SchemaError

from reefvision.domain.errors import ValidationError
from reefvision.schemas.copernicus import CopernicusRequest
from reefvision.schemas.environmental_context import EnvironmentalLookup
from reefvision.services.copernicus_environment import CopernicusEnvironmentService
from reefvision.services.copernicus_worker import read_dataset
from reefvision.tests.test_annotations import create_project


def request(**overrides):
    return CopernicusRequest(
        dataset_id="cmems_mod_synthetic_test",
        dataset_version="202601",
        minimum_longitude=-80,
        maximum_longitude=-79,
        minimum_latitude=32,
        maximum_latitude=33,
        start_datetime="2026-04-03T00:00:00Z",
        end_datetime="2026-04-03T01:00:00Z",
        minimum_depth=0,
        maximum_depth=10,
        **overrides,
    )


def dataset():
    dims = ("time", "depth", "latitude", "longitude")
    return xr.Dataset(
        {
            "uo": (
                dims,
                np.array([[[[3.0]]]]),
                {"units": "m s-1", "standard_name": "eastward_sea_water_velocity"},
            ),
            "vo": (
                dims,
                np.array([[[[4.0]]]]),
                {"units": "m s-1", "standard_name": "northward_sea_water_velocity"},
            ),
            "thetao": (
                dims,
                np.array([[[[20.0]]]]),
                {"units": "degrees_C", "standard_name": "sea_water_potential_temperature"},
            ),
            "so": (
                dims,
                np.array([[[[35.0]]]]),
                {"units": "PSU", "standard_name": "sea_water_practical_salinity"},
            ),
        },
        coords={
            "time": np.array(["2026-04-03T00:00:00"], dtype="datetime64[ns]"),
            "depth": [5.0],
            "latitude": [32.5],
            "longitude": [-79.5],
        },
        attrs={"title": "SYNTHETIC fixture, not real ocean data"},
    )


def raw_fixture(monkeypatch):
    def open_dataset(**kwargs):
        assert kwargs["coordinates_selection_method"] == "strict-inside"
        assert kwargs["dataset_version"] == "202601"
        assert kwargs["minimum_longitude"] == -80
        assert kwargs["maximum_depth"] == 10
        return dataset()

    monkeypatch.setitem(
        sys.modules,
        "copernicusmarine",
        SimpleNamespace(open_dataset=open_dataset, __version__="synthetic-test"),
    )
    return read_dataset(
        request().model_dump(mode="json", exclude={"offline", "refresh"}),
        "fixture-user",
        "fixture-password",
    )


def test_copernicus_worker_uses_bounded_pinned_requests_and_preserves_grid_metadata(monkeypatch):
    raw = raw_fixture(monkeypatch)
    assert len(raw["samples"]) == 4
    assert raw["samples"][0]["longitude"] == -79.5
    assert raw["samples"][0]["depth_m"] == 5
    assert "fixture-password" not in str(raw)
    assert raw["dataset_metadata"]["title"].startswith("SYNTHETIC")


@pytest.mark.parametrize("invalid_provider_value", [False, True])
def test_worker_closes_original_provider_dataset_after_subset_load(
    monkeypatch, invalid_provider_value
):
    """Loading an xarray variable subset must not orphan the provider's close handle."""
    original = dataset()
    closed = []
    original.set_close(lambda: closed.append("provider"))
    if invalid_provider_value:
        # This fails *after* selecting and loading the subset, so cleanup must
        # also work when a remote dataset returns an unusable value.
        original["uo"].values[0, 0, 0, 0] = np.inf

    def open_dataset(**_kwargs):
        return original

    monkeypatch.setitem(
        sys.modules,
        "copernicusmarine",
        SimpleNamespace(open_dataset=open_dataset, __version__="synthetic-test"),
    )
    payload = request().model_dump(mode="json", exclude={"offline", "refresh"})
    if invalid_provider_value:
        with pytest.raises(ValueError, match="Infinite provider value"):
            read_dataset(payload, "fixture-user", "fixture-password")
    else:
        result = read_dataset(payload, "fixture-user", "fixture-password")
        assert len(result["samples"]) == 4
    assert closed == ["provider"]


@pytest.mark.parametrize("value", [True, 3 + 2j, "3.0"])
def test_worker_rejects_nonphysical_measurement_types(monkeypatch, value):
    original = dataset()
    original["uo"] = original["uo"].copy(data=np.full(original["uo"].shape, value))
    closed = []
    original.set_close(lambda: closed.append("provider"))
    monkeypatch.setitem(
        sys.modules,
        "copernicusmarine",
        SimpleNamespace(open_dataset=lambda **_kwargs: original, __version__="synthetic-test"),
    )
    payload = request().model_dump(mode="json", exclude={"offline", "refresh"})
    with pytest.raises(ValueError, match="measurements must be real numbers"):
        read_dataset(payload, "fixture-user", "fixture-password")
    assert closed == ["provider"]


@pytest.mark.parametrize("axis", ["time", "depth", "latitude", "longitude"])
def test_worker_rejects_implicit_dimension_coordinates(monkeypatch, axis):
    """Dimension names alone do not establish physical grid coordinates."""
    original = dataset().drop_vars(axis)
    assert axis in original.dims
    assert axis not in original.coords
    closed = []
    original.set_close(lambda: closed.append("provider"))

    def open_dataset(**_kwargs):
        return original

    monkeypatch.setitem(
        sys.modules,
        "copernicusmarine",
        SimpleNamespace(open_dataset=open_dataset, __version__="synthetic-test"),
    )
    payload = request().model_dump(mode="json", exclude={"offline", "refresh"})
    with pytest.raises(ValueError, match="Explicit one-dimensional"):
        read_dataset(payload, "fixture-user", "fixture-password")
    assert closed == ["provider"]


@pytest.mark.parametrize(
    ("axis", "coordinates", "message"),
    [
        ("latitude", [True, False, True], "spatial coordinates must be real"),
        ("depth", [1 + 2j, 5 + 2j, 9 + 2j], "spatial coordinates must be real"),
        ("time", [0, 1, 2], "time coordinates must be decoded"),
        ("latitude", [32.25, 32.25, 32.75], "strictly monotonic"),
        ("latitude", [32.25, 32.75, 32.25], "strictly monotonic"),
        ("latitude", [32.25, np.nan, 32.75], "Non-finite"),
        ("depth", [1.0, 5.0, np.inf], "Non-finite"),
        (
            "time",
            np.array(["2026-04-03T00:00:00", "NaT", "2026-04-03T01:00:00"], dtype="datetime64[ns]"),
            "Non-finite",
        ),
    ],
)
def test_worker_rejects_nonphysical_grid_axes(monkeypatch, axis, coordinates, message):
    original = dataset().isel({axis: [0, 0, 0]}).assign_coords({axis: coordinates})
    closed = []
    original.set_close(lambda: closed.append("provider"))
    monkeypatch.setitem(
        sys.modules,
        "copernicusmarine",
        SimpleNamespace(open_dataset=lambda **_kwargs: original, __version__="synthetic-test"),
    )
    payload = request().model_dump(mode="json", exclude={"offline", "refresh"})
    with pytest.raises(ValueError, match=message):
        read_dataset(payload, "fixture-user", "fixture-password")
    assert closed == ["provider"]


@pytest.mark.parametrize(
    ("latitudes", "resolution"),
    [([32.75, 32.5, 32.25], 0.25), ([32.25, 32.5, 33.0], None)],
)
def test_worker_accepts_descending_and_irregular_monotonic_axes(monkeypatch, latitudes, resolution):
    original = dataset().isel(latitude=[0, 0, 0]).assign_coords(latitude=latitudes)
    monkeypatch.setitem(
        sys.modules,
        "copernicusmarine",
        SimpleNamespace(open_dataset=lambda **_kwargs: original, __version__="synthetic-test"),
    )
    payload = request().model_dump(mode="json", exclude={"offline", "refresh"})
    result = read_dataset(payload, "fixture-user", "fixture-password")
    assert len(result["samples"]) == 12
    assert result["coordinate_resolution"].get("latitude") == resolution


def test_modeled_copernicus_samples_refresh_and_reopen_offline(client, test_settings, monkeypatch):
    project = create_project(client)
    raw = raw_fixture(monkeypatch)
    calls = []

    def fetch(req, settings):
        calls.append(req)
        return deepcopy(raw)

    now = datetime(2026, 4, 4, tzinfo=UTC)
    with client.app.state.session_factory() as session:
        result = CopernicusEnvironmentService(session, test_settings, fetch=fetch, now=now).acquire(
            project["id"], request()
        )
        assert len(result.items) == 4
        assert all(item.source_kind == "modeled" for item in result.items)
        assert {item.variable for item in result.items} == {
            "current_eastward_velocity",
            "current_northward_velocity",
            "water_potential_temperature",
            "practical_salinity",
        }
        assert all(item.provenance.model_version == "202601" for item in result.items)
    with client.app.state.session_factory() as session:
        offline = CopernicusEnvironmentService(
            session, test_settings, fetch=fetch, now=now + timedelta(days=2)
        ).acquire(project["id"], request(offline=True))
        assert offline.cache_status == "stale_offline"
        assert [item.id for item in offline.items] == [item.id for item in result.items]
        refreshed = CopernicusEnvironmentService(
            session, test_settings, fetch=fetch, now=now + timedelta(days=2)
        ).acquire(project["id"], request(refresh=True))
        assert [item.id for item in refreshed.items] == [item.id for item in result.items]
    assert len(calls) == 2


@pytest.mark.parametrize(
    "patch",
    [
        {"maximum_longitude": 10},
        {"maximum_latitude": 90},
        {"end_datetime": "2026-04-20T00:00:00Z"},
        {"dataset_id": "cmems_obs_in_situ"},
        {"start_datetime": "2026-04-03T00:00:00"},
        {"offline": True, "refresh": True},
    ],
)
def test_unbounded_or_ambiguous_requests_rejected(patch):
    payload = request().model_dump(mode="json")
    payload.update(patch)
    with pytest.raises(SchemaError):
        CopernicusRequest.model_validate(payload)


@pytest.mark.parametrize(
    "damage",
    [
        "outside",
        "unit",
        "direction",
        "duplicate",
        "version",
        "nan_latitude",
        "infinite_longitude",
        "nan_depth",
        "huge_integer_depth",
        "nan_value",
        "huge_integer_value",
        "string_value",
        "boolean_depth",
        "null_observed_at",
        "null_unit",
        "null_standard_name",
        "non_object_sample",
        "non_object_dataset_metadata",
        "non_object_coordinate_resolution",
        "zero_time_resolution",
        "negative_latitude_resolution",
        "string_time_resolution",
        "boolean_time_resolution",
        "nonfinite_longitude_resolution",
        "unknown_resolution_axis",
        "missing_grid_variable",
        "unequal_grid_coverage",
    ],
)
def test_invalid_provider_grid_never_persists_scientific_records(
    client, test_settings, monkeypatch, damage
):
    project = create_project(client)
    raw = raw_fixture(monkeypatch)
    if damage == "outside":
        raw["samples"][0]["latitude"] = 70
    elif damage == "unit":
        raw["samples"][0]["unit"] = "knots-per-furlong"
    elif damage == "direction":
        raw["samples"][0]["standard_name"] = "sea_water_x_velocity"
    elif damage == "duplicate":
        raw["samples"].append(deepcopy(raw["samples"][0]))
    elif damage == "nan_latitude":
        raw["samples"][0]["latitude"] = float("nan")
    elif damage == "infinite_longitude":
        raw["samples"][0]["longitude"] = float("inf")
    elif damage == "nan_depth":
        raw["samples"][0]["depth_m"] = float("nan")
    elif damage == "huge_integer_depth":
        raw["samples"][0]["depth_m"] = 10**1000
    elif damage == "nan_value":
        raw["samples"][0]["value"] = float("nan")
    elif damage == "huge_integer_value":
        raw["samples"][0]["value"] = 10**1000
    elif damage == "string_value":
        raw["samples"][0]["value"] = "3.0"
    elif damage == "boolean_depth":
        raw["samples"][0]["depth_m"] = True
    elif damage == "null_observed_at":
        raw["samples"][0]["observed_at"] = None
    elif damage == "null_unit":
        raw["samples"][0]["unit"] = None
    elif damage == "null_standard_name":
        raw["samples"][0]["standard_name"] = None
    elif damage == "non_object_sample":
        raw["samples"][0] = None
    elif damage == "non_object_dataset_metadata":
        raw["dataset_metadata"] = []
    elif damage == "non_object_coordinate_resolution":
        raw["coordinate_resolution"] = None
    elif damage == "zero_time_resolution":
        raw["coordinate_resolution"]["time"] = 0.0
    elif damage == "negative_latitude_resolution":
        raw["coordinate_resolution"]["latitude"] = -0.1
    elif damage == "string_time_resolution":
        raw["coordinate_resolution"]["time"] = "3600"
    elif damage == "boolean_time_resolution":
        raw["coordinate_resolution"]["time"] = True
    elif damage == "nonfinite_longitude_resolution":
        raw["coordinate_resolution"]["longitude"] = float("inf")
    elif damage == "unknown_resolution_axis":
        raw["coordinate_resolution"]["vertical_datum"] = 1.0
    elif damage == "missing_grid_variable":
        raw["samples"] = [sample for sample in raw["samples"] if sample["variable"] != "vo"]
    elif damage == "unequal_grid_coverage":
        extra_cell = deepcopy(raw["samples"][0])
        extra_cell["latitude"] = 32.6
        raw["samples"].append(extra_cell)
    else:
        raw["dataset_version"] = "different"
    with client.app.state.session_factory() as session, pytest.raises(ValidationError):
        CopernicusEnvironmentService(session, test_settings, fetch=lambda *_: raw).acquire(
            project["id"], request()
        )
    assert client.get(f"/api/v1/projects/{project['id']}/scientific-records").json()["total"] == 0


def test_null_ocean_value_is_missing_data_not_an_omitted_grid_cell(
    client, test_settings, monkeypatch
):
    """Explicit nulls preserve model-grid coverage without fabricating measurements."""
    project = create_project(client)
    raw = raw_fixture(monkeypatch)
    raw["samples"][0]["value"] = None
    with client.app.state.session_factory() as session:
        result = CopernicusEnvironmentService(
            session, test_settings, fetch=lambda *_: deepcopy(raw)
        ).acquire(project["id"], request())
    assert result.skipped_missing == 1
    assert len(result.items) == 3
    assert "current_eastward_velocity" not in {item.variable for item in result.items}
    assert all(item.qc == "unassessed" for item in result.items)


def test_all_missing_refresh_keeps_cache_but_zero_current_is_valid(
    client, test_settings, monkeypatch
):
    """A missing model subset must not replace data or masquerade as slack water."""
    project = create_project(client)
    raw = raw_fixture(monkeypatch)
    now = datetime(2026, 4, 4, tzinfo=UTC)
    later = now + timedelta(days=2)
    with client.app.state.session_factory() as session:
        cached = CopernicusEnvironmentService(
            session, test_settings, fetch=lambda *_: deepcopy(raw), now=now
        ).acquire(project["id"], request())

    missing = deepcopy(raw)
    for sample in missing["samples"]:
        sample["value"] = None
    with (
        client.app.state.session_factory() as session,
        pytest.raises(ValidationError, match="no available ocean values"),
    ):
        CopernicusEnvironmentService(
            session, test_settings, fetch=lambda *_: missing, now=later
        ).acquire(project["id"], request(refresh=True))

    with client.app.state.session_factory() as session:
        offline = CopernicusEnvironmentService(
            session,
            test_settings,
            fetch=lambda *_: pytest.fail("offline must not acquire remote data"),
            now=later,
        ).acquire(project["id"], request(offline=True))
    assert offline.cache_status == "stale_offline"
    assert [item.id for item in offline.items] == [item.id for item in cached.items]
    assert [item.content_sha256 for item in offline.items] == [
        item.content_sha256 for item in cached.items
    ]

    # Zero-valued current components are actual modeled values, not missing data.
    calm = deepcopy(missing)
    for sample in calm["samples"]:
        if sample["variable"] in {"uo", "vo"}:
            sample["value"] = 0.0
    with client.app.state.session_factory() as session:
        refreshed = CopernicusEnvironmentService(
            session, test_settings, fetch=lambda *_: calm, now=later
        ).acquire(project["id"], request(refresh=True))
    assert refreshed.skipped_missing == 2
    assert {item.variable for item in refreshed.items} == {
        "current_eastward_velocity",
        "current_northward_velocity",
    }
    assert all(item.normalized_value == 0.0 for item in refreshed.items)
    assert all(item.qc == "unassessed" for item in refreshed.items)


def test_invalid_copernicus_resolution_refresh_keeps_prior_offline_snapshot(
    client, test_settings, monkeypatch
):
    """Reject misleading provider grid spacing without losing validated cache."""
    project = create_project(client)
    original = raw_fixture(monkeypatch)
    now = datetime(2026, 4, 4, tzinfo=UTC)
    with client.app.state.session_factory() as session:
        cached = CopernicusEnvironmentService(
            session, test_settings, fetch=lambda *_: deepcopy(original), now=now
        ).acquire(project["id"], request())
    corrupted = deepcopy(original)
    corrupted["coordinate_resolution"]["time"] = 0.0
    with client.app.state.session_factory() as session, pytest.raises(ValidationError):
        CopernicusEnvironmentService(
            session,
            test_settings,
            fetch=lambda *_: deepcopy(corrupted),
            now=now + timedelta(days=2),
        ).acquire(project["id"], request(refresh=True))
    with client.app.state.session_factory() as session:
        offline = CopernicusEnvironmentService(
            session,
            test_settings,
            fetch=lambda *_: pytest.fail("offline must not acquire remote data"),
            now=now + timedelta(days=2),
        ).acquire(project["id"], request(offline=True))
    assert offline.cache_status == "stale_offline"
    assert [item.id for item in offline.items] == [item.id for item in cached.items]


def test_shared_grid_hole_cannot_replace_validated_offline_snapshot(
    client, test_settings, monkeypatch
):
    """A shared missing cell is not equivalent to explicit null model values."""
    project = create_project(client)
    original = raw_fixture(monkeypatch)
    now = datetime(2026, 4, 4, tzinfo=UTC)
    with client.app.state.session_factory() as session:
        cached = CopernicusEnvironmentService(
            session, test_settings, fetch=lambda *_: deepcopy(original), now=now
        ).acquire(project["id"], request())

    damaged = deepcopy(original)
    # Every variable has the same three cells of a two-by-two spatial grid.
    for latitude, longitude in ((32.5, -79.4), (32.6, -79.5)):
        for sample in original["samples"]:
            damaged["samples"].append({**sample, "latitude": latitude, "longitude": longitude})
    with (
        client.app.state.session_factory() as session,
        pytest.raises(ValidationError, match="incomplete rectilinear grid coverage"),
    ):
        CopernicusEnvironmentService(
            session, test_settings, fetch=lambda *_: damaged, now=now + timedelta(days=2)
        ).acquire(project["id"], request(refresh=True))

    with client.app.state.session_factory() as session:
        offline = CopernicusEnvironmentService(
            session,
            test_settings,
            fetch=lambda *_: pytest.fail("offline must not acquire remote data"),
            now=now + timedelta(days=2),
        ).acquire(project["id"], request(offline=True))
    assert offline.cache_status == "stale_offline"
    assert [item.id for item in offline.items] == [item.id for item in cached.items]

    # Explicit nulls complete the grid but must not fabricate measurements.
    for sample in original["samples"]:
        damaged["samples"].append({**sample, "latitude": 32.6, "longitude": -79.4, "value": None})
    with client.app.state.session_factory() as session:
        refreshed = CopernicusEnvironmentService(
            session, test_settings, fetch=lambda *_: damaged, now=now + timedelta(days=2)
        ).acquire(project["id"], request(refresh=True))
    assert refreshed.skipped_missing == 4
    assert len(refreshed.items) == 12
    assert all(item.qc == "unassessed" for item in refreshed.items)


def test_reported_resolution_must_match_multi_cell_grid(client, test_settings, monkeypatch):
    """Contradictory spacing cannot overwrite a validated modeled data snapshot."""
    project = create_project(client)
    raw = raw_fixture(monkeypatch)
    original = deepcopy(raw["samples"])
    for time in ("2026-04-03T00:00:00Z", "2026-04-03T01:00:00Z"):
        for longitude in (-79.5, -79.25):
            if time == "2026-04-03T00:00:00Z" and longitude == -79.5:
                continue
            for sample in original:
                raw["samples"].append({**sample, "observed_at": time, "longitude": longitude})
    raw["coordinate_resolution"] = {"time": 3600.0, "longitude": 0.25}
    now = datetime(2026, 4, 4, tzinfo=UTC)
    with client.app.state.session_factory() as session:
        cached = CopernicusEnvironmentService(
            session, test_settings, fetch=lambda *_: deepcopy(raw), now=now
        ).acquire(project["id"], request())
    assert len(cached.items) == 16
    assert all(item.provenance.temporal_resolution_s == 3600.0 for item in cached.items)

    for axis, wrong_spacing in (("time", 1800.0), ("longitude", 0.5)):
        damaged = deepcopy(raw)
        damaged["coordinate_resolution"][axis] = wrong_spacing
        with (
            client.app.state.session_factory() as session,
            pytest.raises(ValidationError, match="reported resolution disagrees"),
        ):
            CopernicusEnvironmentService(
                session,
                test_settings,
                fetch=lambda *_, damaged=damaged: damaged,
                now=now + timedelta(days=2),
            ).acquire(project["id"], request(refresh=True))

    with client.app.state.session_factory() as session:
        offline = CopernicusEnvironmentService(
            session,
            test_settings,
            fetch=lambda *_: pytest.fail("offline must not acquire remote data"),
            now=now + timedelta(days=2),
        ).acquire(project["id"], request(offline=True))
    assert offline.cache_status == "stale_offline"
    assert [item.id for item in offline.items] == [item.id for item in cached.items]
    assert all(item.qc == "unassessed" for item in offline.items)


def test_valid_provider_grid_spacing_is_retained_as_unassessed_provenance(
    client, test_settings, monkeypatch
):
    """Synthetic spacing is preserved explicitly, without claiming QC acceptance."""
    project = create_project(client)
    raw = raw_fixture(monkeypatch)
    raw["coordinate_resolution"] = {"time": 3600.0, "longitude": 0.5}
    with client.app.state.session_factory() as session:
        result = CopernicusEnvironmentService(
            session, test_settings, fetch=lambda *_: deepcopy(raw)
        ).acquire(project["id"], request())
    assert all(item.provenance.temporal_resolution_s == 3600.0 for item in result.items)
    assert all(item.qc == "unassessed" for item in result.items)
    assert all(
        item.provenance.source_metadata["coordinate_resolution"]["longitude"] == 0.5
        for item in result.items
    )


@pytest.mark.parametrize(
    "damage",
    [
        "oversized",
        "unicode_oversized",
        "key_amplification",
        "nonfinite",
        "recursive",
        "invalid_unicode_metadata",
        "invalid_unicode_toolbox",
        "nontext_toolbox_version",
    ],
)
def test_invalid_provider_provenance_preserves_validated_offline_snapshot(
    client, test_settings, monkeypatch, damage
):
    """Reject amplified or malformed grid metadata before replacing cached science."""
    project = create_project(client)
    valid = raw_fixture(monkeypatch)
    now = datetime(2026, 4, 4, tzinfo=UTC)
    with client.app.state.session_factory() as session:
        cached = CopernicusEnvironmentService(
            session, test_settings, fetch=lambda *_: deepcopy(valid), now=now
        ).acquire(project["id"], request())

    damaged = deepcopy(valid)
    if damage == "oversized":
        damaged["dataset_metadata"]["vendor_history"] = "x" * 20_000
    elif damage == "unicode_oversized":
        # Metadata budget is UTF-8 bytes, not Unicode code points.
        damaged["dataset_metadata"]["vendor_history"] = "🐙" * 5_000
    elif damage == "key_amplification":
        damaged["dataset_metadata"].update({f"vendor_{index:04d}": "x" for index in range(1_500)})
    elif damage == "invalid_unicode_metadata":
        # Unpaired surrogate escapes are legal in JSON but cannot form valid UTF-8.
        damaged["dataset_metadata"]["vendor_history"] = "bad\ud800"
    elif damage == "invalid_unicode_toolbox":
        damaged["toolbox_version"] = "version\ud800"
    elif damage == "nontext_toolbox_version":
        damaged["toolbox_version"] = {"unverified": "1.2"}
    elif damage == "nonfinite":
        damaged["dataset_metadata"]["uncertain_error"] = float("nan")
    else:
        recursive = {}
        recursive["self"] = recursive
        damaged["dataset_metadata"]["vendor_history"] = recursive

    with (
        client.app.state.session_factory() as session,
        pytest.raises(ValidationError, match="Copernicus provider metadata"),
    ):
        CopernicusEnvironmentService(
            session,
            test_settings,
            fetch=lambda *_: damaged,
            now=now + timedelta(days=2),
        ).acquire(project["id"], request(refresh=True))

    with client.app.state.session_factory() as session:
        offline = CopernicusEnvironmentService(
            session,
            test_settings,
            fetch=lambda *_: pytest.fail("offline mode must not contact provider"),
            now=now + timedelta(days=2),
        ).acquire(project["id"], request(offline=True))
    assert offline.cache_status == "stale_offline"
    assert [item.id for item in offline.items] == [item.id for item in cached.items]
    assert all(
        item.provenance.source_metadata["dataset"] == valid["dataset_metadata"]
        for item in offline.items
    )


def test_offline_cache_isolated_by_pinned_version_and_variable_selection(
    client, test_settings, monkeypatch
):
    """A cached model subset cannot silently satisfy a different scientific request."""
    project = create_project(client)
    raw = raw_fixture(monkeypatch)
    now = datetime(2026, 4, 4, tzinfo=UTC)
    with client.app.state.session_factory() as session:
        cached = CopernicusEnvironmentService(
            session, test_settings, fetch=lambda *_: deepcopy(raw), now=now
        ).acquire(project["id"], request())

    endpoint = f"/api/v1/projects/{project['id']}/environment/copernicus"
    for overrides in ({"dataset_version": "202602"}, {"variables": ["uo", "vo"]}):
        payload = request(offline=True).model_dump(mode="json")
        payload.update(overrides)
        response = client.post(endpoint, json=payload)
        assert response.status_code == 404, response.text

    with client.app.state.session_factory() as session:
        reopened = CopernicusEnvironmentService(
            session,
            test_settings,
            fetch=lambda *_: pytest.fail("offline must not acquire remote data"),
            now=now + timedelta(days=2),
        ).acquire(project["id"], request(offline=True))
    assert reopened.cache_status == "stale_offline"
    assert [item.id for item in reopened.items] == [item.id for item in cached.items]
    assert [item.content_sha256 for item in reopened.items] == [
        item.content_sha256 for item in cached.items
    ]
    assert all(item.provenance.model_version == "202601" for item in reopened.items)
    assert all(item.qc == "unassessed" for item in reopened.items)


@pytest.mark.parametrize(
    ("elapsed", "force_refresh", "expected_status", "expected_calls"),
    [
        (timedelta(days=1) - timedelta(seconds=1), False, "fresh", 1),
        (timedelta(days=1), False, "downloaded", 2),
        (timedelta(hours=1), True, "downloaded", 2),
    ],
)
def test_copernicus_cache_freshness_does_not_mutate_scientific_records(
    client, test_settings, monkeypatch, elapsed, force_refresh, expected_status, expected_calls
):
    """An identical provider response renews cache freshness, not scientific evidence."""
    project = create_project(client)
    raw = raw_fixture(monkeypatch)
    now = datetime(2026, 4, 4, tzinfo=UTC)
    calls = []

    def fetch(req, _settings):
        calls.append(req)
        return deepcopy(raw)

    with client.app.state.session_factory() as session:
        cached = CopernicusEnvironmentService(session, test_settings, fetch=fetch, now=now).acquire(
            project["id"], request()
        )
    with client.app.state.session_factory() as session:
        reused = CopernicusEnvironmentService(
            session, test_settings, fetch=fetch, now=now + elapsed
        ).acquire(project["id"], request(refresh=force_refresh))

    assert len(calls) == expected_calls
    assert reused.cache_status == expected_status
    expected_fetch_time = now + elapsed if expected_calls == 2 else now
    assert reused.fetched_at == expected_fetch_time
    assert reused.expires_at == expected_fetch_time + timedelta(days=1)
    assert [item.id for item in reused.items] == [item.id for item in cached.items]
    assert [item.content_sha256 for item in reused.items] == [
        item.content_sha256 for item in cached.items
    ]
    assert all(item.provenance.acquired_at == now for item in reused.items)
    assert all(item.qc == "unassessed" for item in reused.items)


def test_changed_copernicus_refresh_preserves_history_and_excludes_superseded_values(
    client, test_settings, monkeypatch
):
    """A refreshed model snapshot must not double-count superseded environmental values."""
    project = create_project(client)
    original = raw_fixture(monkeypatch)
    now = datetime(2026, 4, 4, tzinfo=UTC)
    later = now + timedelta(days=2)
    with client.app.state.session_factory() as session:
        cached = CopernicusEnvironmentService(
            session, test_settings, fetch=lambda *_: deepcopy(original), now=now
        ).acquire(project["id"], request())

    changed = deepcopy(original)
    changed["samples"][0]["value"] = 6.0
    with client.app.state.session_factory() as session:
        service = CopernicusEnvironmentService(
            session, test_settings, fetch=lambda *_: changed, now=later
        )
        refreshed = service.acquire(project["id"], request(refresh=True))
        lookup = service.environment.lookup(
            project["id"],
            EnvironmentalLookup(
                variable="current_eastward_velocity",
                location={"latitude": 32.5, "longitude": -79.5},
                observed_at=datetime(2026, 4, 3, tzinfo=UTC),
                max_distance_m=0,
                max_time_delta_s=0,
                source_kinds=["modeled"],
            ),
        )
    assert len(refreshed.items) == 4
    assert all(item.environmental_snapshot_current is True for item in refreshed.items)
    assert len(lookup.matches) == 1
    assert lookup.matches[0].record.normalized_value == 6.0
    assert lookup.matches[0].record.qc == "unassessed"

    response = client.get(f"/api/v1/projects/{project['id']}/scientific-records")
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 8
    records = {item["id"]: item for item in response.json()["items"]}
    for item in cached.items:
        historical = records[str(item.id)]
        assert historical["environmental_snapshot_current"] is False
        assert historical["content_sha256"] == item.content_sha256
        assert historical["normalized_value"] == item.normalized_value
    assert {str(item.id) for item in refreshed.items}.isdisjoint(
        str(item.id) for item in cached.items
    )


def test_null_refresh_retires_old_measurement_without_fabricating_zero(
    client, test_settings, monkeypatch
):
    """A newly missing modeled value must not leak into current scientific analyses."""
    project = create_project(client)
    original = raw_fixture(monkeypatch)
    now = datetime(2026, 4, 4, tzinfo=UTC)
    later = now + timedelta(days=2)
    with client.app.state.session_factory() as session:
        cached = CopernicusEnvironmentService(
            session, test_settings, fetch=lambda *_: deepcopy(original), now=now
        ).acquire(project["id"], request())

    missing = deepcopy(original)
    missing["samples"][0]["value"] = None
    with client.app.state.session_factory() as session:
        refreshed = CopernicusEnvironmentService(
            session, test_settings, fetch=lambda *_: missing, now=later
        ).acquire(project["id"], request(refresh=True))
    assert refreshed.skipped_missing == 1
    assert len(refreshed.items) == 3

    with client.app.state.session_factory() as session:
        service = CopernicusEnvironmentService(
            session,
            test_settings,
            fetch=lambda *_: pytest.fail("offline must not acquire remote data"),
            now=later,
        )
        reopened = service.acquire(project["id"], request(offline=True))
        lookup = service.environment.lookup(
            project["id"],
            EnvironmentalLookup(
                variable="current_eastward_velocity",
                location={"latitude": 32.5, "longitude": -79.5},
                observed_at=datetime(2026, 4, 3, tzinfo=UTC),
                max_distance_m=0,
                max_time_delta_s=0,
                source_kinds=["modeled"],
            ),
        )
    assert reopened.skipped_missing == 1
    assert [item.id for item in reopened.items] == [item.id for item in refreshed.items]
    assert not lookup.matches

    response = client.get(f"/api/v1/projects/{project['id']}/scientific-records")
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 7
    records = {item["id"]: item for item in response.json()["items"]}
    for item in cached.items:
        historical = records[str(item.id)]
        assert historical["environmental_snapshot_current"] is False
        assert historical["content_sha256"] == item.content_sha256
        assert historical["normalized_value"] == item.normalized_value


def test_missing_copernicus_configuration_fails_without_leaking_secrets(client):
    project = create_project(client)
    response = client.post(
        f"/api/v1/projects/{project['id']}/environment/copernicus",
        json=request().model_dump(mode="json"),
    )
    assert response.status_code == 400, response.text
    assert "credentials" in response.json()["detail"].lower()


def test_copernicus_cache_survives_project_exchange(client, test_settings, monkeypatch):
    from reefvision.tests.test_scientific_project_exchange import export_archive, import_archive

    project = create_project(client)
    raw = raw_fixture(monkeypatch)
    with client.app.state.session_factory() as session:
        CopernicusEnvironmentService(session, test_settings, fetch=lambda *_: raw).acquire(
            project["id"], request()
        )
    imported = import_archive(client, export_archive(client, test_settings, project["id"]))
    assert imported.status_code == 201, imported.text
    response = client.post(
        f"/api/v1/projects/{imported.json()['project_id']}/environment/copernicus",
        json=request(offline=True).model_dump(mode="json"),
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 4


def test_copernicus_exchange_preserves_missing_refresh_and_historical_evidence(
    client, test_settings, monkeypatch
):
    """Moving a project offline must not resurrect superseded modeled measurements."""
    from reefvision.tests.test_scientific_project_exchange import export_archive, import_archive

    project = create_project(client)
    raw = raw_fixture(monkeypatch)
    now = datetime(2026, 4, 4, tzinfo=UTC)
    later = now + timedelta(days=2)
    with client.app.state.session_factory() as session:
        CopernicusEnvironmentService(
            session, test_settings, fetch=lambda *_: deepcopy(raw), now=now
        ).acquire(project["id"], request())

    missing = deepcopy(raw)
    missing["samples"][0]["value"] = None
    with client.app.state.session_factory() as session:
        CopernicusEnvironmentService(
            session, test_settings, fetch=lambda *_: missing, now=later
        ).acquire(project["id"], request(refresh=True))

    source_url = f"/api/v1/projects/{project['id']}/scientific-records"
    before = client.get(source_url).json()["items"]
    assert len(before) == 7
    imported = import_archive(client, export_archive(client, test_settings, project["id"]))
    assert imported.status_code == 201, imported.text
    imported_id = imported.json()["project_id"]

    response = client.get(f"/api/v1/projects/{imported_id}/scientific-records")
    assert response.status_code == 200, response.text
    after = response.json()["items"]
    assert len(after) == 7
    assert {row["id"] for row in before}.isdisjoint(row["id"] for row in after)
    assert sum(row["environmental_snapshot_current"] is False for row in after) == 4
    historical = [row for row in after if row["variable"] == "current_eastward_velocity"]
    assert len(historical) == 1
    assert historical[0]["environmental_snapshot_current"] is False
    assert historical[0]["normalized_value"] == 3.0
    assert historical[0]["qc"] == "unassessed"

    offline = client.post(
        f"/api/v1/projects/{imported_id}/environment/copernicus",
        json=request(offline=True).model_dump(mode="json"),
    )
    assert offline.status_code == 200, offline.text
    assert offline.json()["skipped_missing"] == 1
    assert {row["id"] for row in offline.json()["items"]} == {
        row["id"] for row in after if row["environmental_snapshot_current"] is True
    }
    assert client.get(source_url).json()["items"] == before


def test_cached_datasets_are_listed_and_opened_only_within_project(
    client, test_settings, monkeypatch
):
    project = create_project(client)
    other = create_project(client, "Other")
    raw = raw_fixture(monkeypatch)
    with client.app.state.session_factory() as session:
        CopernicusEnvironmentService(session, test_settings, fetch=lambda *_: raw).acquire(
            project["id"], request()
        )
    listing = client.get(f"/api/v1/projects/{project['id']}/environment/datasets")
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 1
    item = listing.json()["items"][0]
    assert item["provider"] == "copernicus_marine"
    assert item["record_count"] == 4
    opened = client.get(
        f"/api/v1/projects/{project['id']}/environment/datasets/{item['cache_key']}"
    )
    assert len(opened.json()["items"]) == 4
    assert (
        client.get(
            f"/api/v1/projects/{other['id']}/environment/datasets/{item['cache_key']}"
        ).status_code
        == 404
    )


def test_worker_timeout_sanitizes_errors_and_configuration_excludes_credentials(
    test_settings, monkeypatch
):
    import subprocess

    from pydantic import SecretStr

    from reefvision.services.copernicus_environment import fetch_copernicus

    settings = test_settings.model_copy(
        update={
            "copernicus_username": SecretStr("synthetic-user"),
            "copernicus_password": SecretStr("synthetic-secret"),
        }
    )

    def fail(*args, **kwargs):
        assert "synthetic-secret" not in str(args)
        assert kwargs["timeout"] == 90
        assert kwargs["env"]["COPERNICUSMARINE_SERVICE_PASSWORD"] == "synthetic-secret"
        raise subprocess.TimeoutExpired("synthetic-secret", 90)

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(ValidationError) as exc:
        fetch_copernicus(request(), settings)
    assert "synthetic-secret" not in str(exc.value)
    assert "synthetic-secret" not in settings.model_dump_json()
