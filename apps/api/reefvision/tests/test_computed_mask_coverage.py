from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from reefvision.db.models import ImageAsset, LabelClass, MaskAnnotation
from reefvision.tests.test_annotations import create_project, import_one


def _image(client: TestClient, project_id: str, *, index: int = 1) -> str:
    report = import_one(
        client,
        project_id,
        filename=f"coverage-{index}.png",
        relative_path=f"coverage/coverage-{index}.png",
        size=(10, 10),
    )
    return str(report["successful"][0]["image_id"])


def _polygon(mask_id: str, label_id: str, points: list[tuple[float, float]]) -> dict[str, Any]:
    return {
        "id": mask_id,
        "label_class_id": label_id,
        "geometry_kind": "polygon",
        "points": [{"x": x, "y": y} for x, y in points],
    }


def _save_masks(
    client: TestClient,
    image_id: str,
    masks: list[dict[str, Any]],
    *,
    group_key: str | None = None,
) -> None:
    saved = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [],
            "mask_annotations": masks,
        },
    )
    assert saved.status_code == 200, saved.text
    if group_key is not None:
        updated = client.patch(
            f"/api/v1/images/{image_id}",
            json={"annotation_status": "reviewed", "group_key": group_key},
        )
        assert updated.status_code == 200, updated.text


def _definition(
    client: TestClient,
    project_id: str,
    target_label: str,
    *,
    roi_label: str | None = None,
    grouping_level: str = "image",
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/projects/{project_id}/computed-mask-coverage-definitions",
        json={
            "name": "Verified coral cover",
            "grouping_level": grouping_level,
            "label_class_ids": [target_label],
            "roi_label_class_id": roi_label,
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def _preview(client: TestClient, project_id: str, definition_id: str, image_ids: list[str]):
    return client.post(
        f"/api/v1/projects/{project_id}/computed-mask-coverage-definitions/{definition_id}/preview",
        json={"image_ids": image_ids},
    )


def test_known_overlap_reports_sum_union_and_image_coverage(client: TestClient) -> None:
    project = create_project(client, "Known mask union")
    target = str(project["label_classes"][0]["id"])
    image_id = _image(client, project["id"])
    _save_masks(
        client,
        image_id,
        [
            _polygon(str(uuid4()), target, [(1, 1), (4, 1), (4, 4), (1, 4)]),
            _polygon(str(uuid4()), target, [(3, 1), (6, 1), (6, 4), (3, 4)]),
        ],
    )
    definition = _definition(client, project["id"], target)

    response = _preview(client, project["id"], definition["id"], [image_id])

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["mask_count"] == 2
    assert payload["summed_mask_area_pixels"] == 32
    assert payload["union_area_pixels"] == 24
    assert payload["overlap_area_pixels"] == 8
    assert payload["image_denominator_pixels"] == 100
    assert payload["image_coverage_percent"] == pytest.approx(24.0)
    assert payload["roi_denominator_pixels"] is None
    assert payload["roi_coverage_percent"] is None
    assert payload["algorithm"] == "reefvision.source-pixel-mask-union.v1"
    assert payload["images"][0]["union_area_pixels"] == 24
    assert payload["area_by_class"][0]["union_area_pixels"] == 24


def test_roi_union_and_scalar_calibration_make_denominators_explicit(
    client: TestClient,
) -> None:
    project = create_project(client, "ROI calibrated coverage")
    target = str(project["label_classes"][0]["id"])
    roi = str(project["label_classes"][1]["id"])
    image_id = _image(client, project["id"], index=2)
    _save_masks(
        client,
        image_id,
        [
            _polygon(str(uuid4()), target, [(1, 1), (4, 1), (4, 4), (1, 4)]),
            _polygon(str(uuid4()), target, [(3, 1), (6, 1), (6, 4), (3, 4)]),
            _polygon(str(uuid4()), roi, [(0, 0), (4, 0), (4, 4), (0, 4)]),
        ],
    )
    calibrated = client.put(
        f"/api/v1/images/{image_id}/measurement-calibration",
        json={"distance_per_pixel": 0.5, "unit": "cm", "source": "synthetic ruler"},
    )
    assert calibrated.status_code == 200, calibrated.text
    definition = _definition(client, project["id"], target, roi_label=roi)

    response = _preview(client, project["id"], definition["id"], [image_id])

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["roi_denominator_pixels"] == 25
    assert payload["target_union_in_roi_pixels"] == 16
    assert payload["roi_coverage_percent"] == pytest.approx(64.0)
    assert payload["density_object_count"] == 2
    assert payload["physical_unit"] == "cm"
    assert payload["union_area_physical"] == pytest.approx(6.0)
    assert payload["area_by_class"][0]["union_area_physical"] == pytest.approx(6.0)
    assert payload["area_by_class"][0]["physical_unit"] == "cm"
    assert payload["sampling_area_physical"] == pytest.approx(6.25)
    assert payload["object_density_per_square_unit"] == pytest.approx(0.32)
    assert payload["calibration_method"] == "scalar_distance_per_pixel"


def test_roi_density_counts_only_masks_intersecting_the_sampling_region(
    client: TestClient,
) -> None:
    project = create_project(client, "ROI density numerator")
    target = str(project["label_classes"][0]["id"])
    roi = str(project["label_classes"][1]["id"])
    image_id = _image(client, project["id"], index=21)
    _save_masks(
        client,
        image_id,
        [
            _polygon(str(uuid4()), target, [(7, 7), (9, 7), (9, 9), (7, 9)]),
            _polygon(str(uuid4()), roi, [(0, 0), (4, 0), (4, 4), (0, 4)]),
        ],
    )
    calibrated = client.put(
        f"/api/v1/images/{image_id}/measurement-calibration",
        json={"distance_per_pixel": 1, "unit": "cm", "source": "synthetic ruler"},
    )
    assert calibrated.status_code == 200, calibrated.text
    definition = _definition(client, project["id"], target, roi_label=roi)

    payload = _preview(client, project["id"], definition["id"], [image_id]).json()

    assert payload["mask_count"] == 1
    assert payload["density_object_count"] == 0
    assert payload["roi_denominator_pixels"] == 25
    assert payload["target_union_in_roi_pixels"] == 0
    assert payload["object_density_per_square_unit"] == 0


def test_true_zero_can_persist_but_missing_roi_denominator_fails(client: TestClient) -> None:
    project = create_project(client, "Zero mask cover")
    target = str(project["label_classes"][0]["id"])
    roi = str(project["label_classes"][1]["id"])
    image_id = _image(client, project["id"], index=3)
    _save_masks(client, image_id, [])
    definition = _definition(client, project["id"], target)

    calculated = client.post(
        f"/api/v1/projects/{project['id']}/computed-mask-coverage-definitions/"
        f"{definition['id']}/calculate",
        json={"image_ids": [image_id]},
    )
    assert calculated.status_code == 201, calculated.text
    assert calculated.json()["union_area_pixels"] == 0
    assert calculated.json()["image_coverage_percent"] == 0

    roi_definition = _definition(client, project["id"], target, roi_label=roi)
    missing = _preview(client, project["id"], roi_definition["id"], [image_id])
    assert missing.status_code == 400
    assert "roi" in missing.json()["detail"].lower()


def test_projective_or_missing_calibration_leaves_physical_values_unavailable(
    client: TestClient,
) -> None:
    project = create_project(client, "Unavailable physical union")
    target = str(project["label_classes"][0]["id"])
    image_id = _image(client, project["id"], index=4)
    _save_masks(
        client,
        image_id,
        [_polygon(str(uuid4()), target, [(1, 1), (4, 1), (4, 4), (1, 4)])],
    )
    definition = _definition(client, project["id"], target)

    missing = _preview(client, project["id"], definition["id"], [image_id]).json()
    assert missing["union_area_physical"] is None
    assert missing["physical_unavailable_reason"] == "missing_calibration"

    calibrated = client.put(
        f"/api/v1/images/{image_id}/measurement-calibration",
        json={
            "distance_per_pixel": 0.5,
            "unit": "cm",
            "source": "synthetic plane",
            "perspective_homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        },
    )
    assert calibrated.status_code == 200, calibrated.text
    projective = _preview(client, project["id"], definition["id"], [image_id]).json()
    assert projective["union_area_physical"] is None
    assert projective["physical_unavailable_reason"] == (
        "perspective_homography_requires_union_resampling"
    )


def test_group_summary_pools_pixel_denominators_instead_of_averaging_percentages(
    client: TestClient,
) -> None:
    project = create_project(client, "Pooled coverage group")
    target = str(project["label_classes"][0]["id"])
    first = _image(client, project["id"], index=5)
    second_report = import_one(
        client,
        project["id"],
        filename="coverage-6.png",
        relative_path="coverage/coverage-6.png",
        size=(20, 10),
    )
    second = str(second_report["successful"][0]["image_id"])
    _save_masks(
        client,
        first,
        [_polygon(str(uuid4()), target, [(0, 0), (4, 0), (4, 9), (0, 9)])],
        group_key="colony-a",
    )
    _save_masks(
        client,
        second,
        [_polygon(str(uuid4()), target, [(0, 0), (9, 0), (9, 9), (0, 9)])],
        group_key="colony-a",
    )
    definition = _definition(
        client,
        project["id"],
        target,
        grouping_level="image_group_key",
    )

    payload = _preview(client, project["id"], definition["id"], [first, second]).json()

    assert payload["independent_unit_count"] == 1
    assert payload["union_area_pixels"] == 150
    assert payload["image_denominator_pixels"] == 300
    assert payload["image_coverage_percent"] == pytest.approx(50.0)
    assert payload["groups"][0]["unit_key"] == "colony-a"
    assert payload["groups"][0]["image_coverage_percent"] == pytest.approx(50.0)


def test_saved_result_validation_and_csv_preserve_evidence(client: TestClient) -> None:
    project = create_project(client, "Coverage evidence")
    target = str(project["label_classes"][0]["id"])
    image_id = _image(client, project["id"], index=7)
    _save_masks(
        client,
        image_id,
        [_polygon(str(uuid4()), target, [(1, 1), (4, 1), (4, 4), (1, 4)])],
    )
    definition = _definition(client, project["id"], target)
    calculated = client.post(
        f"/api/v1/projects/{project['id']}/computed-mask-coverage-definitions/"
        f"{definition['id']}/calculate",
        json={"image_ids": [image_id]},
    )
    assert calculated.status_code == 201, calculated.text
    result = calculated.json()
    assert result["result_kind"] == "mask_coverage"
    validation_url = (
        f"/api/v1/projects/{project['id']}/computed-mask-coverage-results/{result['id']}/validation"
    )
    current = client.get(validation_url)
    assert current.status_code == 200, current.text
    assert current.json()["current"] is True

    exported = client.get(f"/api/v1/projects/{project['id']}/computed-mask-coverage-results.csv")
    assert exported.status_code == 200, exported.text
    assert "union_area_pixels" in exported.text
    assert result["evidence_sha256"] in exported.text

    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        mask = session.query(MaskAnnotation).filter_by(image_id=image_id).one()
        mask.revision += 1
        image = session.get(ImageAsset, image_id)
        assert image is not None
        image.annotation_revision += 1
        label = session.get(LabelClass, target)
        assert label is not None
        label.name = "Renamed coral state"
        session.commit()

    stale = client.get(validation_url)
    assert stale.status_code == 200, stale.text
    assert stale.json()["current"] is False
    assert stale.json()["reasons"] == [
        "evidence_snapshot_changed",
        "result_summary_mismatch",
    ]


def test_missing_verified_raster_content_fails_closed(client: TestClient) -> None:
    project = create_project(client, "Missing raster coverage")
    target = str(project["label_classes"][0]["id"])
    image_id = _image(client, project["id"], index=8)
    _save_masks(
        client,
        image_id,
        [_polygon(str(uuid4()), target, [(1, 1), (4, 1), (4, 4), (1, 4)])],
    )
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        mask = session.query(MaskAnnotation).filter_by(image_id=image_id).one()
        mask.geometry_kind = "raster_mask"
        mask.polygon_json = None
        mask.mask_path = None
        mask.revision += 1
        session.commit()
    definition = _definition(client, project["id"], target)

    response = _preview(client, project["id"], definition["id"], [image_id])

    assert response.status_code == 400
    assert "content is missing" in response.json()["detail"].lower()


def test_source_sized_raster_mask_uses_exact_nonzero_pixel_union(
    client: TestClient, test_settings
) -> None:
    project = create_project(client, "Raster union coverage")
    target = str(project["label_classes"][0]["id"])
    image_id = _image(client, project["id"], index=81)
    reviewed = client.patch(
        f"/api/v1/images/{image_id}",
        json={"annotation_status": "reviewed", "group_key": None},
    )
    assert reviewed.status_code == 200, reviewed.text
    relative_path = f"{project['storage_root']}/masks/exact-coverage.png"
    absolute_path = test_settings.resolved_data_dir / relative_path
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    raster = Image.new("L", (10, 10), 0)
    for point in ((1, 1), (2, 1), (1, 2)):
        raster.putpixel(point, 255)
    raster.save(absolute_path, format="PNG")
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        session.add(
            MaskAnnotation(
                image_id=image_id,
                label_class_id=target,
                geometry_kind="raster_mask",
                mask_path=relative_path,
                x_min=1,
                y_min=1,
                x_max=3,
                y_max=3,
                area_pixels=3,
                source_type="human",
                status="verified",
            )
        )
        image = session.get(ImageAsset, image_id)
        assert image is not None
        image.annotation_revision += 1
        session.commit()
    definition = _definition(client, project["id"], target)

    payload = _preview(client, project["id"], definition["id"], [image_id]).json()

    assert payload["summed_mask_area_pixels"] == 3
    assert payload["union_area_pixels"] == 3
    assert payload["image_coverage_percent"] == pytest.approx(3)
    assert len(payload["mask_snapshot"][0]["mask_content_sha256"]) == 64


def test_compatible_mixed_calibration_units_normalize_physical_aggregate(
    client: TestClient,
) -> None:
    project = create_project(client, "Mixed-unit coverage")
    target = str(project["label_classes"][0]["id"])
    first = _image(client, project["id"], index=9)
    second_report = import_one(
        client,
        project["id"],
        filename="coverage-mixed-10.png",
        relative_path="coverage/coverage-mixed-10.png",
        size=(11, 10),
    )
    second = str(second_report["successful"][0]["image_id"])
    for image_id in (first, second):
        _save_masks(
            client,
            image_id,
            [_polygon(str(uuid4()), target, [(1, 1), (4, 1), (4, 4), (1, 4)])],
        )
    for image_id, unit in ((first, "cm"), (second, "mm")):
        calibrated = client.put(
            f"/api/v1/images/{image_id}/measurement-calibration",
            json={"distance_per_pixel": 0.5, "unit": unit, "source": "synthetic ruler"},
        )
        assert calibrated.status_code == 200, calibrated.text
    definition = _definition(client, project["id"], target)

    payload = _preview(client, project["id"], definition["id"], [first, second]).json()

    assert payload["union_area_pixels"] == 32
    assert all(item["union_area_physical"] == 4 for item in payload["images"])
    assert payload["physical_unit"] == "m"
    assert payload["union_area_physical"] == pytest.approx(0.000404)
    assert payload["sampling_area_physical"] == pytest.approx(0.0025275)
    assert payload["physical_unavailable_reason"] is None


def test_unknown_calibration_unit_never_fabricates_physical_area(client: TestClient) -> None:
    project = create_project(client, "Unknown-unit coverage")
    target = str(project["label_classes"][0]["id"])
    image_id = _image(client, project["id"], index=11)
    _save_masks(
        client,
        image_id,
        [_polygon(str(uuid4()), target, [(1, 1), (4, 1), (4, 4), (1, 4)])],
    )
    calibrated = client.put(
        f"/api/v1/images/{image_id}/measurement-calibration",
        json={"distance_per_pixel": 0.5, "unit": "unknown", "source": "legacy metadata"},
    )
    assert calibrated.status_code == 200, calibrated.text
    definition = _definition(client, project["id"], target)

    payload = _preview(client, project["id"], definition["id"], [image_id]).json()

    assert payload["union_area_pixels"] == 16
    assert payload["union_area_physical"] is None
    assert payload["physical_unit"] is None
    assert payload["physical_unavailable_reason"] == "unsupported_calibration_unit"
