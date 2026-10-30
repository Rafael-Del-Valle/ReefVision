"""Content-addressed, provisional review provenance for longitudinal meshes."""

from __future__ import annotations

from hashlib import sha256
from json import dumps
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reefvision.jobs.workflow import process_workflow_run_job
from reefvision.schemas.spatial_mesh_preview_v14 import MeshPreviewRequest
from reefvision.services.spatial_mesh_longitudinal_v14 import compare_mesh_observations
from reefvision.services.spatial_mesh_surface_v14 import preview_from_request
from reefvision.tests.test_annotations import create_project


def _observation(observation_id: str, height: int) -> dict:
    result = preview_from_request(
        MeshPreviewRequest.model_validate(
            {
                "vertices": [[0, 0, 0], [1, 0, 0], [0, height, 0]],
                "faces": [[0, 1, 2]],
                "meters_per_unit": 1,
                "calibration_method": "ruler",
                "calibration_evidence": "Unverified ruler",
                "specimen_id": "colony-1",
                "observation_id": observation_id,
                "observed_at_utc": (
                    "2026-10-01T12:00:00Z" if observation_id == "early" else "2026-10-02T12:00:00Z"
                ),
            }
        )
    )
    result["project_id"] = "study-1"
    return result


def _imported_observation(observation_id: str, height: int) -> dict:
    """Construct genuine imported-source metadata rather than spoofing inline geometry."""
    obj_text = f"# provisional reconstruction\nv 0 0 0\nv 1 0 0\nv 0 {height} 0\nf 1 2 3\n"
    result = preview_from_request(
        MeshPreviewRequest.model_validate(
            {
                "obj_text": obj_text,
                "meters_per_unit": 1,
                "calibration_method": "ruler",
                "calibration_evidence": "Unverified ruler",
                "specimen_id": "colony-1",
                "observation_id": observation_id,
                "observed_at_utc": (
                    "2026-10-01T12:00:00Z" if observation_id == "early" else "2026-10-02T12:00:00Z"
                ),
            }
        )
    )
    result["project_id"] = "study-1"
    return result


def _review(before: dict, after: dict) -> dict:
    return {
        "project_id": "study-1",
        "specimen_id": "colony-1",
        "before_observation_id": "early",
        "after_observation_id": "late",
        "method": "photo_match",
        "observer_id": "observer-1",
        "evidence_note": "Provisional image correspondence",
        "before_geometry_sha256": before["provenance"]["geometry_sha256"],
        "after_geometry_sha256": after["provenance"]["geometry_sha256"],
        "independent_reviewer_id": "reviewer-2",
        "independent_review_decision": "supports_match",
        "independent_review_note": "Reviewed but not authenticated",
        "independent_reviewed_at_utc": "2026-10-03T12:00:00Z",
    }


def test_review_fingerprint_is_canonical_and_sensitive_to_review_revision() -> None:
    before = _observation("early", 1)
    after = _observation("late", 2)
    review = _review(before, after)
    result = compare_mesh_observations(before, after, reidentification_evidence=review)
    provenance = result["provenance"]
    digest = provenance["review_evidence_bundle_sha256"]
    assert provenance["review_evidence_bundle_schema_version"] == "mesh-review-bundle-0003"
    assert isinstance(digest, str) and len(digest) == 64
    assert provenance["specimen_identity_verified"] is False
    assert provenance["reidentification_evidence_review_status"] == "caller_supplied_unverified"
    assert result["measurement_status"] == "provisional_unverified_longitudinal_comparison"

    # Verify the published canonical digest, not just its format.
    canonical = {
        "schema_version": "mesh-review-bundle-0003",
        "project_id": "study-1",
        "specimen_id": "colony-1",
        "before_observation_id": "early",
        "after_observation_id": "late",
        "before_observed_at_utc": "2026-10-01T12:00:00Z",
        "after_observed_at_utc": "2026-10-02T12:00:00Z",
        "before_geometry_sha256": before["provenance"]["geometry_sha256"],
        "after_geometry_sha256": after["provenance"]["geometry_sha256"],
        "before_source_payload_sha256": None,
        "after_source_payload_sha256": None,
        "before_source_format": "indexed_triangles",
        "after_source_format": "indexed_triangles",
        "before_source_payload_size_bytes": None,
        "after_source_payload_size_bytes": None,
        "before_source_payload_integrity_checked": False,
        "after_source_payload_integrity_checked": False,
        "before_coordinate_frame_id": None,
        "after_coordinate_frame_id": None,
        "before_calibration_method": "ruler",
        "after_calibration_method": "ruler",
        "before_calibration_evidence": "Unverified ruler",
        "after_calibration_evidence": "Unverified ruler",
        "before_meters_per_mesh_unit": 1.0,
        "after_meters_per_mesh_unit": 1.0,
        "before_relative_scale_uncertainty": None,
        "after_relative_scale_uncertainty": None,
        "before_calibration_review_evidence": None,
        "after_calibration_review_evidence": None,
        "registration_evidence": None,
        "reidentification_evidence": provenance["reidentification_evidence"],
    }
    expected = sha256(
        dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    assert digest == expected
    assert provenance["review_evidence_bundle"] == canonical
    assert (
        sha256(
            dumps(
                provenance["review_evidence_bundle"],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        == digest
    )
    reversed_review = dict(reversed(list(review.items())))
    assert (
        compare_mesh_observations(before, after, reidentification_evidence=reversed_review)[
            "provenance"
        ]["review_evidence_bundle_sha256"]
        == digest
    )
    amended = {**review, "independent_review_note": "Second review changed interpretation"}
    assert (
        compare_mesh_observations(before, after, reidentification_evidence=amended)["provenance"][
            "review_evidence_bundle_sha256"
        ]
        != digest
    )


def test_review_fingerprint_binds_observations_but_does_not_certify_legacy_evidence() -> None:
    before = _observation("early", 1)
    after = _observation("late", 2)
    absent = compare_mesh_observations(before, after)["provenance"]
    assert absent["review_evidence_bundle_sha256"] is None
    assert absent["review_evidence_bundle_schema_version"] is None
    assert absent["review_evidence_bundle"] is None

    review = _review(before, after)
    review.pop("before_geometry_sha256")
    review.pop("after_geometry_sha256")
    first = compare_mesh_observations(before, after, reidentification_evidence=review)
    changed = _observation("late", 3)
    second = compare_mesh_observations(before, changed, reidentification_evidence=review)
    assert (
        first["provenance"]["review_evidence_bundle_sha256"]
        != second["provenance"]["review_evidence_bundle_sha256"]
    )
    assert "reidentification_geometry_binding_unavailable" in second["qc_warnings"]
    assert second["provenance"]["specimen_identity_verified"] is False

    # A supplied geometry binding is still validated; a digest cannot excuse
    # stale evidence or turn a mismatched review into a valid measurement.
    with pytest.raises(ValueError, match="source geometry fingerprints"):
        compare_mesh_observations(before, changed, reidentification_evidence=_review(before, after))


@pytest.mark.parametrize(
    ("provenance_key", "revised_value"),
    [
        ("calibration_method", "photogrammetry"),
        ("calibration_evidence", "Revised unverified scale note"),
        ("relative_scale_uncertainty", 0.2),
        ("source_payload_sha256", "a" * 64),
        ("source_format", "ply_ascii"),
        ("source_payload_size_bytes", 120),
        # A true integrity flag without a source SHA-256 is invalid; test
        # successful source checks with actual imported bytes separately.
        ("coordinate_frame_id", "survey-local"),
        ("calibration_review_evidence", {"independent_review_note": "Amended"}),
    ],
)
def test_review_bundle_detects_revised_observation_provenance(
    provenance_key: str, revised_value: object
) -> None:
    """Geometry alone cannot certify that the same calibration was reviewed."""
    before = _observation("early", 1)
    after = _observation("late", 2)
    if provenance_key.startswith("source_"):
        # Imported-byte provenance cannot be attached to inline triangles.
        after = _imported_observation("late", 2)
    review = _review(before, after)
    original = compare_mesh_observations(before, after, reidentification_evidence=review)
    amended_after = {**after, "provenance": {**after["provenance"]}}
    amended_after["provenance"][provenance_key] = revised_value
    revised = compare_mesh_observations(before, amended_after, reidentification_evidence=review)
    assert (
        original["provenance"]["review_evidence_bundle_sha256"]
        != revised["provenance"]["review_evidence_bundle_sha256"]
    )
    assert (
        revised["provenance"]["review_evidence_bundle_schema_version"] == "mesh-review-bundle-0003"
    )
    assert revised["provenance"]["specimen_identity_verified"] is False
    assert revised["provenance"]["calibration_verified"] is False


def test_review_fingerprint_detects_changed_obj_bytes_with_same_geometry() -> None:
    """A changed source comment is an evidence revision, not geometric growth."""
    before = _observation("early", 1)

    def imported(comment: str) -> dict:
        obj_text = f"# {comment}\nv 0 0 0\nv 1 0 0\nv 0 2 0\nf 1 2 3\n"
        result = preview_from_request(
            MeshPreviewRequest.model_validate(
                {
                    "obj_text": obj_text,
                    "meters_per_unit": 1,
                    "calibration_method": "ruler",
                    "calibration_evidence": "Unverified ruler",
                    "specimen_id": "colony-1",
                    "observation_id": "late",
                    "observed_at_utc": "2026-10-02T12:00:00Z",
                }
            )
        )
        result["project_id"] = "study-1"
        return result

    first = imported("source revision one")
    second = imported("source revision two")
    assert first["provenance"]["geometry_sha256"] == second["provenance"]["geometry_sha256"]
    assert (
        first["provenance"]["source_payload_sha256"]
        != second["provenance"]["source_payload_sha256"]
    )
    review = _review(before, first)
    initial = compare_mesh_observations(before, first, reidentification_evidence=review)
    revised = compare_mesh_observations(before, second, reidentification_evidence=review)
    assert (
        initial["provenance"]["review_evidence_bundle_sha256"]
        != revised["provenance"]["review_evidence_bundle_sha256"]
    )
    assert revised["provenance"]["specimen_identity_verified"] is False


@pytest.mark.parametrize(
    ("field", "bad_value", "message"),
    [
        ("source_payload_sha256", "not-a-digest", "Source payload SHA-256"),
        ("source_payload_sha256", "A" * 64, "Source payload SHA-256"),
        ("source_payload_size_bytes", -1, "Source payload size"),
        ("source_payload_size_bytes", True, "Source payload size"),
        ("source_payload_integrity_checked", "yes", "Source payload integrity check"),
        (
            "source_payload_integrity_checked",
            True,
            "Source payload integrity check requires a source SHA-256",
        ),
    ],
)
def test_longitudinal_rejects_malformed_source_integrity_evidence(
    field: str, bad_value: object, message: str
) -> None:
    """Malformed stored import evidence must not enter an auditable review hash."""
    before = _observation("early", 1)
    after = _observation("late", 2)
    review = _review(before, after)
    altered = {**after, "provenance": {**after["provenance"], field: bad_value}}
    with pytest.raises(ValueError, match=message):
        compare_mesh_observations(before, altered, reidentification_evidence=review)


def test_longitudinal_legacy_missing_source_integrity_stays_unverified() -> None:
    """Missing historical source metadata remains unknown, not a verified check."""
    before = _observation("early", 1)
    after = _observation("late", 2)
    for record in (before, after):
        for key in (
            "source_payload_sha256",
            "source_payload_size_bytes",
            "source_payload_integrity_checked",
        ):
            record["provenance"].pop(key, None)
    result = compare_mesh_observations(
        before, after, reidentification_evidence=_review(before, after)
    )
    bundle = result["provenance"]["review_evidence_bundle"]
    assert bundle["before_source_payload_sha256"] is None
    assert bundle["after_source_payload_size_bytes"] is None
    assert bundle["before_source_payload_integrity_checked"] is None
    assert result["provenance"]["specimen_identity_verified"] is False
    assert result["provenance"]["calibration_verified"] is False


def test_checked_import_review_bundle_matches_saved_workflow(client: TestClient) -> None:
    """A real source-byte check changes review provenance without verifying biology."""
    project_id = str(create_project(client, "Bound longitudinal source review")["id"])
    base = f"/api/v1/projects/{project_id}"
    before_params = {
        "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
        "faces": [[0, 1, 2]],
        "meters_per_unit": 1,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified ruler",
        "specimen_id": "colony-1",
        "observation_id": "early",
        "observed_at_utc": "2026-10-01T12:00:00Z",
    }
    obj_text = "# original source\nv 0 0 0\nv 1 0 0\nv 0 2 0\nf 1 2 3\n"
    source_sha = sha256(obj_text.encode("utf-8")).hexdigest()
    after_params = {
        "obj_text": obj_text,
        "expected_source_payload_sha256": source_sha,
        "meters_per_unit": 1,
        "calibration_method": "ruler",
        "calibration_evidence": "Unverified ruler",
        "specimen_id": "colony-1",
        "observation_id": "late",
        "observed_at_utc": "2026-10-02T12:00:00Z",
    }

    def preview(parameters: dict) -> dict:
        record = preview_from_request(MeshPreviewRequest.model_validate(parameters))
        record["project_id"] = project_id
        return record

    before = preview(before_params)
    after = preview(after_params)
    review = {**_review(before, after), "project_id": project_id}
    expected = compare_mesh_observations(before, after, reidentification_evidence=review)
    provenance = expected["provenance"]
    bundle = provenance["review_evidence_bundle"]
    assert bundle["after_source_payload_sha256"] == source_sha
    assert bundle["after_source_payload_integrity_checked"] is True
    assert bundle["before_source_payload_integrity_checked"] is False
    assert provenance["specimen_identity_verified"] is False
    assert provenance["calibration_verified"] is False
    assert (
        sha256(
            dumps(
                bundle,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        == provenance["review_evidence_bundle_sha256"]
    )

    # The same imported bytes without an expected SHA are not a checked source.
    unchecked_params = dict(after_params)
    unchecked_params.pop("expected_source_payload_sha256")
    unchecked = compare_mesh_observations(
        before, preview(unchecked_params), reidentification_evidence=review
    )
    assert (
        unchecked["provenance"]["review_evidence_bundle_sha256"]
        != (provenance["review_evidence_bundle_sha256"])
    )

    standalone = client.post(
        f"{base}/spatial/mesh-longitudinal-comparison",
        json={
            "before": before_params,
            "after": after_params,
            "reidentification_evidence": review,
        },
    )
    assert standalone.status_code == 200, standalone.text
    assert standalone.json() == expected

    graph = {
        "graph_id": "checked-import-longitudinal-v14",
        "name": "Checked source review provenance",
        "nodes": [
            {"node_id": "project", "node_type": "project_source"},
            {
                "node_id": "early",
                "node_type": "mesh_surface_preview",
                "parameters": before_params,
            },
            {
                "node_id": "late",
                "node_type": "mesh_surface_preview",
                "parameters": after_params,
            },
            {
                "node_id": "compare",
                "node_type": "mesh_longitudinal_comparison",
                "parameters": {"reidentification_evidence": review},
            },
        ],
        "edges": [
            {
                "edge_id": f"project-{node}",
                "source_node_id": "project",
                "source_port_id": "project",
                "target_node_id": node,
                "target_port_id": "project",
            }
            for node in ("early", "late")
        ]
        + [
            {
                "edge_id": f"{node}-compare",
                "source_node_id": node,
                "source_port_id": "measurement",
                "target_node_id": "compare",
                "target_port_id": port,
            }
            for node, port in (("early", "before"), ("late", "after"))
        ],
    }
    plan = client.post(f"{base}/workflow-graphs/plan", json=graph)
    assert plan.status_code == 200, plan.text
    assert plan.json()["executable"] is True
    saved = client.post(f"{base}/workflow-graphs", json={"graph": graph})
    assert saved.status_code == 201, saved.text
    run = client.post(f"{base}/workflow-runs", json={"graph_record_id": saved.json()["id"]})
    assert run.status_code == 202, run.text
    app = cast(FastAPI, client.app)
    assert process_workflow_run_job(
        app.state.settings, app.state.session_factory, str(run.json()["job_id"])
    )
    detail = client.get(f"/api/v1/workflow-runs/{run.json()['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    comparisons = [
        item["payload_json"]
        for item in detail.json()["artifacts"]
        if item["data_type"] == "mesh_longitudinal_comparison"
    ]
    assert comparisons == [expected]


@pytest.mark.parametrize(
    ("source_format", "source_size", "message"),
    [
        ("indexed_triangles", 10, "Inline indexed triangles"),
        (None, 10, "requires an imported mesh format"),
        ("obj", None, "requires a positive source byte count"),
        ("obj", 0, "requires a positive source byte count"),
    ],
)
def test_checked_source_evidence_requires_actual_imported_bytes(
    source_format: str | None, source_size: int | None, message: str
) -> None:
    """Do not fingerprint unsupported claims that inline or empty files were checked."""
    before = _observation("early", 1)
    after = _observation("late", 2)
    after["provenance"].update(
        source_format=source_format,
        source_payload_sha256="a" * 64,
        source_payload_size_bytes=source_size,
        source_payload_integrity_checked=True,
    )
    with pytest.raises(ValueError, match=message):
        compare_mesh_observations(before, after, reidentification_evidence=_review(before, after))


@pytest.mark.parametrize(
    ("source_format", "source_digest", "source_size", "message"),
    [
        ("indexed_triangles", "a" * 64, None, "Inline indexed triangles"),
        ("indexed_triangles", None, 10, "Inline indexed triangles"),
        ("unrecognized_mesh", None, None, "Unsupported mesh source format"),
        (None, "a" * 64, 10, "Source payload metadata requires an imported mesh format"),
        (None, None, 10, "Source payload metadata requires an imported mesh format"),
    ],
)
def test_unchecked_source_metadata_cannot_fabricate_an_import(
    source_format: str | None, source_digest: str | None, source_size: int | None, message: str
) -> None:
    """Unverified previews still cannot claim impossible source-file metadata."""
    before = _observation("early", 1)
    after = _observation("late", 2)
    after["provenance"].update(
        source_format=source_format,
        source_payload_sha256=source_digest,
        source_payload_size_bytes=source_size,
        source_payload_integrity_checked=False,
    )
    with pytest.raises(ValueError, match=message):
        compare_mesh_observations(before, after, reidentification_evidence=_review(before, after))


def test_unchecked_import_keeps_source_evidence_provisional() -> None:
    """An actual imported digest without an expected hash is not a successful check."""
    before = _observation("early", 1)
    after = _imported_observation("late", 2)
    assert after["provenance"]["source_format"] == "obj"
    assert after["provenance"]["source_payload_integrity_checked"] is False
    source_digest = after["provenance"]["source_payload_sha256"]
    assert isinstance(source_digest, str) and len(source_digest) == 64
    result = compare_mesh_observations(
        before, after, reidentification_evidence=_review(before, after)
    )
    bundle = result["provenance"]["review_evidence_bundle"]
    assert bundle["after_source_payload_sha256"] == source_digest
    assert bundle["after_source_payload_integrity_checked"] is False
    assert result["provenance"]["calibration_verified"] is False
    assert result["provenance"]["specimen_identity_verified"] is False
