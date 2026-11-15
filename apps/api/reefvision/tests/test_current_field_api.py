from datetime import UTC, datetime

import pytest

from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_scientific_project_exchange import export_archive, import_archive


@pytest.mark.parametrize(
    ("qc", "uncertainty"),
    [
        ("accepted", None),
        ("unassessed", {"value": 0.05, "kind": "standard_deviation"}),
    ],
)
def test_streamline_preview_uses_one_compatible_scientific_record_slice(
    client, test_settings, qc, uncertainty
) -> None:
    project = create_project(client, "Current streamline")
    records = []
    for latitude in (-1.0, 1.0):
        for longitude in (-1.0, 1.0):
            for variable, value in (
                ("current_eastward_velocity", 1.0),
                ("current_northward_velocity", 0.0),
            ):
                records.append(
                    {
                        "variable": variable,
                        "value": value,
                        "unit": "m/s",
                        "observed_at": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
                        "source_kind": "modeled",
                        "location": {
                            "crs": "EPSG:4326",
                            "latitude": latitude,
                            "longitude": longitude,
                        },
                        "depth_m": 0,
                        "depth_reference": "sea_surface",
                        "qc": qc,
                        "uncertainty": uncertainty,
                        "provenance": {
                            "source": "synthetic current fixture",
                            "dataset_id": "fixture-v1",
                            "acquired_at": datetime(2026, 1, 2, tzinfo=UTC).isoformat(),
                            "method": "test",
                            "processing_parameters": (
                                {"smoothing_radius_m": 10, "grid_revision": "r1"}
                                if variable == "current_eastward_velocity"
                                else {"grid_revision": "r1", "smoothing_radius_m": 10}
                            ),
                        },
                    }
                )
    created = client.post(
        f"/api/v1/projects/{project['id']}/scientific-records", json={"records": records}
    )
    assert created.status_code == 201, created.text
    ids = [item["id"] for item in created.json()["items"]]

    request = {
        "scientific_record_ids": ids,
        "seeds": [{"latitude": 0, "longitude": 0}],
        "step_seconds": 60,
        "max_steps": 2,
        "max_length_m": 1000,
    }
    response = client.post(
        f"/api/v1/projects/{project['id']}/current-field/streamlines/preview",
        json=request,
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["algorithm_version"] == "wgs84-stationary-bilinear-rk4-v1"
    assert result["source_kind"] == "modeled"
    assert result["observed_at"] == "2026-01-01T00:00:00Z"
    assert result["depth_m"] == 0
    assert result["depth_reference"] == "sea_surface"
    assert result["streamlines"][0]["termination"] == "max_steps"
    assert len(result["source_record_ids"]) == 8
    assert len(result["input_sha256"]) == 64
    notes = " ".join(result["methodological_notes"])
    assert "not organism trajectories" in notes
    assert "uncertainty is not propagated" in notes
    assert ("unassessed QC" in notes) == (qc == "unassessed")

    saved = client.post(
        f"/api/v1/projects/{project['id']}/environment/analyses/current-streamline",
        json={"name": "Pinned surface flow", **request},
    )
    assert saved.status_code == 201, saved.text
    body = saved.json()
    assert body["definition"]["analysis_kind"] == "current_streamline"
    assert body["result"]["source_record_ids"] == ids
    assert body["result"]["payload"]["input_sha256"] == result["input_sha256"]
    assert body["result"]["payload"]["methodological_notes"] == result["methodological_notes"]
    validation = client.get(
        f"/api/v1/projects/{project['id']}/environment/analyses/results/"
        f"{body['result']['id']}/validation"
    )
    assert validation.status_code == 200
    assert validation.json()["current"] is True
    exported = client.get(
        f"/api/v1/projects/{project['id']}/environment/analyses/results/{body['result']['id']}.csv"
    )
    assert exported.status_code == 200
    assert "current_streamline" in exported.text

    archive = export_archive(client, test_settings, project["id"])
    imported = import_archive(client, archive)
    assert imported.status_code == 201, imported.text
    imported_project_id = imported.json()["project_id"]
    imported_results = client.get(
        f"/api/v1/projects/{imported_project_id}/environment/analyses/results",
        params={"analysis_kind": "current_streamline"},
    )
    assert imported_results.status_code == 200, imported_results.text
    portable = imported_results.json()["items"]
    assert len(portable) == 1
    assert portable[0]["id"] != body["result"]["id"]
    assert set(portable[0]["source_record_ids"]).isdisjoint(ids)
    assert portable[0]["payload"]["methodological_notes"] == result["methodological_notes"]
    imported_validation = client.get(
        f"/api/v1/projects/{imported_project_id}/environment/analyses/results/"
        f"{portable[0]['id']}/validation"
    )
    assert imported_validation.status_code == 200
    assert imported_validation.json()["current"] is True


@pytest.mark.parametrize(
    ("altered_field", "replacement", "diagnostic"),
    [
        ("observed_at", "2026-01-01T01:00:00Z", "share UTC"),
        ("source_kind", "observed", "share UTC"),
        ("depth_m", 10.0, "share UTC"),
        ("depth_reference", "seabed", "share UTC"),
        ("provenance.source", "different provider", "share UTC"),
        ("provenance.dataset_id", "different grid", "share UTC"),
        ("provenance.model_version", "v2", "share UTC"),
        ("provenance.method", "interpolated from another sensor", "method"),
        ("provenance.processing_parameters", {"smoothing_radius_m": 500}, "processing"),
        ("provenance.spatial_resolution_m", 1000.0, "resolution"),
        ("provenance.temporal_resolution_s", 3600.0, "resolution"),
        ("qc", "suspect", "Suspect or rejected"),
        ("qc", "rejected", "Suspect or rejected"),
    ],
)
def test_streamline_preview_rejects_mixed_scientific_identity_or_qc(
    client, altered_field, replacement, diagnostic
) -> None:
    """Never blend different time/depth/provider/QC identities into one velocity cell."""
    project = create_project(client, "Incompatible current sources")
    records = [
        {
            "variable": variable,
            "value": value,
            "unit": "m/s",
            "observed_at": "2026-01-01T00:00:00Z",
            "source_kind": "modeled",
            "location": {"latitude": latitude, "longitude": longitude},
            "depth_m": 0.0,
            "depth_reference": "sea_surface",
            "qc": "accepted",
            "provenance": {
                "source": "synthetic grid",
                "dataset_id": "fixture-v1",
                "model_version": "v1",
                "acquired_at": "2026-01-02T00:00:00Z",
            },
        }
        for latitude in (-1.0, 1.0)
        for longitude in (-1.0, 1.0)
        for variable, value in (
            ("current_eastward_velocity", 1.0),
            ("current_northward_velocity", 0.0),
        )
    ]
    if altered_field.startswith("provenance."):
        records[0]["provenance"][altered_field.removeprefix("provenance.")] = replacement
    else:
        records[0][altered_field] = replacement

    created = client.post(
        f"/api/v1/projects/{project['id']}/scientific-records",
        json={"records": records},
    )
    assert created.status_code == 201, created.text
    response = client.post(
        f"/api/v1/projects/{project['id']}/current-field/streamlines/preview",
        json={
            "scientific_record_ids": [item["id"] for item in created.json()["items"]],
            "seeds": [{"latitude": 0, "longitude": 0}],
            "max_steps": 2,
        },
    )
    assert response.status_code == 400, response.text
    assert diagnostic.lower() in response.json()["detail"].lower()


def test_streamline_preview_rejects_incomplete_component_grid(client) -> None:
    project = create_project(client, "Incomplete current")
    record = {
        "variable": "current_eastward_velocity",
        "value": 1,
        "unit": "m/s",
        "observed_at": "2026-01-01T00:00:00Z",
        "source_kind": "modeled",
        "location": {"latitude": 0, "longitude": 0},
        "depth_m": 0,
        "depth_reference": "sea_surface",
        "provenance": {
            "source": "fixture",
            "acquired_at": "2026-01-01T00:00:00Z",
        },
    }
    created = client.post(
        f"/api/v1/projects/{project['id']}/scientific-records", json={"records": [record]}
    ).json()
    response = client.post(
        f"/api/v1/projects/{project['id']}/current-field/streamlines/preview",
        json={
            "scientific_record_ids": [created["items"][0]["id"]],
            "seeds": [{"latitude": 0, "longitude": 0}],
        },
    )
    assert response.status_code == 400
    assert "paired" in response.json()["detail"].lower()


def test_streamline_preview_rejects_dateline_grid_instead_of_false_interpolation(client) -> None:
    project = create_project(client, "Dateline current QC")
    records = [
        {
            "variable": variable,
            "value": value,
            "unit": "m/s",
            "observed_at": "2026-01-01T00:00:00Z",
            "source_kind": "modeled",
            "location": {"crs": "EPSG:4326", "latitude": latitude, "longitude": longitude},
            "depth_m": 0,
            "depth_reference": "sea_surface",
            "qc": "accepted",
            "provenance": {
                "source": "synthetic dateline fixture",
                "dataset_id": "fixture-v1",
                "acquired_at": "2026-01-02T00:00:00Z",
            },
        }
        for latitude in (-1.0, 1.0)
        for longitude in (-179.0, 179.0)
        for variable, value in (
            ("current_eastward_velocity", 1.0),
            ("current_northward_velocity", 0.0),
        )
    ]
    created = client.post(
        f"/api/v1/projects/{project['id']}/scientific-records", json={"records": records}
    )
    assert created.status_code == 201, created.text
    ids = [item["id"] for item in created.json()["items"]]
    response = client.post(
        f"/api/v1/projects/{project['id']}/current-field/streamlines/preview",
        json={
            "scientific_record_ids": ids,
            "seeds": [{"latitude": 0, "longitude": 179.5}],
        },
    )
    assert response.status_code == 400, response.text
    assert "longitude gap exceeds 180 degrees" in response.json()["detail"]
