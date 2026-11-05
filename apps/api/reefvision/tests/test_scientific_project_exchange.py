"""Portable science must preserve evidence while isolating imported identifiers."""

import json
import zipfile
from copy import deepcopy
from datetime import UTC, datetime
from io import BytesIO

import httpx
import pytest
from sqlalchemy import func, select

from reefvision.db.base import Base
from reefvision.jobs.project_exchange import process_project_exchange_export_job
from reefvision.schemas.environmental_context import NOAAImportRequest
from reefvision.services.environmental_context import EnvironmentalContextService
from reefvision.services.scientific_data import content_hash
from reefvision.tests.test_annotations import create_project, import_one
from reefvision.tests.test_environmental_context import noaa_fixture
from reefvision.tests.test_scientific_data import observation

MANIFEST = "reefvision-exchange-manifest.json"


def export_archive(client, settings, project_id):
    queued = client.post(
        f"/api/v1/projects/{project_id}/exchange-packages", json={"include_media": True}
    )
    assert queued.status_code == 202, queued.text
    package = queued.json()
    assert process_project_exchange_export_job(
        settings, client.app.state.session_factory, package["job_id"]
    )
    response = client.get(f"/api/v1/exchange-packages/{package['package']['id']}/download")
    assert response.status_code == 200, response.text
    return response.content


def import_archive(client, raw):
    return client.post(
        "/api/v1/exchange-packages/import", files={"file": ("science.zip", raw, "application/zip")}
    )


def enriched_project(client):
    project = create_project(client)
    image_id = import_one(client, project["id"])["successful"][0]["image_id"]
    client.put(
        f"/api/v1/images/{image_id}/measurement-calibration",
        json={"distance_per_pixel": 0.1, "unit": "mm"},
    )
    payload = observation(
        subject={"image_id": image_id},
        pixel={"frame": "image_pixels", "x": 10, "y": 20},
        uncertainty={"value": 1.8, "kind": "bound"},
        qc_flags=["operator_checked"],
    )
    # A literal external dataset identifier must never be rewritten as a foreign key.
    payload["provenance"]["dataset_id"] = image_id
    response = client.post(
        f"/api/v1/projects/{project['id']}/scientific-records", json={"records": [payload]}
    )
    assert response.status_code == 201, response.text
    request = NOAAImportRequest(
        station_id="8665530", day="2026-04-03", subject={"image_id": image_id}
    )
    raw = noaa_fixture()
    with (
        client.app.state.session_factory() as session,
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=raw))
        ) as http,
    ):
        service = EnvironmentalContextService(
            session, http=http, now=datetime(2026, 4, 4, tzinfo=UTC)
        )
        service.import_noaa(project["id"], request)
        raw["data"][0]["v"] = "22.0"
        EnvironmentalContextService(
            session, http=http, now=datetime(2026, 4, 6, tzinfo=UTC)
        ).import_noaa(project["id"], request)
    return project, image_id


def rewrite(raw, change):
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(files[MANIFEST])
    sections = {
        name: [json.loads(line) for line in files[desc["path"]].splitlines()]
        for name, desc in manifest["sections"].items()
    }
    change(manifest, sections)
    import hashlib

    for name, rows in sections.items():
        payload = b"".join((json.dumps(row) + "\n").encode() for row in rows)
        descriptor = manifest["sections"][name]
        files[descriptor["path"]] = payload
        descriptor.update(sha256=hashlib.sha256(payload).hexdigest(), count=len(rows))
    files[MANIFEST] = json.dumps(manifest).encode()
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
    return output.getvalue()


def database_counts(client):
    with client.app.state.session_factory() as session:
        return {
            table.name: session.scalar(select(func.count()).select_from(table))
            for table in Base.metadata.sorted_tables
        }


def test_scientific_roundtrip_preserves_evidence_and_offline_cache_with_isolated_ids(
    client, test_settings
):
    project, image_id = enriched_project(client)
    before = client.get(f"/api/v1/projects/{project['id']}/scientific-records").json()["items"]
    raw = export_archive(client, test_settings, project["id"])
    inspection = client.post(
        "/api/v1/exchange-packages/inspect", files={"file": ("science.zip", raw)}
    )
    assert inspection.json()["format_version"] == "1.1"
    imported_ids = []
    for _ in range(2):
        result = import_archive(client, raw)
        assert result.status_code == 201, result.text
        new_project_id = result.json()["project_id"]
        rows = client.get(f"/api/v1/projects/{new_project_id}/scientific-records").json()["items"]
        assert len(rows) == len(before) == 5
        local = next(row for row in rows if row["provenance"]["source"] == "laboratory sensor")
        original = next(row for row in before if row["provenance"]["source"] == "laboratory sensor")
        assert local["subject"]["image_id"] != image_id
        assert local["provenance"] == original["provenance"]
        for field in (
            "value",
            "normalized_value",
            "uncertainty",
            "qc_flags",
            "pixel",
            "location",
            "calibration_snapshot",
            "calibration_sha256",
        ):
            assert local[field] == original[field]
        assert local["calibration_current"] is True
        assert sum(row["environmental_snapshot_current"] is False for row in rows) == 2
        offline = client.post(
            f"/api/v1/projects/{new_project_id}/environment/noaa",
            json={
                "station_id": "8665530",
                "day": "2026-04-03",
                "offline": True,
                "subject": local["subject"],
            },
        )
        assert offline.status_code == 200, offline.text
        assert len(offline.json()["items"]) == 2
        assert offline.json()["items"][0]["value"] == 22
        imported_ids.append({row["id"] for row in rows})
    assert imported_ids[0].isdisjoint(imported_ids[1])
    assert imported_ids[0].isdisjoint({row["id"] for row in before})
    assert (
        client.get(f"/api/v1/projects/{project['id']}/scientific-records").json()["items"] == before
    )


@pytest.mark.parametrize(
    "corruption",
    [
        "version",
        "duplicate",
        "foreign_project",
        "missing_image",
        "subject_mismatch",
        "hash",
        "cache_reference",
        "normalized",
        "calibration_hash",
        "cache_payload_shape",
        "cache_record_type",
        "cache_identity_shape",
    ],
)
def test_scientific_exchange_rejects_invalid_data_without_partial_import(
    client, test_settings, corruption
):
    project, _ = enriched_project(client)
    raw = export_archive(client, test_settings, project["id"])

    def change(manifest, sections):
        record = sections["scientific_records"][0]
        if corruption == "version":
            manifest["format_version"] = "1.2"
        elif corruption == "duplicate":
            sections["scientific_records"].append(deepcopy(record))
        elif corruption == "foreign_project":
            record["project_id"] = "foreign"
        elif corruption == "missing_image":
            record["image_id"] = "missing"
        elif corruption == "subject_mismatch":
            record["payload_json"]["subject"]["image_id"] = None
        elif corruption == "hash":
            record["payload_json"]["value"] = 900
        elif corruption == "normalized":
            record["payload_json"]["normalized_value"] = 900
        elif corruption == "calibration_hash":
            record["payload_json"]["calibration_sha256"] = "0" * 64
        elif corruption == "cache_reference":
            cache = sections["environmental_cache_entries"][0]
            cache["payload_json"]["record_ids"] = ["missing"]
            cache["content_sha256"] = content_hash(cache["payload_json"])
        if corruption.startswith("cache_") and corruption != "cache_reference":
            cache = sections["environmental_cache_entries"][0]
            if corruption == "cache_payload_shape":
                cache["payload_json"] = []
            elif corruption == "cache_record_type":
                cache["payload_json"]["record_ids"] = [{}]
            else:
                cache["payload_json"]["cache_identity"] = "invalid"
            cache["content_sha256"] = content_hash(cache["payload_json"])
        if corruption in ("subject_mismatch", "normalized", "calibration_hash"):
            record["content_sha256"] = content_hash(record["payload_json"])

    damaged = rewrite(raw, change)
    counts = database_counts(client)
    folders = set((test_settings.resolved_data_dir / "projects").iterdir())
    response = import_archive(client, damaged)
    assert response.status_code == 400, response.text
    assert database_counts(client) == counts
    assert set((test_settings.resolved_data_dir / "projects").iterdir()) == folders


def test_exchange_artifact_failure_rolls_back_all_tables(client, test_settings, monkeypatch):
    from reefvision.domain.errors import ValidationError
    from reefvision.services import project_exchange_import_v1 as importer

    project, _ = enriched_project(client)
    raw = export_archive(client, test_settings, project["id"])
    counts = database_counts(client)
    folders = set((test_settings.resolved_data_dir / "projects").iterdir())

    def fail(*args, **kwargs):
        raise ValidationError("Injected artifact restoration failure")

    monkeypatch.setattr(importer, "_restore_generated_artifacts", fail)
    response = import_archive(client, raw)
    assert response.status_code == 400
    assert database_counts(client) == counts
    assert set((test_settings.resolved_data_dir / "projects").iterdir()) == folders


def test_legacy_10_archive_without_scientific_sections_still_imports(client, test_settings):
    project = create_project(client)
    import_one(client, project["id"])
    raw = export_archive(client, test_settings, project["id"])

    def legacy(manifest, sections):
        manifest["format_version"] = "1.0"
        for name in ("scientific_records", "environmental_cache_entries"):
            sections.pop(name, None)
            manifest["sections"].pop(name, None)

    result = import_archive(client, rewrite(raw, legacy))
    assert result.status_code == 201, result.text
    assert result.json()["imported_counts"]["images"] == 1
