from reefvision.domain.annotation_comparison import (
    BoxEvidence,
    compare_box_evidence,
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
