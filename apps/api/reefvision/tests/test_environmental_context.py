from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_scientific_data import observation


def noaa_fixture():
    """Synthetic NOAA-shaped response; values are test fixtures, not observations."""
    return {
        "metadata": {"id": "8665530", "name": "Synthetic station", "lat": "32.75", "lon": "-79.93"},
        "data": [
            {"t": "2026-04-03 13:00", "v": "20.0", "f": "0,0,0"},
            {"t": "2026-04-03 13:06", "v": "20.1", "f": "0,1,0"},
            {"t": "2026-04-03 13:12", "v": "", "f": "1,1,1"},
        ],
    }


def test_noaa_import_is_persistent_idempotent_and_usable_offline(client):
    from reefvision.schemas.environmental_context import NOAAImportRequest
    from reefvision.services.environmental_context import EnvironmentalContextService

    project = create_project(client)
    calls = []

    def transport(request):
        calls.append(request)
        assert request.url.host == "api.tidesandcurrents.noaa.gov"
        assert request.url.params["time_zone"] == "gmt"
        assert request.url.params["units"] == "metric"
        return httpx.Response(200, json=noaa_fixture())

    payload = NOAAImportRequest(station_id="8665530", day="2026-04-03")
    now = datetime(2026, 4, 4, tzinfo=UTC)
    with (
        client.app.state.session_factory() as session,
        httpx.Client(transport=httpx.MockTransport(transport)) as http,
    ):
        first = EnvironmentalContextService(session, http=http, now=now).import_noaa(
            project["id"], payload
        )
    assert first.cache_status == "downloaded"
    assert len(first.items) == 2 and first.skipped_missing == 1
    assert first.items[0].normalized_value == 20
    assert first.items[0].depth_m is None
    assert first.items[0].source_kind == "observed"
    assert first.items[1].qc == "suspect"
    assert first.items[0].provenance.source_metadata["f"] == "0,0,0"
    with (
        client.app.state.session_factory() as session,
        httpx.Client(transport=httpx.MockTransport(transport)) as http,
    ):
        cached = EnvironmentalContextService(
            session, http=http, now=now + timedelta(hours=1)
        ).import_noaa(project["id"], payload)
        assert cached.cache_status == "fresh"
        offline = EnvironmentalContextService(
            session, http=http, now=now + timedelta(days=2)
        ).import_noaa(project["id"], payload.model_copy(update={"offline": True}))
    assert offline.cache_status == "stale_offline"
    assert offline.items[0].id == first.items[0].id
    assert len(calls) == 1
    assert client.get(f"/api/v1/projects/{project['id']}/scientific-records").json()["total"] == 2


def test_noaa_expiry_refresh_preserves_unchanged_record_ids(client):
    from reefvision.schemas.environmental_context import NOAAImportRequest
    from reefvision.services.environmental_context import EnvironmentalContextService

    project = create_project(client)
    payload = NOAAImportRequest(station_id="8665530", day="2026-04-03")
    now = datetime(2026, 4, 4, tzinfo=UTC)
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(200, json=noaa_fixture())

    with (
        client.app.state.session_factory() as session,
        httpx.Client(transport=httpx.MockTransport(transport)) as http,
    ):
        first = EnvironmentalContextService(session, http=http, now=now).import_noaa(
            project["id"], payload
        )
        refreshed = EnvironmentalContextService(
            session, http=http, now=now + timedelta(days=1)
        ).import_noaa(project["id"], payload)
    assert len(calls) == 2
    assert refreshed.items[0].id == first.items[0].id
    assert refreshed.cache_status == "downloaded"


@pytest.mark.parametrize("correction", ["value", "qc", "removed"])
def test_lookup_uses_current_noaa_snapshot_and_retains_identifiable_history(client, correction):
    from reefvision.schemas.environmental_context import NOAAImportRequest
    from reefvision.services.environmental_context import EnvironmentalContextService

    project = create_project(client)
    payload = NOAAImportRequest(station_id="8665530", day="2026-04-03")
    now = datetime(2026, 4, 4, tzinfo=UTC)
    raw = noaa_fixture()
    with (
        client.app.state.session_factory() as session,
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=raw))
        ) as http,
    ):
        first = EnvironmentalContextService(session, http=http, now=now).import_noaa(
            project["id"], payload
        )
        if correction == "removed":
            raw["data"].pop(0)
        else:
            raw["data"][0]["v"] = "21.0"
            if correction == "qc":
                raw["data"][0]["f"] = "0,1,0"
        refreshed = EnvironmentalContextService(
            session, http=http, now=now + timedelta(days=1)
        ).import_noaa(project["id"], payload)
    response = client.post(
        f"/api/v1/projects/{project['id']}/environment/lookup",
        json={
            "variable": "water_temperature",
            "location": {"latitude": 32.75, "longitude": -79.93},
            "observed_at": "2026-04-03T13:00:00Z",
            "max_distance_m": 1000,
            "max_time_delta_s": 60,
        },
    )
    assert response.status_code == 200, response.text
    matches = response.json()["matches"]
    if correction == "value":
        assert len(matches) == 1
        assert matches[0]["record"]["normalized_value"] == 21
        assert matches[0]["record"]["id"] == str(refreshed.items[0].id)
    else:
        assert matches == []
    history = client.get(f"/api/v1/projects/{project['id']}/scientific-records").json()["items"]
    old = next(row for row in history if row["id"] == str(first.items[0].id))
    assert old["value"] == 20
    assert old["environmental_snapshot_current"] is False
    current = next(row for row in history if row["id"] == str(refreshed.items[0].id))
    assert current["environmental_snapshot_current"] is True


@pytest.mark.parametrize("change", ["error", "station", "date", "nonfinite", "empty"])
def test_noaa_unavailable_or_malformed_data_never_becomes_observations(client, change):
    from reefvision.domain.errors import ValidationError
    from reefvision.schemas.environmental_context import NOAAImportRequest
    from reefvision.services.environmental_context import EnvironmentalContextService

    project = create_project(client)
    raw = deepcopy(noaa_fixture())
    if change == "error":
        raw = {"error": {"message": "No data was found"}}
    if change == "station":
        raw["metadata"]["id"] = "1234567"
    if change == "date":
        raw["data"][0]["t"] = "2026-04-04 13:00"
    if change == "nonfinite":
        raw["data"][0]["v"] = "NaN"
    if change == "empty":
        raw["data"] = []
    with (
        client.app.state.session_factory() as session,
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=raw))
        ) as http,
        pytest.raises(ValidationError),
    ):
        EnvironmentalContextService(session, http=http).import_noaa(
            project["id"], NOAAImportRequest(station_id="8665530", day="2026-04-03")
        )
    assert client.get(f"/api/v1/projects/{project['id']}/scientific-records").json()["total"] == 0


def test_offline_without_cache_reports_missing_data(client):
    project = create_project(client)
    response = client.post(
        f"/api/v1/projects/{project['id']}/environment/noaa",
        json={"station_id": "8665530", "day": "2026-04-03", "offline": True},
    )
    assert response.status_code == 404
    assert "No cached NOAA" in response.json()["detail"]


def test_failed_refresh_keeps_previous_cache_and_corruption_is_rejected(client):
    from sqlalchemy import select

    from reefvision.db.models.scientific_record import EnvironmentalCacheEntry
    from reefvision.domain.errors import ConflictError, ValidationError
    from reefvision.schemas.environmental_context import NOAAImportRequest
    from reefvision.services.environmental_context import EnvironmentalContextService

    project = create_project(client)
    payload = NOAAImportRequest(station_id="8665530", day="2026-04-03")
    now = datetime(2026, 4, 4, tzinfo=UTC)
    with (
        client.app.state.session_factory() as session,
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=noaa_fixture()))
        ) as http,
    ):
        original = EnvironmentalContextService(session, http=http, now=now).import_noaa(
            project["id"], payload
        )
    with (
        client.app.state.session_factory() as session,
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as http,
    ):
        service = EnvironmentalContextService(session, http=http, now=now + timedelta(days=2))
        with pytest.raises(ValidationError):
            service.import_noaa(project["id"], payload)
        cached = service.import_noaa(project["id"], payload.model_copy(update={"offline": True}))
        assert cached.items[0].id == original.items[0].id
        entry = session.scalar(select(EnvironmentalCacheEntry))
        entry.payload_json = {**entry.payload_json, "skipped_missing": 999}
        session.commit()
        with pytest.raises(ConflictError, match="checksum"):
            service.import_noaa(project["id"], payload.model_copy(update={"offline": True}))


@pytest.mark.parametrize(
    ("alteration", "error_fragment"),
    [
        ("missing_count_absent", "missing-observation count"),
        ("missing_count_boolean", "missing-observation count"),
        ("missing_count_negative", "missing-observation count"),
        ("missing_count_string", "missing-observation count"),
        ("missing_count_fractional", "missing-observation count"),
        ("provider_response_absent", "malformed provider evidence"),
        ("provider_response_list", "malformed provider evidence"),
        ("entire_payload_list", "malformed provider evidence"),
    ],
)
def test_rehashed_environmental_cache_rejects_malformed_missingness_and_source_evidence(
    client, alteration, error_fragment
):
    """Rehashing corrupt cache metadata must not forge scientific missingness or cause 500s."""
    from sqlalchemy import select

    from reefvision.db.models.scientific_record import EnvironmentalCacheEntry, ScientificRecord
    from reefvision.domain.errors import ConflictError
    from reefvision.schemas.environmental_context import NOAAImportRequest
    from reefvision.services.environmental_context import EnvironmentalContextService
    from reefvision.services.scientific_data import content_hash

    project = create_project(client, "Malformed environmental cache evidence")
    request = NOAAImportRequest(station_id="8665530", day="2026-04-03")
    with (
        client.app.state.session_factory() as session,
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=noaa_fixture()))
        ) as http,
    ):
        service = EnvironmentalContextService(
            session, http=http, now=datetime(2026, 4, 4, tzinfo=UTC)
        )
        imported = service.import_noaa(project["id"], request)
        assert imported.skipped_missing == 1
        original_ids = {str(item.id) for item in imported.items}
        entry = session.scalar(select(EnvironmentalCacheEntry))
        assert entry is not None
        cache_key = entry.cache_key
        tampered = deepcopy(entry.payload_json)
        if alteration == "missing_count_absent":
            del tampered["skipped_missing"]
        elif alteration == "missing_count_boolean":
            tampered["skipped_missing"] = True
        elif alteration == "missing_count_negative":
            tampered["skipped_missing"] = -1
        elif alteration == "missing_count_string":
            tampered["skipped_missing"] = "1"
        elif alteration == "missing_count_fractional":
            tampered["skipped_missing"] = 0.5
        elif alteration == "provider_response_absent":
            del tampered["provider_response"]
        elif alteration == "provider_response_list":
            tampered["provider_response"] = []
        else:
            tampered = ["not", "a", "scientific", "cache"]
        entry.payload_json = tampered
        entry.content_sha256 = content_hash(tampered)
        session.commit()

        with pytest.raises(ConflictError, match=error_fragment):
            service.cached_dataset(project["id"], cache_key)
        with pytest.raises(ConflictError, match=error_fragment):
            service.datasets(project["id"])
        with pytest.raises(ConflictError, match=error_fragment):
            service.import_noaa(project["id"], request.model_copy(update={"offline": True}))

        records = session.scalars(
            select(ScientificRecord).where(ScientificRecord.project_id == project["id"])
        ).all()
        assert {row.id for row in records} == original_ids
        assert all(content_hash(row.payload_json) == row.content_sha256 for row in records)


@pytest.mark.parametrize(
    ("alteration", "error_fragment"),
    [
        ("missingness", "invalid missing-observation count"),
        ("provider_response", "malformed provider evidence"),
        ("identity", "identity mismatch"),
        ("duplicate_lineage", "duplicate scientific record IDs"),
        ("missing_lineage", "missing or foreign scientific records"),
    ],
)
def test_environmental_lookup_and_threshold_reject_rehashed_bad_provider_cache(
    client, alteration, error_fragment
):
    """Neither spatial matches nor threshold events may use corrupt cached evidence."""
    from sqlalchemy import select

    from reefvision.db.models.scientific_record import EnvironmentalCacheEntry
    from reefvision.domain.errors import ConflictError
    from reefvision.schemas.environmental_context import (
        EnvironmentalLookup,
        EnvironmentalThresholdRequest,
        NOAAImportRequest,
    )
    from reefvision.services.environmental_context import EnvironmentalContextService
    from reefvision.services.scientific_data import content_hash

    project = create_project(client, "Cached environmental lookup QC")
    request = NOAAImportRequest(station_id="8665530", day="2026-04-03")
    with (
        client.app.state.session_factory() as session,
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=noaa_fixture()))
        ) as http,
    ):
        service = EnvironmentalContextService(
            session, http=http, now=datetime(2026, 4, 4, tzinfo=UTC)
        )
        imported = service.import_noaa(project["id"], request)
        original_ids = {str(item.id) for item in imported.items}
        lookup = EnvironmentalLookup(
            variable="water_temperature",
            location={"latitude": 32.75, "longitude": -79.93},
            observed_at=datetime(2026, 4, 3, 13, tzinfo=UTC),
            max_distance_m=1000,
            max_time_delta_s=60,
        )
        assert len(service.lookup(project["id"], lookup).matches) == 1

        entry = session.scalar(select(EnvironmentalCacheEntry))
        assert entry is not None
        payload = deepcopy(entry.payload_json)
        if alteration == "missingness":
            payload["skipped_missing"] = -1
        elif alteration == "provider_response":
            payload["provider_response"] = ["invalid", "provider", "payload"]
        elif alteration == "identity":
            payload["cache_identity"]["source_url"] += "&foreign=1"
        elif alteration == "duplicate_lineage":
            payload["record_ids"] = [payload["record_ids"][0]] * 2
        else:
            payload["record_ids"][1] = "missing-scientific-record"
        entry.payload_json = payload
        entry.content_sha256 = content_hash(payload)
        session.commit()

        with pytest.raises(ConflictError, match=error_fragment):
            service.lookup(project["id"], lookup)
        threshold = EnvironmentalThresholdRequest.model_validate(
            {**lookup.model_dump(), "threshold_value": 19, "threshold_unit": "degC"}
        )
        with pytest.raises(ConflictError, match=error_fragment):
            service.threshold_samples(project["id"], threshold)

    # Retain immutable historic records for audit even when the provider cache
    # is unusable for new environmental inference or event detection.
    records = client.get(f"/api/v1/projects/{project['id']}/scientific-records")
    assert records.status_code == 200, records.text
    assert {item["id"] for item in records.json()["items"]} == original_ids


@pytest.mark.parametrize(
    ("alteration", "error_fragment"),
    [
        ("cache_identity", "identity mismatch"),
        ("source_url", "source identity mismatch"),
    ],
)
def test_offline_noaa_cache_rejects_rehashed_foreign_identity_and_source(
    client, alteration, error_fragment
):
    """A valid payload checksum alone must not authorize mismatched NOAA evidence."""
    from sqlalchemy import select

    from reefvision.db.models.scientific_record import EnvironmentalCacheEntry
    from reefvision.domain.errors import ConflictError
    from reefvision.schemas.environmental_context import NOAAImportRequest
    from reefvision.services.environmental_context import EnvironmentalContextService
    from reefvision.services.scientific_data import content_hash

    project = create_project(client, "Environmental cache identity integrity")
    request = NOAAImportRequest(station_id="8665530", day="2026-04-03")
    now = datetime(2026, 4, 4, tzinfo=UTC)
    with (
        client.app.state.session_factory() as session,
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=noaa_fixture()))
        ) as http,
    ):
        service = EnvironmentalContextService(session, http=http, now=now)
        imported = service.import_noaa(project["id"], request)
        assert len(imported.items) == 2
        original_ids = [item.id for item in imported.items]
        entry = session.scalar(select(EnvironmentalCacheEntry))
        assert entry is not None
        original_key = entry.cache_key

        if alteration == "cache_identity":
            tampered = deepcopy(entry.payload_json)
            tampered["cache_identity"]["source_url"] += "&different_station=1"
            entry.payload_json = tampered
            # Even if the payload digest has been recomputed, the immutable
            # identity key must reject reassignment to another source query.
            entry.content_sha256 = content_hash(tampered)
        else:
            # A changed source URL must not be treated as the identity already
            # recorded in the original cache payload.
            entry.source_url = "https://example.invalid/foreign-dataset"
        session.commit()

        offline = request.model_copy(update={"offline": True})
        with pytest.raises(ConflictError, match=error_fragment):
            service.import_noaa(project["id"], offline)
        with pytest.raises(ConflictError, match=error_fragment):
            service.cached_dataset(project["id"], original_key)
        with pytest.raises(ConflictError, match=error_fragment):
            service.datasets(project["id"])

    # Cache validation must never modify or discard original scientific records.
    records = client.get(f"/api/v1/projects/{project['id']}/scientific-records")
    assert records.status_code == 200, records.text
    assert {item["id"] for item in records.json()["items"]} == {
        str(record_id) for record_id in original_ids
    }
    # Malformed or foreign provider data cannot be displayed as current,
    # even though the original observations remain accessible for audit.
    audit_rows = records.json()["items"]
    assert all(row["environmental_snapshot_current"] is False for row in audit_rows)


@pytest.mark.parametrize("alteration", ["missing", "foreign", "duplicate"])
def test_cache_list_rejects_rehashed_missing_foreign_or_duplicate_record_lineage(
    client, alteration
):
    """A cache checksum cannot make missing, foreign, or repeated evidence valid."""
    from sqlalchemy import select

    from reefvision.db.models.scientific_record import EnvironmentalCacheEntry
    from reefvision.domain.errors import ConflictError
    from reefvision.schemas.environmental_context import NOAAImportRequest
    from reefvision.services.environmental_context import EnvironmentalContextService
    from reefvision.services.scientific_data import content_hash

    project = create_project(client, "Cache evidence lineage")
    other = create_project(client, "Independent field study")
    other_response = client.post(
        f"/api/v1/projects/{other['id']}/scientific-records",
        json={"records": [observation()]},
    )
    assert other_response.status_code == 201, other_response.text
    foreign_id = other_response.json()["items"][0]["id"]

    request = NOAAImportRequest(station_id="8665530", day="2026-04-03")
    with (
        client.app.state.session_factory() as session,
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=noaa_fixture()))
        ) as http,
    ):
        service = EnvironmentalContextService(
            session, http=http, now=datetime(2026, 4, 4, tzinfo=UTC)
        )
        imported = service.import_noaa(project["id"], request)
        original_ids = [str(item.id) for item in imported.items]
        assert len(original_ids) == 2
        entry = session.scalar(select(EnvironmentalCacheEntry))
        assert entry is not None
        cache_key = entry.cache_key
        tampered = deepcopy(entry.payload_json)
        if alteration == "missing":
            tampered["record_ids"] = [original_ids[0], "not-a-record"]
        elif alteration == "foreign":
            tampered["record_ids"] = [original_ids[0], foreign_id]
        else:
            tampered["record_ids"] = [original_ids[0], original_ids[0]]
        entry.payload_json = tampered
        entry.content_sha256 = content_hash(tampered)
        session.commit()

        message = "duplicate" if alteration == "duplicate" else "missing or foreign"
        with pytest.raises(ConflictError, match=message):
            service.cached_dataset(project["id"], cache_key)
        with pytest.raises(ConflictError, match=message):
            service.datasets(project["id"])

    records = client.get(f"/api/v1/projects/{project['id']}/scientific-records")
    assert records.status_code == 200, records.text
    assert {item["id"] for item in records.json()["items"]} == set(original_ids)


@pytest.mark.parametrize("alteration", ["changed_record_key", "same_project_substitution"])
def test_environment_cache_rejects_unrelated_same_project_record_lineage(client, alteration):
    """A record's project and a rehashed payload alone do not prove dataset lineage."""
    from sqlalchemy import select

    from reefvision.db.models.scientific_record import EnvironmentalCacheEntry, ScientificRecord
    from reefvision.domain.errors import ConflictError
    from reefvision.schemas.environmental_context import NOAAImportRequest
    from reefvision.services.environmental_context import EnvironmentalContextService
    from reefvision.services.scientific_data import content_hash

    project = create_project(client, "Same-project NOAA cache lineage")
    unrelated_id = None
    if alteration == "same_project_substitution":
        response = client.post(
            f"/api/v1/projects/{project['id']}/scientific-records",
            json={"records": [observation()]},
        )
        assert response.status_code == 201, response.text
        unrelated_id = str(response.json()["items"][0]["id"])

    request = NOAAImportRequest(station_id="8665530", day="2026-04-03")
    with (
        client.app.state.session_factory() as session,
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=noaa_fixture()))
        ) as http,
    ):
        service = EnvironmentalContextService(
            session, http=http, now=datetime(2026, 4, 4, tzinfo=UTC)
        )
        imported = service.import_noaa(project["id"], request)
        original_ids = [str(item.id) for item in imported.items]
        assert len(original_ids) == 2
        entry = session.scalar(select(EnvironmentalCacheEntry))
        assert entry is not None
        cache_key = entry.cache_key

        if alteration == "changed_record_key":
            record = session.get(ScientificRecord, original_ids[1])
            assert record is not None
            changed = deepcopy(record.payload_json)
            changed["environmental_cache_key"] = "unrelated-dataset"
            record.payload_json = changed
            record.content_sha256 = content_hash(changed)
        else:
            assert unrelated_id is not None
            tampered = deepcopy(entry.payload_json)
            tampered["record_ids"] = [original_ids[0], unrelated_id]
            entry.payload_json = tampered
            entry.content_sha256 = content_hash(tampered)
        session.commit()

        with pytest.raises(ConflictError, match="another dataset"):
            service.cached_dataset(project["id"], cache_key)
        with pytest.raises(ConflictError, match="another dataset"):
            service.datasets(project["id"])
        with pytest.raises(ConflictError, match="another dataset"):
            service.import_noaa(project["id"], request.model_copy(update={"offline": True}))

    # Validation is read-only: even intentionally corrupted lineage must not
    # delete records or modify their stored checksums.
    expected = set(original_ids)
    if unrelated_id is not None:
        expected.add(unrelated_id)
    with client.app.state.session_factory() as session:
        stored = session.scalars(
            select(ScientificRecord).where(ScientificRecord.project_id == project["id"])
        ).all()
        assert {row.id for row in stored} == expected
        assert all(content_hash(row.payload_json) == row.content_sha256 for row in stored)
    if alteration == "same_project_substitution":
        response = client.get(f"/api/v1/projects/{project['id']}/scientific-records")
        assert response.status_code == 200, response.text
        assert {str(item["id"]) for item in response.json()["items"]} == expected


def test_environment_lookup_uses_explicit_space_time_depth_and_qc_limits(client):
    project = create_project(client)
    records = [
        observation(depth_m=5, depth_reference="sea_surface"),
        observation(),
        observation(depth_m=50, depth_reference="sea_surface"),
        observation(
            location={"latitude": 0, "longitude": 0}, depth_m=5, depth_reference="sea_surface"
        ),
        observation(observed_at="2026-04-01T13:00:00Z", depth_m=5, depth_reference="sea_surface"),
        observation(qc="rejected", depth_m=5, depth_reference="sea_surface"),
    ]
    assert (
        client.post(
            f"/api/v1/projects/{project['id']}/scientific-records", json={"records": records}
        ).status_code
        == 201
    )
    request = {
        "variable": "water_temperature",
        "location": {"latitude": 32.75, "longitude": -79.93},
        "observed_at": "2026-04-03T13:00:00Z",
        "max_distance_m": 1000,
        "max_time_delta_s": 60,
        "depth_m": 5,
        "depth_reference": "sea_surface",
        "max_depth_delta_m": 1,
    }
    response = client.post(f"/api/v1/projects/{project['id']}/environment/lookup", json=request)
    assert response.status_code == 200, response.text
    assert len(response.json()["matches"]) == 1
    match = response.json()["matches"][0]
    assert match["distance_m"] == 0 and match["time_delta_s"] == 0
    assert match["record"]["normalized_value"] == pytest.approx(20)


def test_full_backup_preserves_scientific_records_and_offline_provider_cache(client, test_settings):
    from pathlib import Path

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from reefvision.schemas.environmental_context import NOAAImportRequest
    from reefvision.services.environmental_context import EnvironmentalContextService
    from reefvision.services.scientific_data import ScientificDataService
    from reefvision.tests.test_backups import create_completed_backup

    project = create_project(client)
    payload = NOAAImportRequest(station_id="8665530", day="2026-04-03")
    with (
        client.app.state.session_factory() as session,
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=noaa_fixture()))
        ) as http,
    ):
        original = EnvironmentalContextService(session, http=http).import_noaa(
            project["id"], payload
        )
    _, backup = create_completed_backup(client, test_settings)
    snapshot = (
        test_settings.resolved_data_dir / Path(backup["destination_path"]) / "database" / "test.db"
    )
    engine = create_engine(f"sqlite:///{snapshot.as_posix()}")
    try:
        with Session(engine) as session:
            restored = EnvironmentalContextService(session).import_noaa(
                project["id"], payload.model_copy(update={"offline": True})
            )
            assert [row.model_dump(mode="json") for row in restored.items] == [
                row.model_dump(mode="json") for row in original.items
            ]
            assert ScientificDataService(session).list_records(project["id"]).total == 2
    finally:
        engine.dispose()


def test_lookup_excludes_stale_calibration_but_preserves_unlinked_station_observations(client):
    from reefvision.tests.test_annotations import import_one

    project = create_project(client)
    image_id = import_one(client, project["id"])["successful"][0]["image_id"]
    calibration_url = f"/api/v1/images/{image_id}/measurement-calibration"
    calibration = client.put(calibration_url, json={"distance_per_pixel": 0.1, "unit": "mm"})
    assert calibration.status_code == 200, calibration.text

    records_url = f"/api/v1/projects/{project['id']}/scientific-records"
    saved = client.post(
        records_url,
        json={
            "records": [
                observation(
                    subject={"image_id": image_id},
                    pixel={"x": 40, "y": 30, "frame": "image_pixels"},
                ),
                observation(value=70.0),
            ]
        },
    )
    assert saved.status_code == 201, saved.text
    image_record, unlinked_record = saved.json()["items"]
    assert image_record["calibration_current"] is True

    lookup_url = f"/api/v1/projects/{project['id']}/environment/lookup"
    request = {
        "variable": "water_temperature",
        "location": {"latitude": 32.75, "longitude": -79.93},
        "observed_at": "2026-04-03T13:00:00Z",
        "max_distance_m": 1000,
        "max_time_delta_s": 60,
    }
    before = client.post(lookup_url, json=request)
    assert before.status_code == 200, before.text
    assert {match["record"]["id"] for match in before.json()["matches"]} == {
        image_record["id"],
        unlinked_record["id"],
    }

    changed = client.put(calibration_url, json={"distance_per_pixel": 0.2, "unit": "mm"})
    assert changed.status_code == 200, changed.text
    history = client.get(records_url)
    assert history.status_code == 200, history.text
    stale = next(row for row in history.json()["items"] if row["id"] == image_record["id"])
    assert stale["calibration_current"] is False

    after = client.post(lookup_url, json=request)
    assert after.status_code == 200, after.text
    assert [match["record"]["id"] for match in after.json()["matches"]] == [unlinked_record["id"]]


def test_threshold_samples_preserve_source_records_and_unit_contract(client):
    project = create_project(client)
    records_url = f"/api/v1/projects/{project['id']}/scientific-records"
    saved = client.post(
        records_url,
        json={
            "records": [
                observation(value=22, unit="degC", qc="accepted"),
                observation(value=18, unit="degC", qc="accepted"),
                observation(value=25, unit="degC", qc="suspect"),
                observation(value=26, unit="degC", qc="rejected"),
                observation(value=30, unit="degC", source_kind="modeled"),
            ]
        },
    )
    assert saved.status_code == 201, saved.text
    source_ids = [row["id"] for row in saved.json()["items"]]
    url = f"/api/v1/projects/{project['id']}/environment/events/threshold"
    payload = {
        "variable": "water_temperature",
        "location": {"latitude": 32.75, "longitude": -79.93},
        "observed_at": "2026-04-03T13:00:00Z",
        "max_distance_m": 1000,
        "max_time_delta_s": 60,
        "source_kinds": ["observed"],
        "threshold_value": 68,
        "threshold_unit": "degF",
        "direction": "above",
    }
    above = client.post(url, json=payload)
    assert above.status_code == 200, above.text
    result = above.json()
    assert result["method"] == "observed_sample_threshold_no_interpolation"
    assert result["normalized_threshold"] == pytest.approx(20)
    assert result["normalized_unit"] == "degC"
    assert [item["record"]["id"] for item in result["matches"]] == source_ids[:1]
    assert result["matches"][0]["record"]["provenance"]["source"] == "laboratory sensor"

    below = client.post(url, json={**payload, "direction": "below"})
    assert below.status_code == 200, below.text
    assert [item["record"]["id"] for item in below.json()["matches"]] == source_ids[1:2]
    wrong_units = client.post(url, json={**payload, "threshold_unit": "m/s"})
    assert wrong_units.status_code == 400, wrong_units.text
    unsupported = client.post(url, json={**payload, "variable": "organism_count"})
    assert unsupported.status_code == 400, unsupported.text
    nonfinite = client.post(url, json={**payload, "threshold_value": "NaN"})
    assert nonfinite.status_code == 422, nonfinite.text
    history = client.get(records_url)
    assert history.status_code == 200, history.text
    assert history.json()["total"] == len(source_ids)


def test_threshold_inclusive_directions_preserve_exact_boundary_and_qc(client):
    """Inclusive comparisons retain equality without admitting suspect evidence."""
    project = create_project(client)
    records_url = f"/api/v1/projects/{project['id']}/scientific-records"
    saved = client.post(
        records_url,
        json={
            "records": [
                observation(value=20, unit="degC", qc="accepted"),
                observation(value=21, unit="degC", qc="accepted"),
                observation(value=19, unit="degC", qc="accepted"),
                observation(value=20, unit="degC", qc="suspect"),
            ]
        },
    )
    assert saved.status_code == 201, saved.text
    ids = [row["id"] for row in saved.json()["items"]]
    url = f"/api/v1/projects/{project['id']}/environment/events/threshold"
    query = {
        "variable": "water_temperature",
        "location": {"latitude": 32.75, "longitude": -79.93},
        "observed_at": "2026-04-03T13:00:00Z",
        "max_distance_m": 1000,
        "max_time_delta_s": 60,
        "source_kinds": ["observed"],
        "threshold_value": 68,
        "threshold_unit": "degF",
    }
    expected = {
        "above": {ids[1]},
        "below": {ids[2]},
        "at_or_above": {ids[0], ids[1]},
        "at_or_below": {ids[0], ids[2]},
    }
    for direction, record_ids in expected.items():
        response = client.post(url, json={**query, "direction": direction})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["direction"] == direction
        assert payload["normalized_threshold"] == pytest.approx(20)
        assert {item["record"]["id"] for item in payload["matches"]} == record_ids
    invalid = client.post(url, json={**query, "direction": "approximately_above"})
    assert invalid.status_code == 422, invalid.text
    history = client.get(records_url)
    assert history.status_code == 200, history.text
    assert history.json()["total"] == len(ids)


def test_threshold_samples_exclude_superseded_noaa_evidence(client):
    from reefvision.schemas.environmental_context import NOAAImportRequest
    from reefvision.services.environmental_context import EnvironmentalContextService

    project = create_project(client)
    raw = noaa_fixture()
    request = NOAAImportRequest(station_id="8665530", day="2026-04-03")
    now = datetime(2026, 4, 4, tzinfo=UTC)
    with (
        client.app.state.session_factory() as session,
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=raw))
        ) as http,
    ):
        original = EnvironmentalContextService(session, http=http, now=now).import_noaa(
            project["id"], request
        )
        raw["data"][0]["v"] = "19.0"
        corrected = EnvironmentalContextService(
            session, http=http, now=now + timedelta(days=1)
        ).import_noaa(project["id"], request)

    url = f"/api/v1/projects/{project['id']}/environment/events/threshold"
    payload = {
        "variable": "water_temperature",
        "location": {"latitude": 32.75, "longitude": -79.93},
        "observed_at": "2026-04-03T13:00:00Z",
        "max_distance_m": 1000,
        "max_time_delta_s": 60,
        "source_kinds": ["observed"],
        "threshold_value": 19.5,
        "threshold_unit": "degC",
        "direction": "above",
    }
    above = client.post(url, json=payload)
    assert above.status_code == 200, above.text
    assert above.json()["matches"] == []

    below = client.post(url, json={**payload, "direction": "below"})
    assert below.status_code == 200, below.text
    assert [item["record"]["id"] for item in below.json()["matches"]] == [
        str(corrected.items[0].id)
    ]
    history = client.get(f"/api/v1/projects/{project['id']}/scientific-records")
    assert history.status_code == 200, history.text
    assert history.json()["total"] == len(original.items) + len(corrected.items)
    previous = next(
        item for item in history.json()["items"] if item["id"] == str(original.items[0].id)
    )
    assert previous["environmental_snapshot_current"] is False


@pytest.mark.parametrize("duplicate_value", ["21.0", ""])
def test_noaa_duplicate_timestamp_rejected_without_persisting(client, duplicate_value):
    """Repeated times, including missing-value rows, are not independent samples."""
    from reefvision.domain.errors import ValidationError
    from reefvision.schemas.environmental_context import NOAAImportRequest
    from reefvision.services.environmental_context import EnvironmentalContextService

    project = create_project(client, "Duplicate NOAA temperature")
    raw = noaa_fixture()
    raw["data"].append({"t": raw["data"][0]["t"], "v": duplicate_value, "f": "0,0,0"})
    with (
        client.app.state.session_factory() as session,
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=raw))
        ) as http,
        pytest.raises(ValidationError, match="Duplicate NOAA sample timestamp"),
    ):
        EnvironmentalContextService(session, http=http).import_noaa(
            project["id"], NOAAImportRequest(station_id="8665530", day="2026-04-03")
        )
    assert client.get(f"/api/v1/projects/{project['id']}/scientific-records").json()["total"] == 0


def test_noaa_duplicate_timestamp_refresh_keeps_prior_offline_snapshot(client):
    """Invalid provider correction must not replace good cached evidence."""
    from reefvision.domain.errors import ValidationError
    from reefvision.schemas.environmental_context import NOAAImportRequest
    from reefvision.services.environmental_context import EnvironmentalContextService

    project = create_project(client, "NOAA duplicate refresh")
    request = NOAAImportRequest(station_id="8665530", day="2026-04-03")
    raw = noaa_fixture()
    baseline_time = datetime(2026, 4, 4, tzinfo=UTC)
    with (
        client.app.state.session_factory() as session,
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=raw))
        ) as http,
    ):
        original = EnvironmentalContextService(session, http=http, now=baseline_time).import_noaa(
            project["id"], request
        )
        raw["data"].append(dict(raw["data"][0]))
        service = EnvironmentalContextService(
            session, http=http, now=baseline_time + timedelta(days=2)
        )
        with pytest.raises(ValidationError, match="Duplicate NOAA sample timestamp"):
            service.import_noaa(project["id"], request)
        offline = service.import_noaa(project["id"], request.model_copy(update={"offline": True}))
    assert offline.cache_status == "stale_offline"
    assert [item.id for item in offline.items] == [item.id for item in original.items]
    assert client.get(f"/api/v1/projects/{project['id']}/scientific-records").json()["total"] == 2


@pytest.mark.parametrize("product", ["temperature", "water_level", "predictions"])
@pytest.mark.parametrize("overflow", ["station", "observation", "many_station_keys"])
def test_noaa_rejects_unbounded_provider_metadata_without_replacing_offline_cache(
    client, product, overflow
):
    """Reject oversize NOAA evidence without replacing previously validated records."""
    from reefvision.domain.errors import ValidationError
    from reefvision.schemas.environmental_context import (
        NOAAImportRequest,
        NOAATideImportRequest,
    )
    from reefvision.services.environmental_context import EnvironmentalContextService

    project = create_project(client, "NOAA provenance budget")
    if product == "temperature":
        request = NOAAImportRequest(station_id="8665530", day="2026-04-03")
        initial = noaa_fixture()
        import_method = "import_noaa"
    else:
        request = NOAATideImportRequest(
            station_id="8665530", day="2026-04-03", product=product, datum="MLLW"
        )
        key = "predictions" if product == "predictions" else "data"
        initial = {
            "metadata": noaa_fixture()["metadata"],
            key: [{"t": "2026-04-03 13:00", "v": "0.24", "s": "0.05", "f": "0,0,0"}],
        }
        import_method = "import_noaa_tides"
    state = {"raw": initial}
    calls = []

    def transport(req):
        calls.append(req)
        return httpx.Response(200, json=state["raw"])

    start = datetime(2026, 4, 4, tzinfo=UTC)
    with (
        client.app.state.session_factory() as session,
        httpx.Client(transport=httpx.MockTransport(transport)) as http,
    ):
        first = getattr(EnvironmentalContextService(session, http=http, now=start), import_method)(
            project["id"], request
        )
        invalid = deepcopy(initial)
        rows = invalid["predictions" if product == "predictions" else "data"]
        if overflow == "station":
            invalid["metadata"]["provider_note"] = "A" * 17000
        elif overflow == "observation":
            rows[0]["provider_note"] = "B" * 17000
        else:
            invalid["metadata"].update({f"field_{index:04d}": "ABCD" for index in range(1800)})
        state["raw"] = invalid
        service = EnvironmentalContextService(session, http=http, now=start + timedelta(days=2))
        with pytest.raises(ValidationError, match="NOAA source metadata exceeds 16 KiB"):
            getattr(service, import_method)(project["id"], request)
        offline = getattr(service, import_method)(
            project["id"], request.model_copy(update={"offline": True})
        )
    assert offline.cache_status == "stale_offline"
    assert [item.id for item in offline.items] == [item.id for item in first.items]
    assert len(calls) == 2


@pytest.mark.parametrize("invalid", [float("nan"), "\ud800"], ids=["nonfinite", "invalid_utf8"])
@pytest.mark.parametrize("product", ["temperature", "predictions"])
def test_noaa_rejects_non_json_or_non_utf8_provenance_before_persistence(invalid, product):
    """Direct parsers must reject malformed provider data, not truncate or coerce it."""
    from reefvision.domain.errors import ValidationError
    from reefvision.schemas.environmental_context import (
        NOAAImportRequest,
        NOAATideImportRequest,
    )
    from reefvision.services.noaa_environment import parse_noaa, parse_noaa_tides

    station = noaa_fixture()["metadata"]
    station["provider_note"] = invalid
    now = datetime(2026, 4, 4, tzinfo=UTC)
    if product == "temperature":
        raw = {"metadata": station, "data": noaa_fixture()["data"]}
        request = NOAAImportRequest(station_id="8665530", day="2026-04-03")
        parser = parse_noaa
    else:
        raw = {
            "metadata": station,
            "predictions": [{"t": "2026-04-03 13:00", "v": "0.24"}],
        }
        request = NOAATideImportRequest(
            station_id="8665530", day="2026-04-03", product="predictions", datum="MLLW"
        )
        parser = parse_noaa_tides
    with pytest.raises(ValidationError, match="NOAA source metadata is not finite"):
        parser(raw, request, now, "https://api.tidesandcurrents.noaa.gov/test")


@pytest.mark.parametrize(
    ("product", "field", "invalid"),
    [
        ("water_temperature", "v", True),
        ("water_temperature", "lat", False),
        ("water_temperature", "lon", True),
        ("water_temperature", "v", "Infinity"),
        ("predictions", "v", False),
        ("predictions", "lat", True),
        ("water_level", "v", True),
        ("water_level", "lon", False),
        ("water_level", "s", False),
        ("water_level", "s", "NaN"),
    ],
)
def test_noaa_invalid_numeric_refresh_preserves_offline_snapshot(client, product, field, invalid):
    """Booleans must not become real zero/one observations or uncertainty."""
    from reefvision.domain.errors import ValidationError
    from reefvision.schemas.environmental_context import NOAAImportRequest, NOAATideImportRequest
    from reefvision.services.environmental_context import EnvironmentalContextService

    project = create_project(client, "NOAA numeric QC")
    raw = noaa_fixture()
    # An actual numeric zero is distinct from false and must remain usable.
    raw["data"][0]["v"] = 0
    raw["data"][0]["s"] = "0.02"
    key = "data"
    if product == "water_temperature":
        request = NOAAImportRequest(station_id="8665530", day="2026-04-03")
        method = "import_noaa"
    else:
        request = NOAATideImportRequest(
            station_id="8665530", day="2026-04-03", product=product, datum="MLLW"
        )
        method = "import_noaa_tides"
        if product == "predictions":
            key = "predictions"
            raw[key] = raw.pop("data")

    now = datetime(2026, 4, 4, tzinfo=UTC)
    with (
        client.app.state.session_factory() as session,
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=raw))
        ) as http,
    ):
        service = EnvironmentalContextService(session, http=http, now=now)
        first = getattr(service, method)(project["id"], request)
        assert len(first.items) == 2 and first.skipped_missing == 1
        assert first.items[0].normalized_value == 0
        original_ids = [item.id for item in first.items]
        target = raw["metadata"] if field in {"lat", "lon"} else raw[key][0]
        target[field] = invalid
        expired = EnvironmentalContextService(session, http=http, now=now + timedelta(days=2))
        with pytest.raises(ValidationError, match="NOAA numeric fields"):
            getattr(expired, method)(project["id"], request)
        cached = getattr(expired, method)(
            project["id"], request.model_copy(update={"offline": True})
        )
        assert cached.cache_status == "stale_offline"
        assert [item.id for item in cached.items] == original_ids
        assert cached.items[0].normalized_value == 0
        assert cached.skipped_missing == 1

    records = client.get(f"/api/v1/projects/{project['id']}/scientific-records").json()
    assert records["total"] == 2
