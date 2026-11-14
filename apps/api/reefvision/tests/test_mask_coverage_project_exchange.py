from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from reefvision.db.models import ImageAsset, MaskAnnotation
from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.services.scientific_data import content_hash
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_computed_mask_coverage import (
    _definition,
    _image,
    _polygon,
    _save_masks,
)
from reefvision.tests.test_scientific_project_exchange import (
    database_counts,
    export_archive,
    import_archive,
    rewrite,
)
from reefvision.tests.test_workflow_computed_metrics import save_and_queue
from reefvision.tests.test_workflow_mask_coverage import mask_coverage_graph


@pytest.mark.parametrize("mode", ["legacy", "polygon", "projective", "invalid_projection"])
def test_mask_coverage_round_trip_remaps_immutable_evidence(
    client: TestClient, test_settings, mode: str
) -> None:
    project = create_project(client, "Portable mask coverage")
    target = str(project["label_classes"][0]["id"])
    image_id = _image(client, project["id"], index=41)
    mask_ids = [str(uuid4()), str(uuid4())]
    _save_masks(
        client,
        image_id,
        [
            _polygon(mask_ids[0], target, [(1, 1), (4, 1), (4, 4), (1, 4)]),
            _polygon(mask_ids[1], target, [(3, 1), (6, 1), (6, 4), (3, 4)]),
        ],
        group_key=project["id"],
    )
    projective = mode in {"projective", "invalid_projection"}
    with_polygon = mode != "legacy"
    calibration = {"distance_per_pixel": 0.5, "unit": "cm", "source": "synthetic ruler"}
    if projective:
        calibration["perspective_homography"] = [
            [0.5, 0, 0],
            [0, 0.5, 0],
            [-1 if mode == "invalid_projection" else 0, 0, 1],
        ]
    calibrated = client.put(
        f"/api/v1/images/{image_id}/measurement-calibration",
        json=calibration,
    )
    assert calibrated.status_code == 200, calibrated.text
    points = [[0, 0], [4, 0], [4, 4], [0, 4]]
    response = client.post(
        f"/api/v1/projects/{project['id']}/computed-mask-coverage-definitions",
        json={
            "name": "Portable coverage",
            "grouping_level": "image_group_key",
            "label_class_ids": [target],
            "use_reference_plane": projective,
            **(
                {"roi_polygons": [{"image_id": image_id, "points": points}]} if with_polygon else {}
            ),
        },
    )
    assert response.status_code == 201, response.text
    definition = response.json()
    run = save_and_queue(
        client,
        project["id"],
        mask_coverage_graph(definition["id"], [image_id]),
    )
    app = client.app
    assert isinstance(app, FastAPI)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run["job_id"])
    )
    source_result = client.get(
        f"/api/v1/projects/{project['id']}/computed-mask-coverage-results"
    ).json()["items"][0]

    imported = import_archive(client, export_archive(client, test_settings, project["id"]))

    assert imported.status_code == 201, imported.text
    imported_project_id = imported.json()["project_id"]
    restored_definition = client.get(
        f"/api/v1/projects/{imported_project_id}/computed-mask-coverage-definitions"
    ).json()["items"][0]
    restored_result = client.get(
        f"/api/v1/projects/{imported_project_id}/computed-mask-coverage-results"
    ).json()["items"][0]
    assert restored_definition["id"] != definition["id"]
    assert restored_result["id"] != source_result["id"]
    assert restored_result["definition_id"] == restored_definition["id"]
    assert restored_result["union_area_pixels"] == source_result["union_area_pixels"] == 24
    if mode == "invalid_projection":
        assert restored_result["union_area_physical"] is None
        assert (
            restored_result["physical_unavailable_reason"] == "invalid_reference_plane_projection"
        )
    else:
        assert restored_result["union_area_physical"] == source_result["union_area_physical"] == 6
        assert restored_result["physical_unit"] == "cm"
    assert restored_result["groups"][0]["unit_key"] == project["id"]
    assert restored_result["image_snapshot"][0]["image_id"] != image_id
    if with_polygon:
        restored_image = restored_result["image_snapshot"][0]
        assert restored_definition["roi_polygons"] == [
            {"image_id": restored_image["image_id"], "points": points}
        ]
        assert restored_image["roi_polygon"] == points
        assert restored_result["roi_denominator_pixels"] == 25
        assert restored_result["target_union_in_roi_pixels"] == 16
        assert restored_result["roi_coverage_percent"] == 64
        if mode == "projective":
            assert restored_result["roi_coverage_physical_percent"] == 64
            assert restored_result["target_union_in_roi_physical"] == 4
        csv = client.get(
            f"/api/v1/projects/{imported_project_id}/computed-mask-coverage-results.csv"
        )
        assert csv.status_code == 200, csv.text
        assert "source_image_polygons" in csv.text
    assert {item["id"] for item in restored_result["mask_snapshot"]}.isdisjoint(mask_ids)
    assert restored_result["workflow_run_id"] not in (None, source_result["workflow_run_id"])
    assert restored_result["workflow_node_run_id"] not in (
        None,
        source_result["workflow_node_run_id"],
    )
    validation = client.get(
        f"/api/v1/projects/{imported_project_id}/computed-mask-coverage-results/"
        f"{restored_result['id']}/validation"
    )
    assert validation.status_code == 200, validation.text
    assert validation.json()["current"] is True
    restored_run = client.get(f"/api/v1/workflow-runs/{restored_result['workflow_run_id']}").json()
    restored_artifact = next(
        item for item in restored_run["artifacts"] if item["data_type"] == "computed_metric_result"
    )["payload_json"]
    assert restored_artifact["evidence_sha256"] == restored_result["evidence_sha256"]
    assert restored_artifact["content_sha256"] == restored_result["content_sha256"]
    if with_polygon:
        graphs = client.get(f"/api/v1/projects/{imported_project_id}/workflow-graphs").json()
        replay = client.post(
            f"/api/v1/projects/{imported_project_id}/workflow-runs",
            json={"graph_record_id": graphs[0]["id"]},
        )
        assert replay.status_code == 202, replay.text
        assert process_workflow_run_job(
            app.state.settings, app.state.session_factory, replay.json()["job_id"]
        )
        detail = client.get(f"/api/v1/workflow-runs/{replay.json()['id']}").json()
        artifact = next(
            item for item in detail["artifacts"] if item["data_type"] == "computed_metric_result"
        )
        assert artifact["payload_json"]["evidence_sha256"] == restored_result["evidence_sha256"]
        assert artifact["payload_json"]["content_sha256"] == restored_result["content_sha256"]


def test_mask_coverage_round_trip_preserves_invalid_calibration_snapshot(
    client: TestClient, test_settings
) -> None:
    project = create_project(client, "Portable invalid calibration")
    target = str(project["label_classes"][0]["id"])
    image_id = _image(client, project["id"], index=43)
    _save_masks(
        client,
        image_id,
        [_polygon(str(uuid4()), target, [(1, 1), (4, 1), (4, 4), (1, 4)])],
    )
    app = client.app
    assert isinstance(app, FastAPI)
    with app.state.session_factory() as session:
        image = session.get(ImageAsset, image_id)
        assert image is not None
        metadata = dict(image.metadata_json or {})
        metadata["measurement_calibration"] = {"unit": "cm"}
        image.metadata_json = metadata
        session.commit()
    definition = _definition(client, project["id"], target)
    calculated = client.post(
        f"/api/v1/projects/{project['id']}/computed-mask-coverage-definitions/"
        f"{definition['id']}/calculate",
        json={"image_ids": [image_id]},
    )
    assert calculated.status_code == 201, calculated.text
    assert calculated.json()["physical_unavailable_reason"] == "invalid_calibration"

    imported = import_archive(client, export_archive(client, test_settings, project["id"]))

    assert imported.status_code == 201, imported.text
    restored_project_id = imported.json()["project_id"]
    restored = client.get(
        f"/api/v1/projects/{restored_project_id}/computed-mask-coverage-results"
    ).json()["items"][0]
    assert restored["physical_unavailable_reason"] == "invalid_calibration"
    assert restored["image_snapshot"][0]["calibration"] == {"unit": "cm"}


@pytest.mark.parametrize("tampered", [False, True])
def test_mask_coverage_exchange_replays_historical_calibration(
    client: TestClient, test_settings, tampered: bool
) -> None:
    project = create_project(client, "Historical mask coverage")
    project_id = project["id"]
    target = project["label_classes"][0]["id"]
    image_id = _image(client, project_id, index=42)
    _save_masks(
        client,
        image_id,
        [_polygon(str(uuid4()), target, [(1, 1), (4, 1), (4, 4), (1, 4)])],
    )
    calibration = f"/api/v1/images/{image_id}/measurement-calibration"
    assert client.put(calibration, json={"distance_per_pixel": 0.5, "unit": "cm"}).is_success
    definition = _definition(client, project_id, target)
    calculated = client.post(
        f"/api/v1/projects/{project_id}/computed-mask-coverage-definitions/"
        f"{definition['id']}/calculate",
        json={"image_ids": [image_id]},
    )
    assert calculated.status_code == 201, calculated.text
    assert calculated.json()["union_area_pixels"] == 16
    assert client.put(calibration, json={"distance_per_pixel": 1, "unit": "cm"}).is_success
    raw = export_archive(client, test_settings, project_id)

    if tampered:

        def change(_manifest, sections):
            row = sections["computed_metric_results"][0]
            row["payload_json"]["union_area_physical"] = 999
            row["content_sha256"] = content_hash(row["payload_json"])

        before = database_counts(client)
        response = import_archive(client, rewrite(raw, change))
        assert response.status_code == 400, response.text
        assert "summary" in response.json()["detail"]
        assert database_counts(client) == before
        return

    imported = import_archive(client, raw)
    assert imported.status_code == 201, imported.text
    base = f"/api/v1/projects/{imported.json()['project_id']}/computed-mask-coverage-results"
    saved = client.get(base).json()["items"][0]
    assert saved["union_area_physical"] == 4
    assert saved["image_snapshot"][0]["calibration"]["distance_per_pixel"] == 0.5
    status = client.get(f"{base}/{saved['id']}/validation").json()
    assert status["current"] is False
    assert "evidence_snapshot_changed" in status["reasons"]


def test_mask_coverage_exchange_replays_packaged_raster(client: TestClient, test_settings) -> None:
    project = create_project(client, "Portable raster coverage")
    project_id = project["id"]
    target = project["label_classes"][0]["id"]
    image_id = _image(client, project_id, index=82)
    assert client.patch(
        f"/api/v1/images/{image_id}", json={"annotation_status": "reviewed"}
    ).is_success
    mask_relative = "masks/portable-coverage.png"
    mask_path = f"{project['storage_root']}/{mask_relative}"
    disk_path = test_settings.resolved_data_dir / mask_path
    disk_path.parent.mkdir(parents=True, exist_ok=True)
    raster = Image.new("L", (10, 10), 0)
    for point in ((1, 1), (2, 1), (1, 2)):
        raster.putpixel(point, 255)
    raster.save(disk_path, format="PNG")
    with client.app.state.session_factory() as session:
        session.add(
            MaskAnnotation(
                image_id=image_id,
                label_class_id=target,
                geometry_kind="raster_mask",
                mask_path=mask_path,
                x_min=1,
                y_min=1,
                x_max=3,
                y_max=3,
                area_pixels=3,
                source_type="human",
                status="verified",
            )
        )
        session.commit()
    definition = _definition(client, project_id, target)
    calculated = client.post(
        f"/api/v1/projects/{project_id}/computed-mask-coverage-definitions/"
        f"{definition['id']}/calculate",
        json={"image_ids": [image_id]},
    )
    assert calculated.status_code == 201, calculated.text
    raw = export_archive(client, test_settings, project_id, include_generated_artifacts=True)

    imported = import_archive(client, raw)
    assert imported.status_code == 201, imported.text
    new_project_id = imported.json()["project_id"]
    restored_project = client.get(f"/api/v1/projects/{new_project_id}").json()
    base = f"/api/v1/projects/{new_project_id}/computed-mask-coverage-results"
    saved = client.get(base).json()["items"][0]
    assert saved["union_area_pixels"] == 3
    new_mask_path = f"{restored_project['storage_root']}/{mask_relative}"
    assert new_mask_path != mask_path
    assert saved["mask_snapshot"][0]["mask_path"] == new_mask_path
    assert (test_settings.resolved_data_dir / new_mask_path).read_bytes() == disk_path.read_bytes()
    assert client.get(f"{base}/{saved['id']}/validation").json()["current"]

    def redirect_mask(_manifest, sections):
        # Point both records at the original project's still-existing raster.
        # A parent component survives the old source-prefix substitution.
        source_name = project["storage_root"].split("/")[-1]
        foreign = f"{project['storage_root']}/../{source_name}/{mask_relative}"
        sections["mask_annotations"][0]["mask_path"] = foreign
        row = sections["computed_metric_results"][0]
        payload = row["payload_json"]
        payload["mask_snapshot"][0]["mask_path"] = foreign
        payload["evidence_sha256"] = content_hash(
            {
                "definition_sha256": payload["definition_sha256"],
                "algorithm": payload["algorithm"],
                "coordinate_frame": payload["coordinate_frame"],
                "images": payload["image_snapshot"],
                "masks": payload["mask_snapshot"],
            }
        )
        payload["provenance"]["evidence_sha256"] = payload["evidence_sha256"]
        row["content_sha256"] = content_hash(payload)

    before = database_counts(client)
    forged = import_archive(client, rewrite(raw, redirect_mask))
    assert forged.status_code == 400, forged.text
    assert database_counts(client) == before


@pytest.mark.parametrize("corruption", ["summary", "mask_evidence"])
def test_mask_coverage_exchange_rejects_rehashed_corruption_atomically(
    client: TestClient, test_settings, corruption: str
) -> None:
    project = create_project(client, "Corrupt portable mask coverage")
    target = str(project["label_classes"][0]["id"])
    image_id = _image(client, project["id"], index=42)
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
    raw = export_archive(client, test_settings, project["id"])

    def change(_manifest, sections) -> None:
        result = next(
            row
            for row in sections["computed_metric_results"]
            if row.get("result_kind") == "mask_coverage"
        )
        payload = result["payload_json"]
        if corruption == "summary":
            payload["union_area_pixels"] = 999
        else:
            payload["mask_snapshot"][0]["area_pixels"] = 999
            payload["evidence_sha256"] = content_hash(
                {
                    "definition_sha256": payload["definition_sha256"],
                    "algorithm": payload["algorithm"],
                    "coordinate_frame": payload["coordinate_frame"],
                    "images": payload["image_snapshot"],
                    "masks": payload["mask_snapshot"],
                }
            )
            payload["provenance"]["evidence_sha256"] = payload["evidence_sha256"]
        result["content_sha256"] = content_hash(payload)

    before = database_counts(client)
    response = import_archive(client, rewrite(raw, change))
    assert response.status_code == 400, response.text
    assert database_counts(client) == before
