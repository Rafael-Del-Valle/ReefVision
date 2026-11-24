"""Historical scientific records stay auditable when environmental caches are corrupt."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select

from reefvision.db.models.scientific_record import EnvironmentalCacheEntry, ScientificRecord
from reefvision.domain.errors import ConflictError
from reefvision.schemas.environmental_context import NOAAImportRequest
from reefvision.services.environmental_context import EnvironmentalContextService
from reefvision.services.scientific_data import content_hash
from reefvision.tests.test_annotations import create_project
from reefvision.tests.test_environmental_context import noaa_fixture


@pytest.mark.parametrize(
    "damage",
    [
        "missing_record_ids",
        "record_ids_not_list",
        "record_ids_non_string",
        "duplicate_record_ids",
        "missing_member_record_id",
        "missing_cache_identity",
        "null_cache_identity",
        "list_cache_identity",
        "boolean_cache_identity",
        "wrong_cache_identity",
        "wrong_source_url",
        "missingness_is_boolean",
        "missingness_is_negative",
        "provider_response_not_object",
        "whole_payload_not_object",
    ],
)
def test_scientific_record_listing_flags_malformed_rehashed_cache_as_not_current(client, damage):
    """No false currentness or 500s; original scientific rows remain immutable."""
    project = create_project(client, "Cache integrity audit")
    record_url = f"/api/v1/projects/{project['id']}/scientific-records"
    request = NOAAImportRequest(station_id="8665530", day="2026-04-03")
    with (
        client.app.state.session_factory() as session,
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=noaa_fixture()))
        ) as http,
    ):
        imported = EnvironmentalContextService(
            session, http=http, now=datetime(2026, 4, 4, tzinfo=UTC)
        ).import_noaa(project["id"], request)
    original_ids = {str(item.id) for item in imported.items}
    assert len(original_ids) == 2
    valid = client.get(record_url)
    assert valid.status_code == 200, valid.text
    assert {item["id"] for item in valid.json()["items"]} == original_ids
    assert all(item["environmental_snapshot_current"] for item in valid.json()["items"])

    with client.app.state.session_factory() as session:
        entry = session.scalar(select(EnvironmentalCacheEntry))
        assert entry is not None
        payload = deepcopy(entry.payload_json)
        if damage == "missing_record_ids":
            del payload["record_ids"]
        elif damage == "record_ids_not_list":
            payload["record_ids"] = {"id": payload["record_ids"][0]}
        elif damage == "record_ids_non_string":
            payload["record_ids"][0] = 42
        elif damage == "duplicate_record_ids":
            payload["record_ids"][1] = payload["record_ids"][0]
        elif damage == "missing_member_record_id":
            # Preserve both genuine IDs; an invented additional member must
            # invalidate the entire acquisition, not only the missing row.
            payload["record_ids"].append("00000000-0000-4000-8000-000000000000")
        elif damage == "missing_cache_identity":
            del payload["cache_identity"]
        elif damage == "null_cache_identity":
            payload["cache_identity"] = None
        elif damage == "list_cache_identity":
            payload["cache_identity"] = ["unexpected"]
        elif damage == "boolean_cache_identity":
            payload["cache_identity"] = False
        elif damage == "wrong_cache_identity":
            payload["cache_identity"]["source_url"] += "&foreign=1"
        elif damage == "wrong_source_url":
            entry.source_url += "&foreign=1"
        elif damage == "missingness_is_boolean":
            payload["skipped_missing"] = False
        elif damage == "missingness_is_negative":
            payload["skipped_missing"] = -1
        elif damage == "provider_response_not_object":
            payload["provider_response"] = ["invalid"]
        else:
            payload = ["invalid"]
        entry.payload_json = payload
        entry.content_sha256 = content_hash(payload)
        session.commit()

    # History remains independently auditable; a tampered provider cache
    # cannot be presented as current environmental evidence.
    invalid = client.get(record_url)
    assert invalid.status_code == 200, invalid.text
    listed = invalid.json()["items"]
    assert {item["id"] for item in listed} == original_ids
    assert all(item["environmental_snapshot_current"] is False for item in listed)
    with client.app.state.session_factory() as session:
        rows = session.scalars(
            select(ScientificRecord).where(ScientificRecord.project_id == project["id"])
        ).all()
        assert {row.id for row in rows} == original_ids
        assert all(content_hash(row.payload_json) == row.content_sha256 for row in rows)


@pytest.mark.parametrize("damage", ["payload", "checksum"])
def test_dataset_inventory_rejects_corrupt_observation_checksum(client, damage):
    """Intact cache metadata cannot authenticate a damaged member observation."""
    project = create_project(client, "Environmental member integrity")
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
        assert len(original_ids) == 2
        entry = session.scalar(select(EnvironmentalCacheEntry))
        assert entry is not None
        cache_key = entry.cache_key
        cache_checksum = entry.content_sha256
        assert service.datasets(project["id"]).items[0].record_count == 2

        healthy = session.get(ScientificRecord, str(imported.items[0].id))
        row = session.get(ScientificRecord, str(imported.items[1].id))
        assert healthy is not None and row is not None
        assert service.science.response(healthy).environmental_snapshot_current is True
        healthy_checksum = healthy.content_sha256
        original_payload = deepcopy(row.payload_json)
        original_checksum = row.content_sha256
        if damage == "payload":
            row.payload_json = {**original_payload, "unexpected_test_corruption": True}
        else:
            row.content_sha256 = "0" * 64
        session.commit()

        assert entry.content_sha256 == cache_checksum == content_hash(entry.payload_json)
        # The intact sibling remains auditable, but cannot be shown as current.
        historical = service.science.response(healthy)
        assert historical.id == imported.items[0].id
        assert historical.environmental_snapshot_current is False
        assert healthy.content_sha256 == healthy_checksum
        with pytest.raises(ConflictError, match="member checksum mismatch"):
            service.datasets(project["id"])
        with pytest.raises(ConflictError, match="member checksum mismatch"):
            service.cached_dataset(project["id"], cache_key)

        # Restore only the test fixture and establish that genuine data is reusable.
        row.payload_json = original_payload
        row.content_sha256 = original_checksum
        session.commit()
        assert service.datasets(project["id"]).items[0].record_count == 2
        recovered = service.cached_dataset(project["id"], cache_key)
        assert service.science.response(healthy).environmental_snapshot_current is True
        assert all(item.environmental_snapshot_current for item in recovered.items)
        assert {str(item.id) for item in recovered.items} == original_ids
        assert entry.content_sha256 == cache_checksum
