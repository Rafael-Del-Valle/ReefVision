"""Round-trip integrated project exchange through the public API."""

from io import BytesIO
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from reefvision.config import Settings
from reefvision.jobs.pose_identity_tracking import process_pose_identity_tracking_job
from reefvision.storage.datasets import canonical_json_sha256
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_ecology_calibration_evidence_1_2 import (
    _link_calibration,
    _prepared_annotation,
    _save_calibration,
)
from reefvision.tests.test_ecology_image_evidence_1_2 import _register, _workflow
from reefvision.tests.test_pose_identity_tracking_api import _first_class, _submit, _track, _video
from reefvision.tests.test_pose_training_project_exchange_phase9 import (
    _archive_with_pose_training_truth,
)
from reefvision.tests.test_reefpose_validation import freeze_fixture
from reefvision.tests.test_scientific_project_exchange import (
    database_counts,
    export_archive,
    import_archive,
    rewrite,
)


def test_pose_dataset_exchange_includes_ecological_identity_history(
    client: TestClient, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, source_project, _ = _archive_with_pose_training_truth(client, test_settings, monkeypatch)
    project_id = str(source_project["id"])
    _register(client, project_id, "exchange-colony")

    raw = export_archive(client, test_settings, project_id)
    inspected = client.post(
        "/api/v1/exchange-packages/inspect",
        files={"file": ("integrated.zip", raw, "application/zip")},
    )
    assert inspected.status_code == 200, inspected.text
    report = inspected.json()
    assert report["compatible"], report
    assert report["format_version"] == "1.2"
    assert report["section_counts"]["pose_training_datasets"] == 1
    assert report["section_counts"]["ecology_identity_revisions"] == 1
    imported = import_archive(client, raw)
    assert imported.status_code == 201, imported.text
    assert imported.json()["imported_counts"]["pose_training_datasets"] == 1
    assert imported.json()["imported_counts"]["ecology_identity_revisions"] == 1
    assert (
        client.get(
            f"/api/v1/projects/{imported.json()['project_id']}/ecology/identity-registry"
        ).json()["identities"][0]["organism_key"]
        == "exchange-colony"
    )


def test_calibrated_ecology_evidence_reopens_and_reexports(
    client: TestClient, test_settings: Settings
) -> None:
    project_id, image_id, annotation = _prepared_annotation(client)
    _save_calibration(client, image_id)
    assert _link_calibration(client, project_id, annotation).status_code == 201
    original_run = _workflow(client, project_id)
    assert original_run["run"]["status"] == "succeeded"
    raw = export_archive(client, test_settings, project_id)

    imported = import_archive(client, raw)
    assert imported.status_code == 201, imported.text
    report = imported.json()
    destination = report["project_id"]
    registry = client.get(f"/api/v1/projects/{destination}/ecology/identity-registry")
    assert registry.status_code == 200, registry.text
    actual = registry.json()
    mapping = report["package"]["options_json"]["id_map"]
    assert actual["image_evidence_links"][0]["image_id"] == mapping[image_id]
    assert (
        actual["annotation_evidence_links"][0]["annotation_id"]
        == mapping[annotation["annotation_id"]]
    )
    assert actual["calibration_evidence_links"][0]["calibration_json"]["distance_per_pixel"] == 0.25
    saved_run = client.get(f"/api/v1/workflow-runs/{mapping[original_run['run']['id']]}").json()
    provenance = saved_run["run"]["result_json"]
    assert provenance["provenance_manifest"]["project_id"] == destination
    assert (
        canonical_json_sha256(provenance["provenance_manifest"]) == provenance["provenance_sha256"]
    )
    original_candidates = next(
        item
        for item in original_run["artifacts"]
        if item["data_type"] == "ecology_measurement_candidates"
    )
    historical = next(
        item
        for item in saved_run["artifacts"]
        if item["data_type"] == "ecology_measurement_candidates"
    )
    assert historical["payload_json"] == original_candidates["payload_json"]
    assert historical["payload_sha256"] == original_candidates["payload_sha256"]
    assert _workflow(client, destination)["run"]["status"] == "succeeded"
    reexport = export_archive(client, test_settings, destination)
    with ZipFile(BytesIO(reexport)) as archive:
        assert "records/ecology_identity_calibration_evidence.jsonl" in archive.namelist()
    assert import_archive(client, reexport).status_code == 201


def test_exchange_without_originals_preserves_identity_and_reports_missing_assets(
    client: TestClient, test_settings: Settings
) -> None:
    from reefvision.jobs.project_exchange import process_project_exchange_export_job

    project_id, image_id, _ = _prepared_annotation(client)
    queued = client.post(f"/api/v1/projects/{project_id}/exchange-packages", json={})
    assert queued.status_code == 202
    assert process_project_exchange_export_job(
        test_settings, client.app.state.session_factory, queued.json()["job_id"]
    )
    archive = client.get(
        f"/api/v1/exchange-packages/{queued.json()['package']['id']}/download"
    ).content
    inspected = client.post(
        "/api/v1/exchange-packages/inspect",
        files={"file": ("integrated.zip", archive, "application/zip")},
    )
    assert inspected.status_code == 200, inspected.text
    assert inspected.json()["unavailable_assets"][0]["record_id"] == image_id
    imported = import_archive(client, archive)
    assert imported.status_code == 201, imported.text
    result = imported.json()
    mapping = result["package"]["options_json"]["id_map"]
    copied_asset = result["unavailable_assets"][0]
    assert copied_asset["record_id"] == image_id
    assert copied_asset["imported_record_id"] == mapping[image_id]
    image = client.get(f"/api/v1/images/{mapping[image_id]}").json()
    assert image["sha256"] == copied_asset["sha256"]
    assert image["metadata_json"]["exchange_media_missing"] is True


def test_integrated_exchange_rejects_foreign_evidence_before_import(
    client: TestClient, test_settings: Settings
) -> None:
    project_id, _, _ = _prepared_annotation(client)
    raw = export_archive(client, test_settings, project_id)

    def break_reference(manifest, sections):
        sections["ecology_identity_annotation_evidence"][0]["annotation_id"] = (
            "9912f803-2583-44d7-a9ee-6696a10976d9"
        )

    damaged = rewrite(raw, break_reference)
    before = database_counts(client)
    inspected = client.post(
        "/api/v1/exchange-packages/inspect",
        files={"file": ("integrated.zip", damaged, "application/zip")},
    )
    assert inspected.status_code == 200
    assert not inspected.json()["compatible"]
    rejected = import_archive(client, damaged)
    assert rejected.status_code == 400
    assert database_counts(client) == before


def test_reefpose_reference_ancestry_reopens_with_remapped_sources(
    client: TestClient, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    url, payload, original = freeze_fixture(client, monkeypatch)
    project_id = url.split("/")[-2]
    payload["parent_id"] = original["id"]
    payload["recordings"][0]["annotations"][1]["events"][0]["end_s"] = 0.45
    successor = client.post(url, json=payload)
    assert successor.status_code == 201, successor.text

    imported = import_archive(client, export_archive(client, test_settings, project_id))
    assert imported.status_code == 201, imported.text
    report = imported.json()
    mapping = report["package"]["options_json"]["id_map"]
    target = f"/api/v1/projects/{report['project_id']}/reefpose-references"
    parent = client.get(f"{target}/{mapping[original['id']]}")
    child = client.get(f"{target}/{mapping[successor.json()['id']]}")
    assert parent.status_code == child.status_code == 200, (parent.text, child.text)
    assert child.json()["parent_id"] == parent.json()["id"]
    assert child.json()["manifest"]["parent_sha256"] == parent.json()["manifest_sha256"]
    source_recording = original["manifest"]["recordings"][0]
    actual_recording = parent.json()["manifest"]["recordings"][0]
    assert actual_recording["video_id"] == mapping[source_recording["video_id"]]
    assert actual_recording["schema_id"] == mapping[source_recording["schema_id"]]
    assert actual_recording["annotation_sha256"] == source_recording["annotation_sha256"]


def test_reviewed_pose_link_reopens_as_current_after_exchange(
    client: TestClient, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = create_project(client)
    project_id = project["id"]
    video = _video(client, project_id, monkeypatch, "exchange-organism-pose")
    track = _track(client, video["id"], _first_class(project), offset=10, prefix="exchange")
    job = _submit(client, project_id, video["id"], [track["id"]])
    assert process_pose_identity_tracking_job(
        test_settings, client.app.state.session_factory, job["id"]
    )
    run_id = job["result_json"]["run_id"]
    source_url = f"/api/v1/pose-identity-runs/{run_id}"
    animal = client.get(f"{source_url}/identities").json()[0]
    correction = client.post(
        f"{source_url}/corrections",
        json={"action": "accept", "target_type": "identity", "target_id": animal["id"]},
    )
    assert correction.status_code == 201, correction.text
    base = f"/api/v1/projects/{project_id}/ecology"
    identity = client.post(
        f"{base}/organisms",
        json={"organism_key": "fish-1", "kind": "individual", "reason": "Field identity"},
    )
    assert identity.status_code == 201, identity.text
    linked = client.post(
        f"{base}/pose-links",
        json={
            "confirm": True,
            "organism_revision_id": identity.json()["id"],
            "association_run_id": run_id,
            "animal_identity_id": animal["id"],
            "expected_identity_run_revision": 2,
            "frame_start": 0,
            "frame_end": 1,
            "reason": "Compared distinctive identified markings",
            "reviewer": "Scientist",
        },
    )
    assert linked.status_code == 201, linked.text
    imported = import_archive(client, export_archive(client, test_settings, project_id))
    assert imported.status_code == 201, imported.text
    destination = imported.json()["project_id"]
    result = client.get(f"/api/v1/projects/{destination}/ecology/pose-links")
    assert result.status_code == 200, result.text
    saved = result.json()["items"][0]
    mapping = imported.json()["package"]["options_json"]["id_map"]
    assert saved["status"] == "current", saved
    assert saved["association_run_id"] == mapping[run_id]
    assert saved["source"]["video_id"] == mapping[video["id"]]
    assert saved["revision"] == 1


def test_verified_ecology_analysis_retains_frozen_result_on_two_imports(
    client: TestClient, test_settings: Settings
) -> None:
    project = create_project(client)
    project_id = project["id"]
    label = project["label_classes"][0]["id"]
    image_id = import_one(client, project_id)["successful"][0]["image_id"]
    annotation = client.put(
        f"/api/v1/images/{image_id}/annotations",
        json={"base_revision": 0, "annotation_status": "reviewed", "annotations": []},
    )
    assert annotation.status_code == 200, annotation.text
    endpoint = f"/api/v1/projects/{project_id}/ecology/verified-analyses"
    response = client.post(
        endpoint,
        json={
            "selection": {
                "kind": "abundance",
                "class_id": label,
                "sources": [
                    {
                        "image_id": image_id,
                        "sample_id": "quadrat-1",
                        "experimental_unit_type": "site",
                        "experimental_unit_id": "site-1",
                        "observed_at": "2026-11-01T12:00:00Z",
                    }
                ],
            },
            "reviewed_by": "Researcher",
            "review_note": "Confirmed survey completeness.",
            "confirm_reviewed_selection": True,
        },
    )
    assert response.status_code == 201, response.text
    original = response.json()
    current_id = original["id"]
    for _ in range(2):
        imported = import_archive(client, export_archive(client, test_settings, project_id))
        assert imported.status_code == 201, imported.text
        result = imported.json()
        mapping = result["package"]["options_json"]["id_map"]
        project_id, current_id = result["project_id"], mapping[current_id]
        saved = client.get(f"/api/v1/projects/{project_id}/ecology/verified-analyses/{current_id}")
        assert saved.status_code == 200, saved.text
        data = saved.json()
        assert data["snapshot"] == original["snapshot"]
        assert data["content_sha256"] == original["content_sha256"]
        assert data["source_id_map"][image_id] != image_id
