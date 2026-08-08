from __future__ import annotations

import io
import zipfile
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.db.models import ImageAsset, LabelClass, MaskAnnotationEvent
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_dataset_versions import create_version


def _seed_measurement_image(client: TestClient) -> tuple[dict[str, object], str, str, str]:
    project = create_project(client, "Phase 4 coral measurements")
    report = import_one(client, str(project["id"]), size=(100, 80))
    image_id = str(report["successful"][0]["image_id"])
    label_classes = cast(list[dict[str, object]], project["label_classes"])
    primary_class_id = str(label_classes[0]["id"])
    secondary_class_id = str(label_classes[1]["id"])
    mask_id = "c5eb715d-dac8-4c90-a84e-77d8e8a64cbd"
    saved = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [
                {
                    "id": "ca45f365-acde-4bf8-a411-1cc1d8c5dc5a",
                    "label_class_id": primary_class_id,
                    "x_min": 12,
                    "y_min": 12,
                    "x_max": 18,
                    "y_max": 18,
                },
                {
                    "id": "646970a4-f424-4375-ad39-f9cc7c5e4724",
                    "label_class_id": secondary_class_id,
                    "x_min": 22,
                    "y_min": 12,
                    "x_max": 28,
                    "y_max": 18,
                },
            ],
            "mask_annotations": [
                {
                    "id": mask_id,
                    "label_class_id": primary_class_id,
                    "geometry_kind": "polygon",
                    "points": [
                        {"x": 10, "y": 10},
                        {"x": 30, "y": 10},
                        {"x": 30, "y": 20},
                        {"x": 10, "y": 20},
                    ],
                }
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    return project, image_id, mask_id, secondary_class_id


def test_calibration_centerline_and_surface_area_are_revisioned(client: TestClient) -> None:
    project, image_id, mask_id, _secondary_class_id = _seed_measurement_image(client)

    calibrated = client.put(
        f"/api/v1/images/{image_id}/measurement-calibration",
        json={
            "distance_per_pixel": 0.1,
            "unit": "mm",
            "source": "scale bar",
            "reference_length": 10,
            "reference_pixel_length": 100,
            "default_depth": 2,
        },
    )
    assert calibrated.status_code == 200, calibrated.text
    assert calibrated.json()["distance_per_pixel"] == pytest.approx(0.1)

    profile = client.put(
        f"/api/v1/mask-annotations/{mask_id}/measurement-profile",
        json={
            "base_revision": 1,
            "centerline_points": [{"x": 10, "y": 15}, {"x": 30, "y": 15}],
            "surface_model": "extruded",
            "depth_value": 2,
            "notes": "Manual branch axis",
        },
    )
    assert profile.status_code == 200, profile.text
    assert profile.json()["revision"] == 2
    assert profile.json()["centerline_length_pixels"] == pytest.approx(20.0)

    measured = client.get(f"/api/v1/mask-annotations/{mask_id}/measurements")
    assert measured.status_code == 200, measured.text
    payload = measured.json()
    assert payload["calibrated"] is True
    assert payload["physical_unit"] == "mm"
    assert payload["area_physical"] == pytest.approx(2.0)
    assert payload["perimeter_physical"] == pytest.approx(6.0)
    assert payload["total_linear_extension_pixels"] == pytest.approx(20.0)
    assert payload["total_linear_extension_physical"] == pytest.approx(2.0)
    assert payload["surface_area_model"] == "extruded"
    assert payload["surface_area_physical"] == pytest.approx(16.0)

    stale = client.put(
        f"/api/v1/mask-annotations/{mask_id}/measurement-profile",
        json={"base_revision": 1, "centerline_points": [], "surface_model": "none"},
    )
    assert stale.status_code == 409

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        image = session.get(ImageAsset, image_id)
        assert image is not None
        assert image.annotation_revision == 2
        events = session.query(MaskAnnotationEvent).filter_by(mask_annotation_id=mask_id).all()
        assert [event.event_type for event in events] == ["created", "measurement_updated"]
        assert events[-1].after_json["measurement_json"]["surface_model"] == "extruded"

    export = client.get(f"/api/v1/projects/{project['id']}/measurement-export?format=csv")
    assert export.status_code == 200, export.text
    assert "total_linear_extension_physical" in export.text
    assert mask_id in export.text


def test_density_filters_and_numpy_bundle(client: TestClient) -> None:
    project, _image_id, mask_id, secondary_class_id = _seed_measurement_image(client)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        secondary = session.get(LabelClass, secondary_class_id)
        assert secondary is not None
        secondary.scientific_name = "Swiftia exserta"
        secondary.state_name = "open"
        session.commit()

    unfiltered = client.get(f"/api/v1/mask-annotations/{mask_id}/measurements")
    assert unfiltered.status_code == 200
    assert unfiltered.json()["contained_box_count"] == 2

    by_class = client.get(
        f"/api/v1/mask-annotations/{mask_id}/measurements",
        params={"label_class_id": secondary_class_id},
    )
    assert by_class.status_code == 200, by_class.text
    assert by_class.json()["contained_box_count"] == 1
    assert by_class.json()["filters"]["label_class_ids"] == [secondary_class_id]

    by_species_state = client.get(
        f"/api/v1/mask-annotations/{mask_id}/measurements",
        params={"scientific_name": "Swiftia exserta", "state_name": "open"},
    )
    assert by_species_state.status_code == 200, by_species_state.text
    assert by_species_state.json()["contained_box_count"] == 1

    exported = client.get(f"/api/v1/projects/{project['id']}/measurement-export?format=numpy")
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        assert set(archive.namelist()) == {
            "columns.json",
            "measurements.npy",
            "rows.json",
        }
        assert archive.read("measurements.npy").startswith(b"\x93NUMPY")
        assert mask_id.encode() in archive.read("rows.json")


def test_project_summary_groups_measurements(client: TestClient) -> None:
    project, image_id, mask_id, _secondary_class_id = _seed_measurement_image(client)
    calibrated = client.put(
        f"/api/v1/images/{image_id}/measurement-calibration",
        json={"distance_per_pixel": 0.1, "unit": "mm", "source": "manual"},
    )
    assert calibrated.status_code == 200, calibrated.text
    profile = client.put(
        f"/api/v1/mask-annotations/{mask_id}/measurement-profile",
        json={
            "base_revision": 1,
            "centerline_points": [{"x": 10, "y": 15}, {"x": 30, "y": 15}],
            "surface_model": "cylindrical_centerline",
            "diameter_value": 1,
        },
    )
    assert profile.status_code == 200, profile.text

    response = client.get(f"/api/v1/projects/{project['id']}/measurement-summary")
    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["mask_count"] == 1
    assert summary["calibrated_mask_count"] == 1
    assert summary["area_pixels"] == 200
    assert summary["contained_box_count"] == 2
    assert summary["calibrated_area_by_unit"]["mm"] == pytest.approx(2.0)
    assert summary["calibrated_tle_by_unit"]["mm"] == pytest.approx(2.0)
    assert summary["surface_area_by_unit"]["mm"] == pytest.approx(2.0 * 3.141592653589793)
    assert len(summary["by_class"]) == 1


def test_dataset_snapshot_preserves_measurement_profile(client: TestClient) -> None:
    project, _image_id, mask_id, _secondary_class_id = _seed_measurement_image(client)
    profile = client.put(
        f"/api/v1/mask-annotations/{mask_id}/measurement-profile",
        json={
            "base_revision": 1,
            "centerline_points": [{"x": 10, "y": 15}, {"x": 30, "y": 15}],
            "surface_model": "none",
            "notes": "Frozen TLE profile",
        },
    )
    assert profile.status_code == 200, profile.text
    version = create_version(client, str(project["id"]), name="Measured masks")
    items = client.get(f"/api/v1/dataset-versions/{version['id']}/items")
    assert items.status_code == 200, items.text
    snapshot = items.json()[0]["mask_annotation_snapshot_json"][0]
    assert snapshot["measurement_json"]["notes"] == "Frozen TLE profile"
    assert snapshot["measurement_json"]["centerline_points"] == [
        {"x": 10.0, "y": 15.0},
        {"x": 30.0, "y": 15.0},
    ]
