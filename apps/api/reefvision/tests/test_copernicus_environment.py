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
        "nan_value",
        "string_value",
        "boolean_depth",
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
    elif damage == "nan_value":
        raw["samples"][0]["value"] = float("nan")
    elif damage == "string_value":
        raw["samples"][0]["value"] = "3.0"
    elif damage == "boolean_depth":
        raw["samples"][0]["depth_m"] = True
    else:
        raw["dataset_version"] = "different"
    with client.app.state.session_factory() as session, pytest.raises(ValidationError):
        CopernicusEnvironmentService(session, test_settings, fetch=lambda *_: raw).acquire(
            project["id"], request()
        )
    assert client.get(f"/api/v1/projects/{project['id']}/scientific-records").json()["total"] == 0


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
