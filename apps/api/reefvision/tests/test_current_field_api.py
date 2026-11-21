from datetime import UTC, datetime

from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_scientific_project_exchange import export_archive, import_archive


def test_streamline_preview_uses_one_compatible_scientific_record_slice(
    client, test_settings
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
                        "qc": "accepted",
                        "provenance": {
                            "source": "synthetic current fixture",
                            "dataset_id": "fixture-v1",
                            "acquired_at": datetime(2026, 1, 2, tzinfo=UTC).isoformat(),
                            "method": "test",
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
    assert "not organism trajectories" in " ".join(result["methodological_notes"])

    saved = client.post(
        f"/api/v1/projects/{project['id']}/environment/analyses/current-streamline",
        json={"name": "Pinned surface flow", **request},
    )
    assert saved.status_code == 201, saved.text
    body = saved.json()
    assert body["definition"]["analysis_kind"] == "current_streamline"
    assert body["result"]["source_record_ids"] == ids
    assert body["result"]["payload"]["input_sha256"] == result["input_sha256"]
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
    imported_validation = client.get(
        f"/api/v1/projects/{imported_project_id}/environment/analyses/results/"
        f"{portable[0]['id']}/validation"
    )
    assert imported_validation.status_code == 200
    assert imported_validation.json()["current"] is True


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
