from uuid import uuid4

import pytest
from sqlalchemy import select

from reefvision.db.models import Job, MaskAnnotation, ModelRegistration, PredictionProposal
from reefvision.db.models.computed_metric import ComputedMetricResult
from reefvision.domain.annotation_comparison import (
    BoxEvidence,
    MaskEvidence,
    compare_box_evidence,
    compare_mask_evidence,
)
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_scientific_project_exchange import export_archive, import_archive


def box(
    evidence_id: str,
    *,
    image_id: str = "image-1",
    class_id: str = "fish",
    bounds: tuple[float, float, float, float] = (0.0, 0.0, 10.0, 10.0),
) -> BoxEvidence:
    return BoxEvidence(evidence_id, image_id, class_id, bounds)


def test_comparison_is_class_aware_and_stably_one_to_one() -> None:
    source_a = [box("a-2"), box("a-1")]
    source_b = [box("b-2"), box("b-1"), box("b-wrong", class_id="coral")]

    result = compare_box_evidence(source_a, source_b, iou_threshold=0.5)

    fish = result.per_class["fish"]
    assert [(item.source_a_id, item.source_b_id) for item in fish.matches] == [
        ("a-1", "b-1"),
        ("a-2", "b-2"),
    ]
    assert fish.unmatched_a_ids == ()
    assert fish.unmatched_b_ids == ()
    assert result.per_class["coral"].unmatched_b_ids == ("b-wrong",)


def test_comparison_reports_count_differences_and_undefined_reference_percent() -> None:
    result = compare_box_evidence(
        [],
        [box("b-1")],
        iou_threshold=0.5,
        reference_side="a",
    )

    fish = result.per_class["fish"]
    assert fish.count_a == 0
    assert fish.count_b == 1
    assert fish.signed_count_difference_b_minus_a == 1
    assert fish.absolute_count_difference == 1
    assert fish.reference_relative_percent_difference is None
    assert fish.reference_relative_percent_reason == "zero_reference_count"
    assert fish.false_positive_ids == ("b-1",)
    assert fish.false_negative_ids == ()


def test_comparison_uses_neutral_unmatched_terms_without_reference() -> None:
    result = compare_box_evidence(
        [box("a-1")],
        [box("b-1", bounds=(100.0, 100.0, 110.0, 110.0))],
        iou_threshold=0.5,
    )

    fish = result.per_class["fish"]
    assert fish.unmatched_a_ids == ("a-1",)
    assert fish.unmatched_b_ids == ("b-1",)
    assert fish.false_positive_ids is None
    assert fish.false_negative_ids is None


def test_comparison_matches_only_within_same_image() -> None:
    result = compare_box_evidence(
        [box("a-1", image_id="one")],
        [box("b-1", image_id="two")],
        iou_threshold=0.5,
        reference_side="b",
    )

    fish = result.per_class["fish"]
    assert fish.matches == ()
    assert fish.false_positive_ids == ("a-1",)
    assert fish.false_negative_ids == ("b-1",)


def test_comparison_rejects_invalid_geometry_and_duplicate_ids() -> None:
    try:
        box("bad", bounds=(10.0, 0.0, 0.0, 10.0))
    except ValueError as exc:
        assert "positive area" in str(exc)
    else:
        raise AssertionError("invalid box accepted")

    duplicate = box("same")
    try:
        compare_box_evidence([duplicate, duplicate], [], iou_threshold=0.5)
    except ValueError as exc:
        assert "unique" in str(exc)
    else:
        raise AssertionError("duplicate evidence accepted")


def test_mask_comparison_uses_exact_pixels_and_class_union_disagreement() -> None:
    source_a = [
        MaskEvidence("a-1", "image", "fish", 10, 10, ((0, 0, 3), (1, 0, 3))),
        MaskEvidence("a-2", "image", "fish", 10, 10, ((0, 2, 5),)),
    ]
    source_b = [
        MaskEvidence("b-1", "image", "fish", 10, 10, ((0, 1, 4), (1, 0, 3))),
    ]

    result = compare_mask_evidence(source_a, source_b, iou_threshold=0.5, reference_side="a")
    fish = result.per_class["fish"]

    assert [(item.source_a_id, item.source_b_id) for item in fish.matches] == [("a-1", "b-1")]
    assert fish.matches[0].iou == pytest.approx(5 / 7)
    assert fish.unmatched_a_ids == ("a-2",)
    assert fish.false_negative_ids == ("a-2",)
    assert fish.false_positive_ids == ()
    # Overlapping A masks are unioned, not double counted.
    assert fish.union_area_a_pixels == 8
    assert fish.union_area_b_pixels == 6
    assert fish.intersection_area_pixels == 6
    assert fish.symmetric_difference_area_pixels == 2
    assert fish.disagreement_runs == ((0, 0, 1), (0, 4, 5))


def test_mask_comparison_separates_classes_and_reports_empty_reference() -> None:
    result = compare_mask_evidence(
        [],
        [MaskEvidence("b", "image", "coral", 2, 2, ((0, 0, 1),))],
        iou_threshold=0.5,
        reference_side="a",
    )
    coral = result.per_class["coral"]
    assert coral.reference_relative_percent_difference is None
    assert coral.reference_relative_percent_reason == "zero_reference_count"
    assert coral.false_positive_ids == ("b",)
    assert coral.union_iou == 0


def test_mask_comparison_rejects_incompatible_dimensions_and_empty_masks() -> None:
    with pytest.raises(ValueError, match="occupied"):
        MaskEvidence("empty", "image", "fish", 2, 2, ())
    with pytest.raises(ValueError, match="dimensions"):
        compare_mask_evidence(
            [MaskEvidence("a", "image", "fish", 2, 2, ((0, 0, 1),))],
            [MaskEvidence("b", "image", "fish", 3, 2, ((0, 0, 1),))],
            iou_threshold=0.5,
        )


def test_verified_mask_comparison_preview_and_persistence(client, test_settings) -> None:
    project = create_project(client, "Mask comparison")
    class_id = project["label_classes"][0]["id"]
    report = import_one(
        client,
        project["id"],
        filename="mask-comparison.png",
        relative_path="mask-comparison.png",
        size=(10, 10),
    )
    image_id = report["successful"][0]["image_id"]
    first_id, second_id = str(uuid4()), str(uuid4())
    saved = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [],
            "mask_annotations": [
                {
                    "id": first_id,
                    "label_class_id": class_id,
                    "geometry_kind": "polygon",
                    "points": [
                        {"x": 1, "y": 1},
                        {"x": 4, "y": 1},
                        {"x": 4, "y": 4},
                        {"x": 1, "y": 4},
                    ],
                },
                {
                    "id": second_id,
                    "label_class_id": class_id,
                    "geometry_kind": "polygon",
                    "points": [
                        {"x": 2, "y": 1},
                        {"x": 5, "y": 1},
                        {"x": 5, "y": 4},
                        {"x": 2, "y": 4},
                    ],
                },
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    request = {
        "image_id": image_id,
        "geometry_kind": "masks",
        "source_a": {"kind": "verified_masks", "mask_annotation_ids": [first_id]},
        "source_b": {"kind": "verified_masks", "mask_annotation_ids": [second_id]},
        "reference_side": "a",
        "iou_threshold": 0.5,
    }

    preview = client.post(
        f"/api/v1/projects/{project['id']}/annotation-comparisons/preview", json=request
    )

    assert preview.status_code == 200, preview.text
    payload = preview.json()
    assert payload["algorithm"] == "reefvision.class-aware-mask-comparison.v1"
    assert payload["geometry_kind"] == "masks"
    class_result = payload["per_class"][class_id]
    assert class_result["matched_count"] == 1
    assert class_result["union_iou"] == pytest.approx(0.6)
    assert class_result["symmetric_difference_area_pixels"] == 8
    assert len(payload["source_a_sha256"]) == 64

    calculated = client.post(
        f"/api/v1/projects/{project['id']}/annotation-comparisons/calculate",
        json={**request, "name": "Explicit verified-mask comparison"},
    )
    assert calculated.status_code == 201, calculated.text
    result = calculated.json()
    assert result["comparison"]["content_sha256"] == payload["content_sha256"]
    fetched = client.get(
        f"/api/v1/projects/{project['id']}/annotation-comparisons/{result['result_id']}"
    )
    assert fetched.status_code == 200, fetched.text
    current = client.get(
        f"/api/v1/projects/{project['id']}/annotation-comparisons/"
        f"{result['result_id']}/validation"
    )
    assert current.status_code == 200, current.text
    assert current.json()["is_current"] is True
    exported = client.get(
        f"/api/v1/projects/{project['id']}/annotation-comparisons/"
        f"{result['result_id']}/export.csv"
    )
    assert exported.status_code == 200, exported.text
    assert "symmetric_difference_area_pixels" in exported.text
    assert result["comparison"]["content_sha256"] in exported.text

    archive = export_archive(client, test_settings, project["id"])
    imported = import_archive(client, archive)
    assert imported.status_code == 201, imported.text
    imported_project_id = imported.json()["project_id"]
    with client.app.state.session_factory() as session:
        imported_result = session.scalar(
            select(ComputedMetricResult).where(
                ComputedMetricResult.project_id == imported_project_id,
                ComputedMetricResult.result_kind == "annotation_comparison",
            )
        )
        assert imported_result is not None
        imported_result_id = imported_result.id
    imported_saved = client.get(
        f"/api/v1/projects/{imported_project_id}/annotation-comparisons/{imported_result_id}"
    )
    assert imported_saved.status_code == 200, imported_saved.text
    imported_comparison = imported_saved.json()["comparison"]
    assert imported_comparison["image_id"] != image_id
    assert class_id not in imported_comparison["per_class"]
    assert imported_comparison["source_a_snapshot"][0]["evidence_id"] != first_id
    imported_current = client.get(
        f"/api/v1/projects/{imported_project_id}/annotation-comparisons/"
        f"{imported_result_id}/validation"
    )
    assert imported_current.status_code == 200, imported_current.text
    assert imported_current.json()["is_current"] is True

    with client.app.state.session_factory() as session:
        changed = session.get(MaskAnnotation, first_id)
        assert changed is not None
        changed.polygon_json = [[0, 0], [2, 0], [2, 2], [0, 2]]
        changed.revision += 1
        session.commit()
    stale = client.get(
        f"/api/v1/projects/{project['id']}/annotation-comparisons/"
        f"{result['result_id']}/validation"
    )
    assert stale.status_code == 200, stale.text
    assert stale.json()["is_current"] is False
    assert stale.json()["reasons"] == ["source_snapshot_changed"]


def test_mask_comparison_rejects_overlapping_source_inventory(client) -> None:
    shared_id = str(uuid4())
    response = client.post(
        f"/api/v1/projects/{uuid4()}/annotation-comparisons/preview",
        json={
            "image_id": str(uuid4()),
            "geometry_kind": "masks",
            "source_a": {"kind": "verified_masks", "mask_annotation_ids": [shared_id]},
            "source_b": {"kind": "verified_masks", "mask_annotation_ids": [shared_id]},
        },
    )
    assert response.status_code == 422


def test_verified_mask_can_compare_with_pinned_prediction_mask(client) -> None:
    project = create_project(client, "Pinned mask comparison")
    class_id = project["label_classes"][0]["id"]
    report = import_one(
        client,
        project["id"],
        filename="pinned-mask.png",
        relative_path="pinned-mask.png",
        size=(10, 10),
    )
    image_id = report["successful"][0]["image_id"]
    mask_id, job_id, model_id = str(uuid4()), str(uuid4()), str(uuid4())
    saved = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [],
            "mask_annotations": [
                {
                    "id": mask_id,
                    "label_class_id": class_id,
                    "geometry_kind": "polygon",
                    "points": [
                        {"x": 1, "y": 1},
                        {"x": 4, "y": 1},
                        {"x": 4, "y": 4},
                        {"x": 1, "y": 4},
                    ],
                }
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    with client.app.state.session_factory() as session:
        session.add(
            Job(
                id=job_id,
                project_id=project["id"],
                job_type="inference",
                status="succeeded",
                progress_total=1,
                progress_current=1,
                request_json={"task": "segment"},
            )
        )
        session.add(
            ModelRegistration(
                id=model_id,
                project_id=project["id"],
                purpose="assist",
                display_name="Pinned segmentation model",
                source_filename="segment.pt",
                managed_path=f"{project['storage_root']}/models/{model_id}.pt",
                sha256="c" * 64,
                file_size_bytes=1,
                framework="ultralytics",
                task="segment",
                provider_name="ultralytics",
                provider_version="8.3.228",
                class_map_json={},
                metadata_json={},
            )
        )
        session.flush()
        session.add(
            PredictionProposal(
                project_id=project["id"],
                image_id=image_id,
                model_id=model_id,
                inference_job_id=job_id,
                model_checksum="c" * 64,
                label_class_id=class_id,
                predicted_label="coral",
                confidence=0.9,
                geometry_kind="polygon_mask",
                polygon_json=[[1, 1], [4, 1], [4, 4], [1, 4]],
                x_min=1,
                y_min=1,
                x_max=4,
                y_max=4,
                review_status="evaluation_only",
                inference_settings_json={"imgsz": 640},
                provenance_json={"evaluation_only": True},
            )
        )
        session.commit()

    response = client.post(
        f"/api/v1/projects/{project['id']}/annotation-comparisons/preview",
        json={
            "image_id": image_id,
            "geometry_kind": "masks",
            "source_a": {"kind": "verified_masks", "mask_annotation_ids": [mask_id]},
            "source_b": {"kind": "prediction_job", "prediction_job_id": job_id},
            "reference_side": "a",
            "iou_threshold": 0.5,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["per_class"][class_id]["union_iou"] == 1
    assert payload["source_b_snapshot"][0]["model_checksum"] == "c" * 64
    assert payload["source_b_snapshot"][0]["prediction_job_id"] == job_id


def test_reviewed_box_comparison_preview_is_project_scoped_and_hashed(
    client, test_settings
) -> None:
    project = create_project(client, "Comparison preview")
    image_id = import_one(client, project["id"])["successful"][0]["image_id"]
    annotation_id = "11111111-1111-4111-8111-111111111111"
    saved = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={
            "base_revision": 0,
            "annotation_status": "reviewed",
            "annotations": [
                {
                    "id": annotation_id,
                    "label_class_id": project["label_classes"][0]["id"],
                    "x_min": 2,
                    "y_min": 3,
                    "x_max": 12,
                    "y_max": 13,
                }
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    payload = {
        "image_id": image_id,
        "source_a": {"kind": "reviewed_boxes"},
        "source_b": {"kind": "reviewed_boxes"},
        "reference_side": None,
        "iou_threshold": 0.5,
    }

    response = client.post(
        f"/api/v1/projects/{project['id']}/annotation-comparisons/preview",
        json=payload,
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["algorithm"] == "reefvision.class-aware-box-comparison.v1"
    assert result["source_a_snapshot"][0]["evidence_id"] == annotation_id
    assert result["source_a_sha256"] == result["source_b_sha256"]
    assert len(result["content_sha256"]) == 64
    class_result = next(iter(result["per_class"].values()))
    assert class_result["matched_count"] == 1
    assert "reviewer" in " ".join(result["methodological_notes"]).lower()

    other = create_project(client, "Other comparison project")
    wrong = client.post(
        f"/api/v1/projects/{other['id']}/annotation-comparisons/preview",
        json=payload,
    )
    assert wrong.status_code == 404

    saved = client.post(
        f"/api/v1/projects/{project['id']}/annotation-comparisons/calculate",
        json={"name": "Reviewed self-check", **payload},
    )
    assert saved.status_code == 201, saved.text
    saved_body = saved.json()
    assert len(saved_body["definition_sha256"]) == 64
    assert len(saved_body["result_sha256"]) == 64
    assert saved_body["comparison"]["content_sha256"] == result["content_sha256"]

    archive = export_archive(client, test_settings, project["id"])
    imported = import_archive(client, archive)
    assert imported.status_code == 201, imported.text
    assert imported.json()["imported_counts"]["computed_metric_definitions"] == 1
    assert imported.json()["imported_counts"]["computed_metric_results"] == 1
